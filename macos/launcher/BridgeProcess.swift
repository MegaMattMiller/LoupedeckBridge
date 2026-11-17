// The Python bridge as a child process: where its output goes, its status pipe, and stopping it.

import CoreGraphics
import Foundation

final class BridgeProcess {
    static var logURL = FileManager.default.homeDirectoryForCurrentUser   // var: tests point it elsewhere
        .appendingPathComponent("Library/Logs/loupedeck-lr-bridge/bridge.log")
    static let statusFD: Int32 = 3                 // bridge/status.py STATUS_FD_ENV points here
    /// Every key the bridge can hold down (bridge/platform/macos_keys.py KEYCODES):
    /// Shift, Ctrl, Alt, Cmd, Tab and the four arrows.
    static let holdableKeys: [CGKeyCode] = [56, 59, 58, 55, 48, 123, 124, 125, 126]

    let python: String
    let workdir: String
    let arguments: [String]
    var onStatus: ((BridgeStatus) -> Void)?
    var onExit: ((Int32) -> Void)?
    private(set) var pid: pid_t = 0
    private(set) var running = false

    init(python: String, workdir: String, arguments: [String]) {
        self.python = python
        self.workdir = workdir
        self.arguments = arguments
    }

    // ---- the log ------------------------------------------------------------
    /// The launcher's own messages go to the bridge's log, in its format.
    static func log(_ message: String, level: String = "INFO") {
        let stamp = DateFormatter()
        stamp.locale = Locale(identifier: "en_US_POSIX")
        stamp.dateFormat = "yyyy-MM-dd HH:mm:ss,SSS"
        let line = "\(stamp.string(from: Date())) \(level.padding(toLength: 7, withPad: " ", startingAt: 0)) launcher: \(message)\n"
        let fd = openLog()
        if fd >= 0 {
            _ = line.withCString { write(fd, $0, strlen($0)) }
            close(fd)
        }
        fputs(line, stderr)
    }

    private static func openLog() -> Int32 {
        try? FileManager.default.createDirectory(at: logURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        return open(logURL.path, O_WRONLY | O_APPEND | O_CREAT, 0o644)
    }

    // ---- starting -----------------------------------------------------------
    /// Spawns `<python> -E -B -m bridge …` in `workdir` (the repo, or the app's bundled code), with stdout and
    /// stderr appended to the log (so a crash before logging starts is still recorded) and, if given,
    /// `statusWrite` as fd 3.
    private static func spawn(python: String, workdir: String, arguments: [String], statusWrite: Int32?,
                              closeInChild: Int32?) -> pid_t? {
        let logFD = openLog()
        var actions: posix_spawn_file_actions_t?
        posix_spawn_file_actions_init(&actions)
        defer { posix_spawn_file_actions_destroy(&actions) }
        // Order matters: the pipe's read end is often fd 3 itself, so close it *before* putting the write
        // end on fd 3 (closing it afterwards closed the status pipe: "Bad file descriptor", live check).
        if let r = closeInChild { posix_spawn_file_actions_addclose(&actions, r) }
        if logFD >= 0 {
            posix_spawn_file_actions_adddup2(&actions, logFD, 1)
            posix_spawn_file_actions_adddup2(&actions, logFD, 2)
        }
        if let w = statusWrite {
            posix_spawn_file_actions_adddup2(&actions, w, statusFD)
            if w != statusFD { posix_spawn_file_actions_addclose(&actions, w) }
        }
        if logFD > 2 && logFD != statusFD { posix_spawn_file_actions_addclose(&actions, logFD) }

        var env = ProcessInfo.processInfo.environment
        env["LB_STATUS_FD"] = statusWrite == nil ? nil : String(statusFD)
        // -B: never write __pycache__ (a release's bundle is signed, and comes precompiled)
        var cArgs: [UnsafeMutablePointer<CChar>?] = ([python, "-E", "-B", "-m", "bridge"] + arguments).map { strdup($0) } + [nil]
        var cEnv: [UnsafeMutablePointer<CChar>?] = env.map { strdup("\($0.key)=\($0.value)") } + [nil]
        defer { (cArgs + cEnv).forEach { free($0) } }

        FileManager.default.changeCurrentDirectoryPath(workdir)
        var child: pid_t = 0
        let rc = posix_spawn(&child, python, &actions, nil, &cArgs, &cEnv)
        if logFD >= 0 { close(logFD) }
        guard rc == 0 else {
            log("couldn't start \(python): \(String(cString: strerror(rc)))", level: "ERROR")
            return nil
        }
        return child
    }

    /// Starts the bridge with its status pipe; false if it couldn't start (the reason is logged).
    func start() -> Bool {
        var fds: [Int32] = [-1, -1]
        guard pipe(&fds) == 0 else {
            Self.log("couldn't make the status pipe: \(String(cString: strerror(errno)))", level: "ERROR")
            return false
        }
        let child = Self.spawn(python: python, workdir: workdir, arguments: arguments, statusWrite: fds[1],
                               closeInChild: fds[0])
        close(fds[1])                              // only the bridge writes
        guard let pid = child else {
            close(fds[0])
            return false
        }
        self.pid = pid
        running = true
        readStatus(from: fds[0])
        waitForExit(pid)
        return true
    }

    /// For one-shot runs (`--check-permission`): no pipe, no menu; returns the bridge's exit code.
    static func runOnce(paths: RuntimePaths, arguments: [String]) -> Int32 {
        guard let child = spawn(python: paths.python, workdir: paths.workdir, arguments: arguments, statusWrite: nil,
                                closeInChild: nil) else { return 1 }
        return wait(for: child)
    }

    // ---- running ------------------------------------------------------------
    private func readStatus(from fd: Int32) {
        DispatchQueue.global(qos: .utility).async { [weak self] in
            var pending = Data()
            var chunk = [UInt8](repeating: 0, count: 4096)
            while true {
                let n = read(fd, &chunk, chunk.count)
                if n < 0 && errno == EINTR { continue }
                if n <= 0 { break }                // the bridge exited (or closed its end)
                pending.append(contentsOf: chunk[0..<n])
                while let newline = pending.firstIndex(of: 0x0A) {
                    let line = String(data: pending[pending.startIndex..<newline], encoding: .utf8) ?? ""
                    pending = Data(pending[pending.index(after: newline)...])
                    if let status = BridgeStatus.parse(line) {
                        DispatchQueue.main.async { self?.onStatus?(status) }
                    }
                }
            }
            close(fd)
        }
    }

    private func waitForExit(_ child: pid_t) {
        DispatchQueue.global().async { [weak self] in
            let code = Self.wait(for: child)
            DispatchQueue.main.async {
                self?.running = false
                self?.onExit?(code)
            }
        }
    }

    /// The child's exit code; 128 + the signal number if a signal ended it (as a shell reports it).
    private static func wait(for child: pid_t) -> Int32 {
        var status: Int32 = 0
        while waitpid(child, &status, 0) == -1 && errno == EINTR {}
        let signalled = status & 0x7f
        return signalled == 0 ? (status >> 8) & 0xff : 128 + signalled
    }

    // ---- stopping -----------------------------------------------------------
    /// SIGTERM: the bridge lets go of held keys and closes cleanly. SIGKILL if it's still there after 5 s.
    func stop() {
        guard running else { return }
        let child = pid
        kill(child, SIGTERM)
        DispatchQueue.main.asyncAfter(deadline: .now() + 5) { [weak self] in
            guard let self = self, self.running, self.pid == child else { return }
            Self.log("the bridge didn't stop within 5 s; forcing it", level: "WARNING")
            kill(child, SIGKILL)
        }
    }

    /// After the bridge ended without its own clean-up (killed, crashed): let go of every key it could hold.
    /// Harmless when nothing was held.
    static func releaseKeys() {
        for code in holdableKeys {
            guard let up = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: false) else { continue }
            up.flags = []
            up.post(tap: .cghidEventTap)
        }
    }
}
