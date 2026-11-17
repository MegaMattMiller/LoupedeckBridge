// Checks for Policies.swift, compiled (with -parse-as-library) and run by tests/test_launcher_policies.py.
// Prints "ok <name>" or "FAIL <name>: <why>" per check, and exits non-zero on any failure.
// Time is a plain Double (seconds), so every timing rule is exact and instant to test.

import Foundation

var failures = 0

func check(_ name: String, _ body: () -> String?) {
    if let why = body() {
        print("FAIL \(name): \(why)")
        failures += 1
    } else {
        print("ok \(name)")
    }
}

func line(_ loupedeck: Bool, keys: String = "allowed") -> BridgeStatus {
    BridgeStatus(loupedeck: loupedeck, lightroom: true, keys: keys, five_mode: "ratings", settings_url: nil)
}

/// Feed (time, loupedeck) changes, ticking every second from `from` to `to`; returns every alert.
func run(_ p: inout AlertPolicy, changes: [Double: Bool], from: Double = 0, to: Double) -> [(Double, Alert)] {
    var out: [(Double, Alert)] = []
    var t = from
    while t <= to {
        if let up = changes[t] { out += p.status(line(up), at: t).map { (t, $0) } }
        out += p.tick(at: t).map { (t, $0) }
        t += 1
    }
    return out
}

@main
enum PolicyTests {
    static func main() {
        check("never_connected_never_alerts") {
            var p = AlertPolicy()
            let out = run(&p, changes: [0: false, 30: false], to: 60)
            return out.isEmpty ? nil : "\(out)"
        }

        check("drop_alerts_after_debounce") {
            var p = AlertPolicy()
            _ = p.status(line(true), at: 0)
            _ = p.status(line(false), at: 10)
            if !p.tick(at: 11).isEmpty || !p.tick(at: 12).isEmpty { return "alerted before 3 s" }
            if p.tick(at: 13) != [.disconnected] { return "no alert at 3 s" }
            if p.tick(at: 14) != [] { return "alerted twice" }
            let back = p.status(line(true), at: 20)
            return back == [.back] ? nil : "back: \(back)"
        }

        check("quick_replug_is_silent") {
            var p = AlertPolicy()
            let out = run(&p, changes: [0: true, 10: false, 12: true], to: 30)
            return out.isEmpty ? nil : "\(out)"
        }

        check("wake_grace") {
            var p = AlertPolicy()
            _ = p.status(line(true), at: 0)
            p.didWake(at: 100)
            _ = p.status(line(false), at: 101)
            var t = 101.0
            while t < 115 {
                if !p.tick(at: t).isEmpty { return "alerted at \(t), during the wake grace" }
                t += 1
            }
            let out = p.tick(at: 115)
            return out == [.disconnected] ? nil : "at 115: \(out)"
        }

        check("flapping_is_rate_limited") {
            var p = AlertPolicy()
            var changes: [Double: Bool] = [:]
            var t = 0.0
            var up = false
            while t <= 120 { changes[t] = up; up.toggle(); t += 5 }   // gone at 0, back at 5, gone at 10, …
            _ = p.status(line(true), at: -1)
            let out = run(&p, changes: changes, to: 120)
            let gone = out.filter { $0.1 == .disconnected }.count
            let back = out.filter { $0.1 == .back }.count
            return gone <= 2 && back <= 2 && gone >= 1 ? nil : "\(gone) disconnected, \(back) back: \(out)"
        }

        check("rate_limited_alert_fires_later") {
            var p = AlertPolicy()
            _ = p.status(line(true), at: -1)
            let first = run(&p, changes: [0: false, 5: true, 10: false], to: 62)
            if first.map({ $0.1 }) != [.disconnected, .back] { return "first minute: \(first)" }
            let later = p.tick(at: 63)
            return later == [.disconnected] ? nil : "at 63: \(later)"
        }

        check("keys_missing_once_per_run") {
            var p = AlertPolicy()
            var out: [Alert] = []
            for t in 0..<3 { out += p.status(line(true, keys: "missing"), at: Double(t)) }
            if out != [.keysMissing] { return "first run: \(out)" }
            p.bridgeRestarted()
            let again = p.status(line(true, keys: "missing"), at: 10)
            return again == [.keysMissing] ? nil : "after restart: \(again)"
        }

        check("restart_disarms") {
            var p = AlertPolicy()
            _ = p.status(line(true), at: 0)
            p.bridgeRestarted()
            let out = run(&p, changes: [1: false], from: 1, to: 31)
            return out.isEmpty ? nil : "\(out)"
        }

        check("restart_budget") {
            var r = RestartPolicy()
            let answers = [0.0, 10, 20, 30].map { r.shouldRestart(exitCode: 1, at: $0) }
            if answers != [true, true, true, false] { return "first ten minutes: \(answers)" }
            return r.shouldRestart(exitCode: 1, at: 700) ? nil : "no restart after the window"
        }

        check("already_running_is_not_a_crash") {
            var r = RestartPolicy()
            let clean = r.shouldRestart(exitCode: 0, at: 0)
            let running = r.shouldRestart(exitCode: 3, at: 1)
            return !clean && !running ? nil : "exit 0 → \(clean), exit 3 → \(running)"
        }

        check("parse_rejects_garbage") {
            for bad in ["", "{}", "not json", "{\"loupedeck\": 1}"] where BridgeStatus.parse(bad) != nil {
                return "accepted \(bad)"
            }
            let good = #"{"loupedeck": true, "lightroom": false, "keys": "missing", "five_mode": "keys", "settings_url": "http://127.0.0.1:7690/"}"#
            let want = BridgeStatus(loupedeck: true, lightroom: false, keys: "missing", five_mode: "keys",
                                    settings_url: "http://127.0.0.1:7690/")
            let nullURL = #"{"loupedeck": false, "lightroom": false, "keys": "allowed", "five_mode": "ratings", "settings_url": null}"#
            if BridgeStatus.parse(nullURL)?.settings_url != nil || BridgeStatus.parse(nullURL) == nil { return "null url" }
            return BridgeStatus.parse(good) == want ? nil : "parsed \(String(describing: BridgeStatus.parse(good)))"
        }
        exit(failures == 0 ? 0 : 1)
    }
}
