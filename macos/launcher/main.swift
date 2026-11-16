// LoupedeckBridge.app launcher.
//
// macOS grants the Accessibility (keyboard) permission to the *app* that started a process.
// This tiny app starts the repo's Python bridge as a CHILD process (posix_spawn, not exec),
// so the permission belongs to LoupedeckBridge rather than to Terminal or the Claude app.
// The Python code is read from the repo at run time: editing it never needs a rebuild.

import Foundation

let info = Bundle.main.infoDictionary ?? [:]
guard let repo = info["LBRepoPath"] as? String else {
    fputs("LoupedeckBridge: LBRepoPath is missing from Info.plist; rebuild with tools/build_mac_app.sh\n", stderr)
    exit(2)
}
let python = repo + "/.venv/bin/python"
let argv = [python, "-m", "bridge"] + CommandLine.arguments.dropFirst()

FileManager.default.changeCurrentDirectoryPath(repo)
var cArgs: [UnsafeMutablePointer<CChar>?] = argv.map { strdup($0) } + [nil]
var child: pid_t = 0
let rc = posix_spawn(&child, python, nil, nil, &cArgs, environ)
guard rc == 0 else {
    fputs("LoupedeckBridge: couldn't start \(python): \(String(cString: strerror(rc)))\n", stderr)
    exit(1)
}

// Pass stop requests on to the bridge, so it can release held keys and close cleanly.
var signalSources: [DispatchSourceSignal] = []
for sig in [SIGTERM, SIGINT, SIGHUP] {
    signal(sig, SIG_IGN)
    let source = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    source.setEventHandler { kill(child, sig) }
    source.resume()
    signalSources.append(source)
}

DispatchQueue.global().async {
    var status: Int32 = 0
    while waitpid(child, &status, 0) == -1 && errno == EINTR {}
    let signalled = status & 0x7f
    exit(signalled == 0 ? (status >> 8) & 0xff : 128 + signalled)
}
dispatchMain()
