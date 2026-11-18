// The menu-bar app's rules, kept free of AppKit so tests/PolicyTests.swift can check them directly:
// - which status lines the bridge sends (bridge/status.py),
// - when to alert (AlertPolicy), and
// - when to restart a bridge that stopped (RestartPolicy).
// Time is seconds as a plain Double (the app passes a monotonic clock).

import Foundation

/// One status line from the bridge.
struct BridgeStatus: Decodable, Equatable {
    var loupedeck: Bool
    var lightroom: Bool
    var keys: String          // "allowed", "missing" or "unavailable"
    var five_mode: String     // "ratings", "colours" or "keys"
    var settings_url: String?

    /// The status in one line of the bridge's output, or nil for anything else.
    static func parse(_ line: String) -> BridgeStatus? {
        guard let data = line.data(using: .utf8) else { return nil }
        return try? JSONDecoder().decode(BridgeStatus.self, from: data)
    }
}

enum Alert: Equatable {
    case disconnected
    case back
    case keysMissing
    case bridgeStopped(willRestart: Bool)
}

/// When to alert about the Loupedeck and the keyboard permission (the design's rules):
/// - "disconnected" only for a Loupedeck that was connected during this run (armed by the first connect),
///   still gone after `debounce` seconds, not within `wakeGrace` of a wake, at most once per `minInterval`
///   (a held-back alert fires later if it's still gone);
/// - "back" only after a "disconnected" was shown;
/// - "keys missing" once per run.
struct AlertPolicy {
    var debounce = 3.0
    var wakeGrace = 15.0
    var minInterval = 60.0

    private var armed = false              // a Loupedeck has connected during this run
    private var connected = false
    private var goneSince: Double?         // a drop waiting to become an alert
    private var shownDisconnect = false    // so "back" follows only a shown "disconnected"
    private var lastDisconnect = -Double.infinity
    private var wakeUntil = -Double.infinity
    private var keysAlerted = false

    mutating func status(_ s: BridgeStatus, at now: Double) -> [Alert] {
        var out: [Alert] = []
        if s.keys == "missing" && !keysAlerted {
            keysAlerted = true
            out.append(.keysMissing)
        }
        if s.loupedeck {
            armed = true
            goneSince = nil
            if shownDisconnect {
                shownDisconnect = false
                out.append(.back)
            }
        } else if connected && armed && goneSince == nil {
            goneSince = now
        }
        connected = s.loupedeck
        return out
    }

    /// Called about once a second: sends a pending "disconnected" once the rules allow it.
    mutating func tick(at now: Double) -> [Alert] {
        guard let since = goneSince, !connected,
              now - since >= debounce, now >= wakeUntil, now - lastDisconnect >= minInterval else { return [] }
        goneSince = nil
        shownDisconnect = true
        lastDisconnect = now
        return [.disconnected]
    }

    /// USB devices re-enumerate on wake: hold disconnect alerts for a while.
    mutating func didWake(at now: Double) {
        wakeUntil = now + wakeGrace
    }

    /// The bridge exited: what it last said about the Loupedeck no longer counts. Its shutdown isn't an
    /// unplug, so a pending "disconnected" is dropped (review fix).
    mutating func bridgeStopped() {
        armed = false
        connected = false
        goneSince = nil
    }

    /// A new bridge run: nothing is known about the Loupedeck until it connects again.
    mutating func bridgeRestarted() {
        armed = false
        connected = false
        goneSince = nil
        keysAlerted = false
    }
}

/// When to restart a bridge that stopped by itself: after `delay` seconds, at most `maxRestarts` times in
/// `window` seconds. A clean exit (0) or "already running" (3) is never a crash.
struct RestartPolicy {
    static let alreadyRunning: Int32 = 3   // bridge/__main__.py EXIT_ALREADY_RUNNING
    var delay = 5.0
    var window = 600.0
    var maxRestarts = 3
    private var restarts: [Double] = []

    mutating func shouldRestart(exitCode: Int32, at now: Double) -> Bool {
        if exitCode == 0 || exitCode == RestartPolicy.alreadyRunning { return false }
        restarts = restarts.filter { now - $0 < window }
        guard restarts.count < maxRestarts else { return false }
        restarts.append(now)
        return true
    }
}

/// What the app does when the bridge starts, exits or restarts, or the user quits: the decisions only, so
/// they're testable without AppKit. The app (StatusMenu.swift) carries out the actions.
/// Review fixes: keys are let go after a forced Quit too, status lines from a bridge that's on its way out
/// are ignored, and a restart (automatic or from the menu) can never start a second bridge.
enum SupervisorAction: Equatable {
    case spawn                                   // start the bridge
    case stopBridge                              // SIGTERM, then SIGKILL after 5 s
    case releaseKeys                             // it ended without its own clean-up
    case alert(Alert)
    case scheduleRestart(token: Int, after: Double)
    case terminateApp
    case readyToSwap                             // an update may now replace the app (the bridge has stopped)
}

struct BridgeSupervisor {
    enum State: Equatable { case idle, running, waitingToRestart, stopped, updating, quitting }
    private(set) var state: State = .idle
    private var restarts = RestartPolicy()
    private var token = 0                        // only the newest scheduled restart may fire

    /// Status lines count only while the bridge runs, not once it's exiting, stopped or quitting.
    var acceptsStatus: Bool { state == .running }
    /// The menu shows "stopped" (and offers Restart) in these states.
    var isStopped: Bool { state == .stopped || state == .waitingToRestart }

    mutating func start() -> [SupervisorAction] {
        state = .running
        return [.spawn]
    }

    mutating func spawnFailed() -> [SupervisorAction] {
        state = .stopped
        return [.alert(.bridgeStopped(willRestart: false))]
    }

    mutating func exited(code: Int32, at now: Double) -> [SupervisorAction] {
        let hard = code != 0 && code != RestartPolicy.alreadyRunning   // no clean-up of its own
        if state == .quitting {
            return (hard ? [.releaseKeys] : []) + [.terminateApp]
        }
        if state == .updating {
            return (hard ? [.releaseKeys] : []) + [.readyToSwap]
        }
        if code == RestartPolicy.alreadyRunning {
            state = .stopped
            return [.terminateApp]                 // another LoupedeckBridge is in the menu bar
        }
        var out: [SupervisorAction] = hard ? [.releaseKeys] : []
        let restart = restarts.shouldRestart(exitCode: code, at: now)
        if hard { out.append(.alert(.bridgeStopped(willRestart: restart))) }
        if restart {
            token += 1
            state = .waitingToRestart
            out.append(.scheduleRestart(token: token, after: restarts.delay))
        } else {
            state = .stopped                       // exit 0: a deliberate stop; or the budget is used up
        }
        return out
    }

    mutating func restartTimerFired(token fired: Int) -> [SupervisorAction] {
        guard state == .waitingToRestart, fired == token else { return [] }
        state = .running
        return [.spawn]
    }

    /// "Restart bridge" in the menu: only when it's stopped (a stale menu click does nothing).
    mutating func manualRestart() -> [SupervisorAction] {
        guard isStopped else { return [] }
        token += 1                                 // cancels a pending automatic restart
        restarts = RestartPolicy()                 // a fresh budget after a deliberate restart
        state = .running
        return [.spawn]
    }

    /// An update is about to replace the app: stop the bridge like Quit does, but keep the app running so it can
    /// swap itself out (or bring the bridge back if the swap fails). A pending automatic restart is cancelled.
    mutating func stopForUpdate(bridgeRunning: Bool) -> [SupervisorAction] {
        guard state != .updating, state != .quitting else { return [] }
        token += 1
        state = .updating
        return bridgeRunning ? [.stopBridge] : [.readyToSwap]
    }

    /// The update failed after the bridge was stopped: start it again, with a fresh restart budget.
    mutating func updateAbandoned() -> [SupervisorAction] {
        guard state == .updating else { return [] }
        restarts = RestartPolicy()
        state = .running
        return [.spawn]
    }

    mutating func quit(bridgeRunning: Bool) -> [SupervisorAction] {
        guard state != .quitting else { return [] }
        state = .quitting
        return bridgeRunning ? [.stopBridge] : [.terminateApp]
    }
}

/// Which Python to run, and where, from the app's Info.plist (milestone 6):
/// - `LBRuntime = bundled` (releases): the Python and code inside the app
/// - `LBRuntime = repo`, or no `LBRuntime` (dev builds, older builds): `LBRepoPath`'s `.venv` and checkout
struct RuntimePaths: Equatable {
    let python: String
    let workdir: String

    static func resolve(info: [String: Any], bundle: String) -> RuntimePaths? {
        switch info["LBRuntime"] as? String {
        case "bundled":
            let resources = bundle + "/Contents/Resources"
            return RuntimePaths(python: resources + "/python/bin/python3", workdir: resources + "/app")
        case "repo", nil:
            guard let repo = info["LBRepoPath"] as? String, !repo.isEmpty else { return nil }
            return RuntimePaths(python: repo + "/.venv/bin/python", workdir: repo)
        default:
            return nil
        }
    }
}

// ---- updates (milestone 6) ------------------------------------------------------

/// A release version: three numbers, compared numerically ("0.10.0" > "0.9.9"). A leading "v" is allowed.
struct Version: Comparable, CustomStringConvertible {
    let parts: [Int]

    init?(_ text: String) {
        let trimmed = text.hasPrefix("v") ? String(text.dropFirst()) : text
        let pieces = trimmed.split(separator: ".", omittingEmptySubsequences: false)
        guard pieces.count == 3 else { return nil }
        var numbers: [Int] = []
        for piece in pieces {
            guard !piece.isEmpty, piece.allSatisfy(\.isNumber), let n = Int(piece) else { return nil }
            numbers.append(n)
        }
        parts = numbers
    }

    static func < (a: Version, b: Version) -> Bool { a.parts.lexicographicallyPrecedes(b.parts) }
    var description: String { parts.map(String.init).joined(separator: ".") }
}

/// The newest release, from GitHub's "latest release" JSON. Only a full release (not a draft or pre-release)
/// with both `LoupedeckBridge-v<ver>-macos-arm64.zip` and its `.sha256` counts.
struct ReleaseInfo: Equatable {
    let version: Version
    let zipURL: URL
    let sha256URL: URL

    static func assetName(for version: Version) -> String { "LoupedeckBridge-v\(version)-macos-arm64.zip" }

    static func parse(_ data: Data) -> ReleaseInfo? {
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let tag = json["tag_name"] as? String, let version = Version(tag),
              (json["draft"] as? Bool) != true, (json["prerelease"] as? Bool) != true,
              let assets = json["assets"] as? [[String: Any]] else { return nil }
        var urls: [String: URL] = [:]
        for asset in assets {
            if let name = asset["name"] as? String, let link = asset["browser_download_url"] as? String,
               let url = URL(string: link), url.scheme == "https" {
                urls[name] = url
            }
        }
        let zip = assetName(for: version)
        guard let zipURL = urls[zip], let shaURL = urls[zip + ".sha256"] else { return nil }
        return ReleaseInfo(version: version, zipURL: zipURL, sha256URL: shaURL)
    }

    /// For the app's defaults, so a found update survives a relaunch.
    var saved: [String: String] {
        ["version": version.description, "zip": zipURL.absoluteString, "sha256": sha256URL.absoluteString]
    }

    /// A saved release, if it's still newer than the running version (nil once installed, or if unreadable).
    static func restore(_ saved: Any?, newerThan current: Version) -> ReleaseInfo? {
        guard let fields = saved as? [String: String], let version = fields["version"].flatMap(Version.init),
              version > current,
              let zipURL = fields["zip"].flatMap(URL.init(string:)), zipURL.scheme == "https",
              let shaURL = fields["sha256"].flatMap(URL.init(string:)), shaURL.scheme == "https" else { return nil }
        return ReleaseInfo(version: version, zipURL: zipURL, sha256URL: shaURL)
    }
}

/// When to ask GitHub: never for dev builds or when turned off; not in the first 30 s after launch; then at
/// most once a day.
struct UpdateSchedule {
    var interval: TimeInterval = 86_400
    var firstDelay: TimeInterval = 30

    func shouldCheck(now: Date, lastCheck: Date?, enabled: Bool, isDev: Bool, sinceLaunch: TimeInterval) -> Bool {
        guard !isDev, enabled, sinceLaunch >= firstDelay else { return false }
        guard let last = lastCheck else { return true }
        return now.timeIntervalSince(last) >= interval
    }
}

/// One alert per newer version (the menu item stays as long as it's available). `lastAnnounced` is saved in
/// the app's defaults, so a relaunch doesn't alert again for the same version.
struct UpdateNotice {
    private(set) var lastAnnounced: Version?

    init(lastAnnounced: Version? = nil) {
        self.lastAnnounced = lastAnnounced
    }

    mutating func announce(_ version: Version, current: Version) -> Bool {
        guard version > current else { return false }
        if let last = lastAnnounced, version <= last { return false }
        lastAnnounced = version
        return true
    }
}

/// The install steps, in order. Everything is checked (verify) before anything is stopped or moved.
enum InstallStep: Equatable {
    case download, unzip, verify, stopBridge, moveOldToTrash, moveNewIntoPlace, launchNew
}

let installOrder: [InstallStep] = [.download, .unzip, .verify, .stopBridge, .moveOldToTrash, .moveNewIntoPlace,
                                   .launchNew]

let releaseBundleID = "io.github.megamattmiller.loupedeckbridge"

/// The first reason not to install a downloaded app, in plain words, or nil if it may be installed.
func installProblem(bundleID: String, version: Version?, current: Version, signatureOK: Bool, appCount: Int,
                    allowOlder: Bool) -> String? {
    if appCount != 1 { return "the download should hold exactly one app (it holds \(appCount))" }
    if bundleID != releaseBundleID { return "it isn't the LoupedeckBridge release (\(bundleID))" }
    if !signatureOK { return "it isn't signed with your LoupedeckBridge release key" }
    guard let version = version else { return "it has no readable version" }
    if version <= current && !allowOlder { return "it isn't newer than the installed v\(current)" }
    return nil
}

/// Why unzipping a download failed, in plain words, from ditto's error output (e.g. a full disk).
func unzipProblem(_ errors: String) -> String {
    let detail = errors.split(whereSeparator: \.isNewline)
        .map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }.joined(separator: " ")
    return detail.isEmpty ? "it isn't a valid zip" : "couldn't unzip it (\(detail))"
}
