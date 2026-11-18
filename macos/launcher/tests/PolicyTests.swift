// Checks for Policies.swift, compiled (with -parse-as-library) and run by tests/test_launcher_policies.py.
// Prints "ok <name>" or "FAIL <name>: <why>" per check, and exits non-zero on any failure.
// Time is a plain Double (seconds), so every timing rule is exact and instant to test.

import CryptoKit
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

@discardableResult
func shell(_ tool: String, _ args: String...) -> Int32 {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: tool)
    p.arguments = args
    p.standardOutput = FileHandle.nullDevice
    p.standardError = FileHandle.nullDevice
    guard (try? p.run()) != nil else { return -1 }
    p.waitUntilExit()
    return p.terminationStatus
}

/// The SHA-256 of the app's signing certificate as `codesign -d --extract-certificates` writes it (DER).
func leafSHA256ByCodesign(_ app: URL) -> String? {
    let dir = FileManager.default.temporaryDirectory.appendingPathComponent("lb-cert-\(getpid())")
    try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: dir) }
    shell("/usr/bin/codesign", "-d", "--extract-certificates=" + dir.appendingPathComponent("c").path, app.path)
    guard let der = try? Data(contentsOf: dir.appendingPathComponent("c0")) else { return nil }
    return SHA256.hash(data: der).map { String(format: "%02x", $0) }.joined()
}

/// A minimal unsigned app bundle (a copy of /usr/bin/true as its executable) in a fresh temp folder.
func tinyApp(bundleID: String) -> URL? {
    let fm = FileManager.default
    let app = fm.temporaryDirectory.appendingPathComponent("lb-app-\(getpid())/Tiny.app")
    try? fm.removeItem(at: app.deletingLastPathComponent())
    do {
        try fm.createDirectory(at: app.appendingPathComponent("Contents/MacOS"), withIntermediateDirectories: true)
        try fm.createDirectory(at: app.appendingPathComponent("Contents/Resources"), withIntermediateDirectories: true)
        try fm.copyItem(at: URL(fileURLWithPath: "/usr/bin/true"), to: app.appendingPathComponent("Contents/MacOS/Tiny"))
        let plist: [String: Any] = ["CFBundleIdentifier": bundleID, "CFBundleExecutable": "Tiny",
                                    "CFBundlePackageType": "APPL"]
        try PropertyListSerialization.data(fromPropertyList: plist, format: .xml, options: 0)
            .write(to: app.appendingPathComponent("Contents/Info.plist"))
        return app
    } catch {
        return nil
    }
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
        check("parse_ignores_new_fields") {
            // Milestone 7: the bridge also reports "loupedeck_busy" (Windows); the Mac app must still read the line.
            let line = #"{"loupedeck": false, "lightroom": true, "keys": "allowed", "five_mode": "ratings", "settings_url": null, "loupedeck_busy": true}"#
            return BridgeStatus.parse(line)?.lightroom == true ? nil : "refused a line with a new field"
        }
        check("bridge_exit_drops_pending_disconnect") {
            // Review: the bridge reports "loupedeck: false" while shutting down; a crash then raised a
            // false "disconnected" alert, and "back" after the restart.
            var p = AlertPolicy()
            _ = p.status(line(true), at: 0)
            _ = p.status(line(false), at: 10)        // the bridge's shutdown line
            p.bridgeStopped()
            var out: [Alert] = []
            var t = 10.0
            while t <= 20 { out += p.tick(at: t); t += 1 }
            p.bridgeRestarted()
            out += p.status(line(true), at: 16)
            return out.isEmpty ? nil : "\(out)"
        }

        check("quit_after_forced_kill_releases_keys") {
            // Review: Quit → SIGKILL after 5 s (exit 137) exited without letting go of held keys.
            var s = BridgeSupervisor()
            _ = s.start()
            if s.quit(bridgeRunning: true) != [.stopBridge] { return "quit didn't stop the bridge" }
            let out = s.exited(code: 137, at: 1)
            return out == [.releaseKeys, .terminateApp] ? nil : "\(out)"
        }

        check("quit_after_clean_stop_just_exits") {
            var s = BridgeSupervisor()
            _ = s.start()
            _ = s.quit(bridgeRunning: true)
            let out = s.exited(code: 0, at: 1)
            return out == [.terminateApp] ? nil : "\(out)"
        }

        check("crash_releases_alerts_and_schedules_once") {
            var s = BridgeSupervisor()
            if s.start() != [.spawn] { return "start" }
            let out = s.exited(code: 1, at: 0)
            return out == [.releaseKeys, .alert(.bridgeStopped(willRestart: true)), .scheduleRestart(token: 1, after: 5)]
                ? nil : "\(out)"
        }

        check("manual_restart_during_wait_spawns_once") {
            // Review: "Restart bridge" during the 5 s wait started a second bridge, and the app quit.
            var s = BridgeSupervisor()
            _ = s.start()
            _ = s.exited(code: 1, at: 0)
            if s.manualRestart() != [.spawn] { return "manual restart didn't spawn" }
            let late = s.restartTimerFired(token: 1)
            return late.isEmpty ? nil : "the stale timer also spawned: \(late)"
        }

        check("stale_restart_click_does_nothing") {
            var s = BridgeSupervisor()
            _ = s.start()
            _ = s.exited(code: 1, at: 0)
            if s.restartTimerFired(token: 1) != [.spawn] { return "the timer didn't restart it" }
            let click = s.manualRestart()                // the menu was opened before the restart
            return click.isEmpty ? nil : "a second bridge: \(click)"
        }

        check("status_ignored_once_the_bridge_is_gone") {
            var s = BridgeSupervisor()
            _ = s.start()
            if !s.acceptsStatus { return "a running bridge's status was ignored" }
            _ = s.exited(code: 1, at: 0)
            if s.acceptsStatus { return "accepted status from a bridge that has exited" }
            _ = s.quit(bridgeRunning: false)
            return s.acceptsStatus ? "accepted status while quitting" : nil
        }

        check("already_running_quits_the_app") {
            var s = BridgeSupervisor()
            _ = s.start()
            let out = s.exited(code: 3, at: 0)
            return out == [.terminateApp] ? nil : "\(out)"
        }

        check("runtime_paths_bundled_and_repo") {
            let bundled = RuntimePaths.resolve(info: ["LBRuntime": "bundled"], bundle: "/Applications/LoupedeckBridge.app")
            if bundled?.python != "/Applications/LoupedeckBridge.app/Contents/Resources/python/bin/python3"
                || bundled?.workdir != "/Applications/LoupedeckBridge.app/Contents/Resources/app" {
                return "bundled: \(String(describing: bundled))"
            }
            for info: [String: Any] in [["LBRuntime": "repo", "LBRepoPath": "/r"], ["LBRepoPath": "/r"]] {
                let repo = RuntimePaths.resolve(info: info, bundle: "/x.app")
                if repo?.python != "/r/.venv/bin/python" || repo?.workdir != "/r" { return "repo: \(String(describing: repo))" }
            }
            if RuntimePaths.resolve(info: ["LBRuntime": "weird"], bundle: "/x.app") != nil { return "accepted a weird runtime" }
            if RuntimePaths.resolve(info: ["LBRuntime": "repo"], bundle: "/x.app") != nil { return "repo without a path" }
            return nil
        }

        // ---- milestone 6: updates --------------------------------------------------
        check("version_compare") {
            guard let a = Version("0.10.0"), let b = Version("0.9.9"), let c = Version("v0.5.1"), let d = Version("0.5.0")
            else { return "didn't parse" }
            if !(a > b) || !(c > d) || !(d == Version("v0.5.0")!) { return "order" }
            for bad in ["0.5", "x.y.z", "", "1.2.3.4", "1.-2.3"] where Version(bad) != nil { return "accepted \(bad)" }
            return d.description == "0.5.0" ? nil : "description \(d)"
        }

        let sampleRelease = """
        {"tag_name": "v0.6.0", "draft": false, "prerelease": false, "assets": [
          {"name": "LoupedeckBridge-v0.6.0-macos-arm64.zip",
           "browser_download_url": "https://github.com/o/r/releases/download/v0.6.0/LoupedeckBridge-v0.6.0-macos-arm64.zip"},
          {"name": "LoupedeckBridge-v0.6.0-macos-arm64.zip.sha256",
           "browser_download_url": "https://github.com/o/r/releases/download/v0.6.0/LoupedeckBridge-v0.6.0-macos-arm64.zip.sha256"}]}
        """

        check("release_parse_accepts_a_real_shape") {
            guard let r = ReleaseInfo.parse(Data(sampleRelease.utf8)) else { return "not parsed" }
            if r.version != Version("0.6.0") { return "version \(r.version)" }
            if !r.zipURL.absoluteString.hasSuffix("LoupedeckBridge-v0.6.0-macos-arm64.zip") { return "zip \(r.zipURL)" }
            return r.sha256URL.absoluteString.hasSuffix(".zip.sha256") ? nil : "sha \(r.sha256URL)"
        }

        check("release_parse_rejects_garbage") {
            let noSha = sampleRelease.replacingOccurrences(of: ".zip.sha256\"", with: ".zip.txt\"")
            let bad = ["", "{}", "{\"message\":\"API rate limit exceeded\"}", "not json", noSha,
                       sampleRelease.replacingOccurrences(of: "\"draft\": false", with: "\"draft\": true"),
                       sampleRelease.replacingOccurrences(of: "\"prerelease\": false", with: "\"prerelease\": true"),
                       sampleRelease.replacingOccurrences(of: "v0.6.0\", \"draft", with: "latest\", \"draft")]
            for (i, text) in bad.enumerated() where ReleaseInfo.parse(Data(text.utf8)) != nil { return "accepted case \(i)" }
            return nil
        }

        check("check_schedule") {
            let s = UpdateSchedule()
            let now = Date(timeIntervalSince1970: 1_000_000)
            func check(_ last: Date?, enabled: Bool = true, dev: Bool = false, since: TimeInterval = 60) -> Bool {
                s.shouldCheck(now: now, lastCheck: last, enabled: enabled, isDev: dev, sinceLaunch: since)
            }
            if check(nil, dev: true) || check(nil, enabled: false) || check(nil, since: 10) { return "checked when it shouldn't" }
            if !check(nil) { return "no first check" }
            if !check(now.addingTimeInterval(-86_400)) { return "no check after 24 h" }
            return check(now.addingTimeInterval(-82_800)) ? "checked after 23 h" : nil
        }

        check("notice_once_per_version") {
            var n = UpdateNotice()
            let current = Version("0.5.0")!
            let answers = ["0.6.0", "0.6.0", "0.6.1", "0.5.0"].map { n.announce(Version($0)!, current: current) }
            return answers == [true, false, true, false] ? nil : "\(answers)"
        }

        // Milestone 6 review: a found update and its one alert must survive a relaunch (start at login).
        check("notice_survives_a_relaunch") {
            var before = UpdateNotice()
            let current = Version("0.5.0")!
            guard before.announce(Version("0.6.0")!, current: current) else { return "no first alert" }
            var after = UpdateNotice(lastAnnounced: before.lastAnnounced)
            if after.announce(Version("0.6.0")!, current: current) { return "alerted again after a relaunch" }
            return after.announce(Version("0.6.1")!, current: current) ? nil : "no alert for a newer version"
        }

        check("found_update_survives_a_relaunch") {
            guard let found = ReleaseInfo.parse(Data(sampleRelease.utf8)) else { return "sample didn't parse" }
            if ReleaseInfo.restore(found.saved, newerThan: Version("0.5.0")!) != found { return "not restored" }
            if ReleaseInfo.restore(found.saved, newerThan: Version("0.6.0")!) != nil { return "restored once installed" }
            var http = found.saved
            http["zip"] = "http://example.com/x.zip"
            for bad: Any? in [nil, ["version": "x"], http, "garbage"]
                where ReleaseInfo.restore(bad, newerThan: Version("0.5.0")!) != nil { return "restored \(String(describing: bad))" }
            return nil
        }

        check("install_plan_order") {
            let order = installOrder
            guard let verify = order.firstIndex(of: .verify) else { return "no verify step" }
            for later: InstallStep in [.stopBridge, .moveOldToTrash, .moveNewIntoPlace, .launchNew] {
                guard let i = order.firstIndex(of: later), i > verify else { return "\(later) isn't after verify" }
            }
            return order.first == .download ? nil : "\(order)"
        }

        let releaseID = "io.github.megamattmiller.loupedeckbridge"
        let current = Version("0.5.0")!
        let newer = Version("0.5.1")

        check("install_plan_refuses_wrong_bundle") {
            installProblem(bundleID: releaseID + ".dev", version: newer, current: current, signatureOK: true,
                           appCount: 1, allowOlder: false) == nil ? "accepted a dev build" : nil
        }
        check("install_plan_refuses_bad_signature") {
            let p = installProblem(bundleID: releaseID, version: newer, current: current, signatureOK: false,
                                   appCount: 1, allowOlder: false)
            return p?.contains("sign") == true ? nil : "\(String(describing: p))"
        }
        check("install_plan_refuses_two_apps") {
            installProblem(bundleID: releaseID, version: newer, current: current, signatureOK: true,
                           appCount: 2, allowOlder: false) == nil ? "accepted two apps" : nil
        }
        check("install_plan_refuses_not_newer") {
            let same = installProblem(bundleID: releaseID, version: current, current: current, signatureOK: true,
                                      appCount: 1, allowOlder: false)
            let older = installProblem(bundleID: releaseID, version: Version("0.4.0"), current: current, signatureOK: true,
                                       appCount: 1, allowOlder: false)
            let allowed = installProblem(bundleID: releaseID, version: Version("0.4.0"), current: current,
                                         signatureOK: true, appCount: 1, allowOlder: true)
            return same != nil && older != nil && allowed == nil ? nil : "same \(String(describing: same)), older \(String(describing: older)), allowed \(String(describing: allowed))"
        }
        check("install_plan_accepts_valid") {
            let p = installProblem(bundleID: releaseID, version: newer, current: current, signatureOK: true,
                                   appCount: 1, allowOlder: false)
            return p == nil ? nil : p
        }

        // ---- v0.5.1: downloads are capped and hashed as they arrive; unzip errors say why ----
        check("download_is_capped_and_hashed") {
            let dir = FileManager.default.temporaryDirectory.appendingPathComponent("lb-download-\(getpid())")
            try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            defer { try? FileManager.default.removeItem(at: dir) }
            let source = dir.appendingPathComponent("release.zip")
            let body = Data((0..<3_000_000).map { UInt8(truncatingIfNeeded: $0 &* 31) })
            guard (try? body.write(to: source)) != nil else { return "couldn't write the source" }
            let expected = SHA256.hash(data: body).map { String(format: "%02x", $0) }.joined()
            do {
                let done = try Download.fetch(source, to: dir.appendingPathComponent("copy"), limit: 10_000_000,
                                              userAgent: "test")
                if done.bytes != 3_000_000 || done.sha256 != expected { return "bytes \(done.bytes), sha \(done.sha256)" }
                if (try? Data(contentsOf: done.file)) != body { return "the file differs" }
            } catch {
                return "fetch failed: \(error)"
            }
            do {
                _ = try Download.fetch(source, to: dir.appendingPathComponent("capped"), limit: 1_000_000, userAgent: "test")
                return "a download over the limit was accepted"
            } catch let failure as Download.Failure {
                return failure.reason.contains("bigger than") ? nil : failure.reason
            } catch {
                return "\(error)"
            }
        }

        check("unzip_problem_says_why") {
            let full = unzipProblem("ditto: /tmp/x/LoupedeckBridge.app: No space left on device\n")
            if !full.contains("No space left on device") { return full }
            return unzipProblem("") == "it isn't a valid zip" ? nil : unzipProblem("")
        }

        // ---- the updater stops the bridge without quitting (Task 4) ----------------
        check("update_stops_the_bridge_without_quitting") {
            var s = BridgeSupervisor()
            _ = s.start()
            let stop = s.stopForUpdate(bridgeRunning: true)
            if stop != [.stopBridge] { return "stop: \(stop)" }
            if s.acceptsStatus || s.isStopped { return "the menu would show it as running or stopped" }
            let exited = s.exited(code: 0, at: 1)
            if exited != [.readyToSwap] { return "exited: \(exited)" }
            return s.state == .updating ? nil : "state \(s.state)"
        }
        check("update_after_a_forced_stop_releases_keys") {
            var s = BridgeSupervisor()
            _ = s.start()
            _ = s.stopForUpdate(bridgeRunning: true)
            let exited = s.exited(code: -9, at: 1)
            return exited == [.releaseKeys, .readyToSwap] ? nil : "\(exited)"      // and no "stopped" alert
        }
        check("update_when_stopped_swaps_at_once") {
            var s = BridgeSupervisor()
            _ = s.start()
            _ = s.spawnFailed()
            let stop = s.stopForUpdate(bridgeRunning: false)
            return stop == [.readyToSwap] ? nil : "\(stop)"
        }
        check("update_cancels_a_pending_restart") {
            var s = BridgeSupervisor()
            _ = s.start()
            let crash = s.exited(code: 1, at: 0)
            guard let token = crash.compactMap({ action -> Int? in
                if case .scheduleRestart(let t, _) = action { return t }
                return nil
            }).first else { return "no restart scheduled: \(crash)" }
            _ = s.stopForUpdate(bridgeRunning: false)
            let fired = s.restartTimerFired(token: token)
            return fired.isEmpty ? nil : "restarted mid-update: \(fired)"
        }
        check("failed_update_restarts_the_bridge") {
            var s = BridgeSupervisor()
            _ = s.start()
            _ = s.stopForUpdate(bridgeRunning: true)
            _ = s.exited(code: 0, at: 1)
            let back = s.updateAbandoned()
            if back != [.spawn] || s.state != .running { return "\(back), \(s.state)" }
            return s.updateAbandoned().isEmpty ? nil : "spawned twice"
        }
        check("second_update_request_is_ignored") {
            var s = BridgeSupervisor()
            _ = s.start()
            _ = s.stopForUpdate(bridgeRunning: true)
            return s.stopForUpdate(bridgeRunning: true).isEmpty ? nil : "stopped twice"
        }
        check("quit_during_an_update_just_quits") {
            var s = BridgeSupervisor()
            _ = s.start()
            _ = s.stopForUpdate(bridgeRunning: true)
            _ = s.quit(bridgeRunning: true)                 // the bridge is still on its way out
            let exited = s.exited(code: 0, at: 1)
            return exited == [.terminateApp] ? nil : "\(exited)"
        }

        // ---- the signature check (Task 4) ------------------------------------------
        // Calculator stands in for a release: really signed, and codesign itself says which certificate signed it
        // (the same way tools/install.sh reads it), so the app's check and the installer's are compared too.
        let calculator = URL(fileURLWithPath: "/System/Applications/Calculator.app")
        let calculatorLeaf = leafSHA256ByCodesign(calculator)
        check("signature_accepts_the_pinned_certificate") {
            guard let pin = calculatorLeaf else { return "codesign gave no certificate" }
            return Signature.problem(app: calculator, identifier: "com.apple.calculator", pinnedSHA256: pin)
        }
        check("signature_refuses_another_certificate") {
            let p = Signature.problem(app: calculator, identifier: "com.apple.calculator",
                                      pinnedSHA256: String(repeating: "0", count: 64))
            return p?.contains("release key") == true ? nil : "\(String(describing: p))"
        }
        check("signature_refuses_another_identifier") {
            guard let pin = calculatorLeaf else { return "codesign gave no certificate" }
            return Signature.problem(app: calculator, identifier: releaseBundleID, pinnedSHA256: pin) == nil
                ? "accepted Calculator as LoupedeckBridge" : nil
        }
        check("signature_needs_a_pinned_key") {
            let p = Signature.problem(app: calculator, identifier: "com.apple.calculator", pinnedSHA256: "")
            return p?.contains("pinned") == true ? nil : "\(String(describing: p))"
        }
        check("signature_refuses_unsigned_ad_hoc_and_changed_apps") {
            // An app with the release bundle id: unsigned; then signed ad hoc (valid, but no certificate);
            // then changed after signing. None may pass, whatever the pinned value.
            guard let app = tinyApp(bundleID: releaseBundleID) else { return "couldn't make the test app" }
            defer { try? FileManager.default.removeItem(at: app.deletingLastPathComponent()) }
            let pin = calculatorLeaf ?? String(repeating: "0", count: 64)
            if Signature.problem(app: app, identifier: releaseBundleID, pinnedSHA256: pin) == nil { return "unsigned passed" }
            guard shell("/usr/bin/codesign", "--force", "--sign", "-", app.path) == 0 else { return "ad hoc signing failed" }
            if Signature.problem(app: app, identifier: releaseBundleID, pinnedSHA256: pin) == nil { return "ad hoc passed" }
            try? Data("changed".utf8).write(to: app.appendingPathComponent("Contents/Resources/extra.txt"))
            return Signature.problem(app: app, identifier: releaseBundleID, pinnedSHA256: pin) == nil ? "changed passed" : nil
        }

        check("status_pipe_reaches_the_app") {
            // Live check, 2026-11-16: the bridge got "Bad file descriptor" writing status to fd 3.
            // A stand-in "python" writes one status line to fd 3; the app must receive it.
            let dir = FileManager.default.temporaryDirectory.appendingPathComponent("lb-pipe-\(getpid())")
            let bin = dir.appendingPathComponent(".venv/bin")
            try? FileManager.default.createDirectory(at: bin, withIntermediateDirectories: true)
            let script = bin.appendingPathComponent("python")
            let body = "#!/bin/sh\necho '{\"loupedeck\": true, \"lightroom\": true, \"keys\": \"allowed\", " +
                "\"five_mode\": \"ratings\", \"settings_url\": null}' >&3 || exit 9\n"
            try? body.write(to: script, atomically: true, encoding: .utf8)
            chmod(script.path, 0o755)
            BridgeProcess.logURL = dir.appendingPathComponent("bridge.log")
            var received: BridgeStatus?
            var exitCode: Int32?
            let process = BridgeProcess(python: script.path, workdir: dir.path, arguments: [])
            process.onStatus = { received = $0 }
            process.onExit = { exitCode = $0 }
            guard process.start() else { return "couldn't start the stand-in" }
            let deadline = Date().addingTimeInterval(5)
            while (received == nil || exitCode == nil) && Date() < deadline {
                RunLoop.main.run(until: Date().addingTimeInterval(0.05))
            }
            try? FileManager.default.removeItem(at: dir)
            if received?.loupedeck != true { return "no status arrived (stand-in exit code \(String(describing: exitCode)))" }
            return exitCode == 0 ? nil : "stand-in exit code \(String(describing: exitCode))"
        }

        check("bridge_python_runs_only_its_own_code") {
            // A signed release must not change its own bundle: Python writing __pycache__ there would break the
            // signature (-B). And it must run only its own code: -E ignores PYTHON* variables, and -s the user's
            // ~/.local site-packages, where any program could drop a .pth file (milestone 6 review).
            // The stand-in "python" records its arguments.
            let dir = FileManager.default.temporaryDirectory.appendingPathComponent("lb-args-\(getpid())")
            try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            defer { try? FileManager.default.removeItem(at: dir) }
            let script = dir.appendingPathComponent("python3")
            let record = dir.appendingPathComponent("args")
            try? "#!/bin/sh\necho \"$@\" > '\(record.path)'\n".write(to: script, atomically: true, encoding: .utf8)
            chmod(script.path, 0o755)
            BridgeProcess.logURL = dir.appendingPathComponent("bridge.log")
            var exitCode: Int32?
            let process = BridgeProcess(python: script.path, workdir: dir.path, arguments: ["--debug"])
            process.onExit = { exitCode = $0 }
            guard process.start() else { return "couldn't start the stand-in" }
            let deadline = Date().addingTimeInterval(5)
            while exitCode == nil && Date() < deadline { RunLoop.main.run(until: Date().addingTimeInterval(0.05)) }
            let args = (try? String(contentsOf: record, encoding: .utf8))?.trimmingCharacters(in: .whitespacesAndNewlines)
            return args == "-E -s -B -m bridge --debug" ? nil : "python ran with: \(String(describing: args))"
        }
        exit(failures == 0 ? 0 : 1)
    }
}
