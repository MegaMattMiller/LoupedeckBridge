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
}

struct BridgeSupervisor {
    enum State: Equatable { case idle, running, waitingToRestart, stopped, quitting }
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

    mutating func quit(bridgeRunning: Bool) -> [SupervisorAction] {
        guard state != .quitting else { return [] }
        state = .quitting
        return bridgeRunning ? [.stopBridge] : [.terminateApp]
    }
}
