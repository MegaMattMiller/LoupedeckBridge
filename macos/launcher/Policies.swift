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
