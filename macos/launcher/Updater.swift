// Update checks and installs, for release builds only (milestone 6). Dev builds don't create an Updater.
//
// The decisions are elsewhere and tested: when to check (UpdateSchedule), what counts as a release
// (ReleaseInfo), whether a download may be installed (installProblem, Signature) and in what order
// (installOrder). This file does the network, file and process work, and talks to the user.
// The only internet use in LoupedeckBridge: api.github.com and GitHub's release downloads.

import AppKit

final class Updater {
    static let latestURL = URL(string: "https://api.github.com/repos/MegaMattMiller/LoupedeckBridge/releases/latest")!

    struct Failure: Error {
        let step: InstallStep
        let reason: String
    }

    enum Phase: Equatable { case idle, checking, installing(InstallStep) }

    let current: Version
    private(set) var available: ReleaseInfo?       // a newer release, once a check has found one
    private(set) var phase: Phase = .idle
    private(set) var target = ""                   // what's being installed: "v0.5.1"

    // From the app (StatusMenu.swift):
    var notify: (_ title: String, _ body: String) -> Void = { _, _ in }
    var stopBridge: (_ then: @escaping () -> Void) -> Void = { $0() }    // the Quit path, without quitting
    var restartBridge: () -> Void = {}

    private let pinnedSHA256: String
    private let userAgent: String
    private let schedule = UpdateSchedule()
    private var notice: UpdateNotice
    private let launched = Date()
    private var timer: Timer?
    private let defaults = UserDefaults.standard

    /// nil for dev builds, and for a build without a readable version.
    init?(info: [String: Any]) {
        guard (info["LBIsDev"] as? Bool) != true,
              let version = (info["LBVersion"] as? String).flatMap(Version.init) else { return nil }
        current = version
        pinnedSHA256 = info["LBSignerSHA256"] as? String ?? ""
        userAgent = "LoupedeckBridge/\(version)"
        // What earlier runs found and announced (start at login relaunches the app every day).
        available = ReleaseInfo.restore(defaults.dictionary(forKey: "availableRelease"), newerThan: version,
                                        arch: runningArch)
        notice = UpdateNotice(lastAnnounced: defaults.string(forKey: "announcedVersion").flatMap(Version.init))
        if available == nil { defaults.removeObject(forKey: "availableRelease") }   // installed, or unreadable
    }

    /// "Check for updates automatically" (on unless turned off).
    var automatic: Bool {
        get { defaults.object(forKey: "autoUpdateCheck") as? Bool ?? true }
        set { defaults.set(newValue, forKey: "autoUpdateCheck") }
    }

    /// The version the last update replaced, if it's still in the Trash.
    var previous: (url: URL, version: String)? {
        guard let path = defaults.string(forKey: "previousAppPath"), FileManager.default.fileExists(atPath: path)
        else { return nil }
        let url = URL(fileURLWithPath: path)
        let plist = NSDictionary(contentsOf: url.appendingPathComponent("Contents/Info.plist"))
        return (url, plist?["LBVersion"] as? String ?? "?")
    }

    // ---- checking -------------------------------------------------------------
    func start() {
        DispatchQueue.main.asyncAfter(deadline: .now() + schedule.firstDelay + 1) { [weak self] in self?.checkIfDue() }
        timer = Timer.scheduledTimer(withTimeInterval: 3600, repeats: true) { [weak self] _ in self?.checkIfDue() }
    }

    func checkIfDue() {
        guard phase == .idle,
              schedule.shouldCheck(now: Date(), lastCheck: defaults.object(forKey: "lastUpdateCheck") as? Date,
                                   enabled: automatic, isDev: false, sinceLaunch: Date().timeIntervalSince(launched))
        else { return }
        check(manual: false)
    }

    /// "Check for updates now": says what it found, even "up to date".
    func checkNow() {
        guard phase == .idle else { return }
        check(manual: true)
    }

    private func check(manual: Bool) {
        phase = .checking
        var request = URLRequest(url: Updater.latestURL, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 15)
        request.setValue(userAgent, forHTTPHeaderField: "User-Agent")
        request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        URLSession.shared.dataTask(with: request) { data, response, error in
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            let release = status == 200 ? data.flatMap { ReleaseInfo.parse($0, arch: runningArch) } : nil
            let why = error?.localizedDescription
                ?? (status == 200 ? "GitHub's answer had no \(runningArch) Mac release in it" : "GitHub answered \(status)")
            DispatchQueue.main.async { self.checked(release, why: why, manual: manual) }
        }.resume()
    }

    private func checked(_ release: ReleaseInfo?, why: String, manual: Bool) {
        phase = .idle
        defaults.set(Date(), forKey: "lastUpdateCheck")    // a failed check also waits a day: no alert, no retry storm
        guard let release = release else {
            BridgeProcess.log("update check failed: \(why)")
            if manual { tell("Couldn't check for updates", "\(why). Try again later.") }
            return
        }
        guard release.version > current else {
            available = nil
            defaults.removeObject(forKey: "availableRelease")
            BridgeProcess.log("update check: up to date (v\(current))")
            if manual { tell("LoupedeckBridge is up to date", "v\(current) is the newest version.") }
            return
        }
        available = release
        defaults.set(release.saved, forKey: "availableRelease")
        BridgeProcess.log("update check: v\(release.version) is available (this is v\(current))")
        let first = notice.announce(release.version, current: current)
        if first, let announced = notice.lastAnnounced { defaults.set(announced.description, forKey: "announcedVersion") }
        if manual {
            installAvailable()
        } else if first {
            notify("LoupedeckBridge v\(release.version) is available",
                   "To install it, click LoupedeckBridge's menu-bar icon and choose Install.")
        }
    }

    // ---- installing (installOrder: download, unzip, verify, stopBridge, moveOldToTrash, moveNewIntoPlace,
    // launchNew). Nothing is stopped or moved until every check has passed. ----------------------------------

    /// "Update available: v… – Install…"
    func installAvailable() {
        guard phase == .idle, let release = available,
              ask("Install LoupedeckBridge v\(release.version)?",
                  "You have v\(current). LoupedeckBridge restarts with the new version, and this one goes to the Trash.",
                  ok: "Install") else { return }
        begin("v\(release.version)", at: .download)
        let (pinned, current, agent) = (pinnedSHA256, self.current, userAgent)
        DispatchQueue.global(qos: .userInitiated).async {
            let result = Result {
                try Updater.prepare(release, pinned: pinned, current: current, userAgent: agent) { step in
                    DispatchQueue.main.async { self.phase = .installing(step) }
                }
            }
            DispatchQueue.main.async {
                switch result {
                case .success(let app): self.swapIn(app, scratch: app.deletingLastPathComponent().deletingLastPathComponent())
                case .failure(let error): self.failed(error)
                }
            }
        }
    }

    /// "Go back to the previous version (v…)…": the copy in the Trash, checked the same way (older is allowed).
    func goBack() {
        guard phase == .idle, let previous = previous,
              ask("Go back to LoupedeckBridge v\(previous.version)?",
                  "v\(current) goes to the Trash, and v\(previous.version) starts in its place.", ok: "Go back")
        else { return }
        begin("v\(previous.version)", at: .verify)
        let (pinned, current) = (pinnedSHA256, self.current)
        DispatchQueue.global(qos: .userInitiated).async {
            let result = Result { try Updater.verify([previous.url], pinned: pinned, current: current, expected: nil,
                                                     allowOlder: true) }
            DispatchQueue.main.async {
                switch result {
                case .success: self.swapIn(previous.url, scratch: nil)
                case .failure(let error): self.failed(error)
                }
            }
        }
    }

    private func begin(_ what: String, at step: InstallStep) {
        target = what
        phase = .installing(step)
        BridgeProcess.log("update: installing \(what)")
    }

    /// Off the main thread: download, check the SHA-256, unzip, and verify. Returns the checked app, inside a
    /// new temporary folder.
    private static func prepare(_ release: ReleaseInfo, pinned: String, current: Version, userAgent: String,
                                progress: (InstallStep) -> Void) throws -> URL {
        let fm = FileManager.default
        let scratch = fm.temporaryDirectory.appendingPathComponent("LoupedeckBridge-update-\(UUID().uuidString)")
        do {
            try? fm.createDirectory(at: scratch, withIntermediateDirectories: true)
            let name = ReleaseInfo.assetName(for: release.version, arch: runningArch)
            let zip = try fetch(release.zipURL, to: scratch.appendingPathComponent(name), limit: maxDownload,
                                userAgent: userAgent)
            let sums = try fetch(release.sha256URL, to: scratch.appendingPathComponent(name + ".sha256"), limit: 4096,
                                 userAgent: userAgent)
            let expected = (try? String(contentsOf: sums.file, encoding: .utf8))?
                .split(whereSeparator: \.isWhitespace).first?.lowercased()
            guard expected == zip.sha256 else { throw Failure(step: .download, reason: "its SHA-256 doesn't match") }

            progress(.unzip)
            let unzipped = scratch.appendingPathComponent("unzipped")
            let (status, errors) = runCapturingErrors("/usr/bin/ditto", "-x", "-k", zip.file.path, unzipped.path)
            guard status == 0 else { throw Failure(step: .unzip, reason: unzipProblem(errors)) }

            progress(.verify)
            let apps = ((try? fm.contentsOfDirectory(at: unzipped, includingPropertiesForKeys: nil)) ?? [])
                .filter { $0.pathExtension == "app" }
            try verify(apps, pinned: pinned, current: current, expected: release.version, allowOlder: false)
            return apps[0]
        } catch {
            try? fm.removeItem(at: scratch)
            throw error
        }
    }

    /// Every check an install must pass (Policies.swift's installProblem, with Signature.swift's check).
    private static func verify(_ apps: [URL], pinned: String, current: Version, expected: Version?,
                               allowOlder: Bool) throws {
        let plist = apps.count == 1 ? NSDictionary(contentsOf: apps[0].appendingPathComponent("Contents/Info.plist")) : nil
        let version = (plist?["LBVersion"] as? String).flatMap(Version.init)
        let signature = apps.count == 1
            ? Signature.problem(app: apps[0], identifier: releaseBundleID, pinnedSHA256: pinned) : "not checked"
        if let why = signature, apps.count == 1 { BridgeProcess.log("update: signature check: \(why)", level: "WARNING") }
        if let problem = installProblem(bundleID: plist?["CFBundleIdentifier"] as? String ?? "", version: version,
                                        current: current, signatureOK: signature == nil, appCount: apps.count,
                                        allowOlder: allowOlder) {
            throw Failure(step: .verify, reason: problem)
        }
        if let expected = expected, let version = version, version != expected {
            throw Failure(step: .verify, reason: "it says it's v\(version), not v\(expected)")
        }
        // As tools/install.sh does: the download says which Mac it's for, and that's checked, not trusted.
        // A wrong-arch app can't launch, so installing one would leave no working LoupedeckBridge at all.
        if let arch = plist?["LBArch"] as? String, arch != runningArch {
            throw Failure(step: .verify, reason: "it's the \(arch) build, not \(runningArch)")
        }
    }

    /// Main thread, after every check passed: stop the bridge, swap the apps, start the new one, exit.
    private func swapIn(_ new: URL, scratch: URL?) {
        phase = .installing(.stopBridge)
        stopBridge { [weak self] in self?.replaceRunningApp(with: new, scratch: scratch) }
    }

    private func replaceRunningApp(with new: URL, scratch: URL?) {
        let fm = FileManager.default
        let running = Bundle.main.bundleURL
        func cleanUp() { if let scratch = scratch { try? fm.removeItem(at: scratch) } }

        phase = .installing(.moveOldToTrash)
        var trashed: NSURL?
        do {
            try fm.trashItem(at: running, resultingItemURL: &trashed)
        } catch {
            cleanUp()
            return abandon(Failure(step: .moveOldToTrash, reason: error.localizedDescription))
        }
        guard let old = trashed as URL? else {
            cleanUp()
            return abandon(Failure(step: .moveOldToTrash, reason: "macOS didn't say where in the Trash it went; " +
                                   "put LoupedeckBridge back in Applications from the Trash"))
        }

        // From here, a failure puts this version back where it was.
        func putBack(_ step: InstallStep, _ reason: String) {
            var why = reason
            if (try? fm.moveItem(at: old, to: running)) == nil {
                why += ". This version is in the Trash: move it back to \(running.deletingLastPathComponent().path)"
            }
            cleanUp()
            abandon(Failure(step: step, reason: why))
        }
        phase = .installing(.moveNewIntoPlace)
        do {
            try fm.moveItem(at: new, to: running)
        } catch {
            return putBack(.moveNewIntoPlace, error.localizedDescription)
        }
        phase = .installing(.launchNew)
        guard Updater.run("/usr/bin/open", "-n", running.path) == 0 else {
            try? fm.trashItem(at: running, resultingItemURL: nil)         // the new one, which didn't start
            return putBack(.launchNew, "macOS didn't start it")
        }
        defaults.set(old.path, forKey: "previousAppPath")
        cleanUp()
        BridgeProcess.log("update: \(target) started; v\(current) is in the Trash (\(old.path))")
        NSApp.terminate(nil)
    }

    /// A failure after the bridge was stopped: bring it back, then say what happened.
    private func abandon(_ failure: Failure) {
        restartBridge()
        failed(failure)
    }

    private func failed(_ error: Error) {
        let failure = error as? Failure ?? Failure(step: .download, reason: error.localizedDescription)
        phase = .idle
        BridgeProcess.log("update to \(target) failed while \(failure.step.label): \(failure.reason)", level: "ERROR")
        tell("Couldn't install LoupedeckBridge \(target)",
             "It failed while \(failure.step.label): \(failure.reason).\n\nThis version (v\(current)) keeps running.")
    }

    // ---- helpers ----------------------------------------------------------------
    /// 200 MB: a release is about 30 MB, so a bigger download isn't one (Download.swift stops it).
    private static let maxDownload: Int64 = 200 * 1_048_576

    /// A capped download for the background queue (Download.swift), as a download-step failure.
    private static func fetch(_ url: URL, to file: URL, limit: Int64, userAgent: String) throws -> Download.Done {
        do {
            return try Download.fetch(url, to: file, limit: limit, userAgent: userAgent)
        } catch let failure as Download.Failure {
            throw Failure(step: .download, reason: failure.reason)
        }
    }

    /// Runs a tool and returns its exit status and what it wrote to stderr.
    private static func runCapturingErrors(_ tool: String, _ args: String...) -> (Int32, String) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: tool)
        process.arguments = args
        process.standardOutput = FileHandle.nullDevice
        let errors = Pipe()
        process.standardError = errors
        guard (try? process.run()) != nil else { return (-1, "couldn't run \(tool)") }
        let text = String(decoding: errors.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
        process.waitUntilExit()
        return (process.terminationStatus, text)
    }

    @discardableResult
    private static func run(_ tool: String, _ args: String...) -> Int32 {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: tool)
        process.arguments = args
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        guard (try? process.run()) != nil else { return -1 }
        process.waitUntilExit()
        return process.terminationStatus
    }

    private func tell(_ title: String, _ text: String) {
        _ = ask(title, text, ok: "OK", cancel: nil)
    }

    /// A dialog in front of other apps (this is a menu-bar app). True if the first button was chosen.
    private func ask(_ title: String, _ text: String, ok: String, cancel: String? = "Cancel") -> Bool {
        NSApp.activate()
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = text
        alert.addButton(withTitle: ok)
        if let cancel = cancel { alert.addButton(withTitle: cancel) }
        return alert.runModal() == .alertFirstButtonReturn
    }
}

extension InstallStep {
    /// For "It failed while …" and the menu's "Installing v…: …".
    var label: String {
        switch self {
        case .download: return "downloading"
        case .unzip: return "unzipping"
        case .verify: return "checking the download"
        case .stopBridge: return "stopping the bridge"
        case .moveOldToTrash: return "moving this version to the Trash"
        case .moveNewIntoPlace: return "putting the new version in place"
        case .launchNew: return "starting the new version"
        }
    }
}
