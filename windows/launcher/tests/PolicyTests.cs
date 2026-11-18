// Checks for the Windows tray app's rules (Policies.cs, BuildInfo.cs), built and run by tests/test_windows_launcher.py.
// Prints "ok <name>" or "FAIL <name>: <why>" per check, and exits non-zero on any failure. Most are ported from
// macos/launcher/tests/PolicyTests.swift with the same names. Time is a plain double (seconds).

using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;

namespace LoupedeckBridge
{
    static class PolicyTests
    {
        static int failures;

        static void Check(string name, Func<string> body)
        {
            string why;
            try { why = body(); }
            catch (Exception e) { why = "threw " + e.GetType().Name + ": " + e.Message; }
            if (why != null)
            {
                Console.WriteLine("FAIL " + name + ": " + why);
                failures++;
            }
            else
            {
                Console.WriteLine("ok " + name);
            }
        }

        static BridgeStatus Line(bool loupedeck, bool busy = false) =>
            new BridgeStatus(loupedeck, lightroom: true, keys: "allowed", fiveMode: "ratings", settingsUrl: null,
                             loupedeckBusy: busy);

        /// Feed (time, loupedeck) changes, ticking every second from `from` to `to`; returns every alert.
        static List<(double, Alert)> Run(AlertPolicy p, Dictionary<double, bool> changes, double to, double from = 0)
        {
            var output = new List<(double, Alert)>();
            for (var t = from; t <= to; t += 1)
            {
                if (changes.TryGetValue(t, out var up)) output.AddRange(p.Status(Line(up), t).Select(a => (t, a)));
                output.AddRange(p.Tick(t).Select(a => (t, a)));
            }
            return output;
        }

        static string Show(IEnumerable<object> items) => "[" + string.Join(", ", items) + "]";
        static bool Same(IEnumerable<SupervisorAction> got, params SupervisorAction[] want) => got.SequenceEqual(want);
        static bool Same(IEnumerable<Alert> got, params Alert[] want) => got.SequenceEqual(want);

        [DllImport("shell32.dll", SetLastError = true)]
        static extern IntPtr CommandLineToArgvW([MarshalAs(UnmanagedType.LPWStr)] string cmdLine, out int numArgs);

        [DllImport("kernel32.dll")]
        static extern IntPtr LocalFree(IntPtr mem);

        /// How Windows itself splits a command line (what a started program sees as its arguments).
        static string[] SplitLikeWindows(string arguments)
        {
            var argv = CommandLineToArgvW("program.exe " + arguments, out var count);
            try
            {
                var parts = new string[count - 1];
                for (var i = 1; i < count; i++) parts[i - 1] = Marshal.PtrToStringUni(Marshal.ReadIntPtr(argv, i * IntPtr.Size));
                return parts;
            }
            finally { LocalFree(argv); }
        }

        static int Main(string[] args)
        {
            // ---- when to alert ----------------------------------------------------------------------------
            Check("never_connected_never_alerts", () =>
            {
                var output = Run(new AlertPolicy(), new Dictionary<double, bool> { [0] = false, [30] = false }, to: 60);
                return output.Count == 0 ? null : Show(output.Cast<object>());
            });

            Check("drop_alerts_after_debounce", () =>
            {
                var p = new AlertPolicy();
                p.Status(Line(true), 0);
                p.Status(Line(false), 10);
                if (p.Tick(11).Count > 0 || p.Tick(12).Count > 0) return "alerted before 3 s";
                if (!Same(p.Tick(13), Alert.Disconnected)) return "no alert at 3 s";
                if (p.Tick(14).Count > 0) return "alerted twice";
                var back = p.Status(Line(true), 20);
                return Same(back, Alert.Back) ? null : "back: " + Show(back);
            });

            Check("quick_replug_is_silent", () =>
            {
                var output = Run(new AlertPolicy(), new Dictionary<double, bool> { [0] = true, [10] = false, [12] = true }, to: 30);
                return output.Count == 0 ? null : Show(output.Cast<object>());
            });

            Check("wake_grace", () =>
            {
                var p = new AlertPolicy();
                p.Status(Line(true), 0);
                p.DidWake(100);
                p.Status(Line(false), 101);
                for (var t = 101.0; t < 115; t += 1)
                    if (p.Tick(t).Count > 0) return $"alerted at {t}, during the wake grace";
                var output = p.Tick(115);
                return Same(output, Alert.Disconnected) ? null : "at 115: " + Show(output);
            });

            Check("flapping_is_rate_limited", () =>
            {
                var p = new AlertPolicy();
                var changes = new Dictionary<double, bool>();
                var up = false;
                for (var t = 0.0; t <= 120; t += 5) { changes[t] = up; up = !up; }   // gone at 0, back at 5, …
                p.Status(Line(true), -1);
                var output = Run(p, changes, to: 120);
                var gone = output.Count(o => o.Item2.Equals(Alert.Disconnected));
                var back = output.Count(o => o.Item2.Equals(Alert.Back));
                return gone <= 2 && back <= 2 && gone >= 1 ? null : $"{gone} disconnected, {back} back";
            });

            Check("rate_limited_alert_fires_later", () =>
            {
                var p = new AlertPolicy();
                p.Status(Line(true), -1);
                var first = Run(p, new Dictionary<double, bool> { [0] = false, [5] = true, [10] = false }, to: 62);
                if (!first.Select(o => o.Item2).SequenceEqual(new[] { Alert.Disconnected, Alert.Back }))
                    return "first minute: " + Show(first.Cast<object>());
                var later = p.Tick(63);
                return Same(later, Alert.Disconnected) ? null : "at 63: " + Show(later);
            });

            Check("restart_disarms", () =>
            {
                var p = new AlertPolicy();
                p.Status(Line(true), 0);
                p.BridgeRestarted();
                var output = Run(p, new Dictionary<double, bool> { [1] = false }, to: 31, from: 1);
                return output.Count == 0 ? null : Show(output.Cast<object>());
            });

            Check("bridge_exit_drops_pending_disconnect", () =>
            {
                var p = new AlertPolicy();
                p.Status(Line(true), 0);
                p.Status(Line(false), 10);           // the bridge's shutdown line
                p.BridgeStopped();
                var output = new List<Alert>();
                for (var t = 10.0; t <= 20; t += 1) output.AddRange(p.Tick(t));
                p.BridgeRestarted();
                output.AddRange(p.Status(Line(true), 16));
                return output.Count == 0 ? null : Show(output);
            });

            // ---- when to restart ----------------------------------------------------------------------------
            Check("restart_budget", () =>
            {
                var r = new RestartPolicy();
                var answers = new[] { 0.0, 10, 20, 30 }.Select(t => r.ShouldRestart(1, t)).ToArray();
                if (!answers.SequenceEqual(new[] { true, true, true, false })) return "first ten minutes: " + string.Join(",", answers);
                return r.ShouldRestart(1, 700) ? null : "no restart after the window";
            });

            Check("already_running_is_not_a_crash", () =>
            {
                var r = new RestartPolicy();
                var clean = r.ShouldRestart(0, 0);
                var running = r.ShouldRestart(3, 1);
                return !clean && !running ? null : $"exit 0 → {clean}, exit 3 → {running}";
            });

            // ---- status lines -------------------------------------------------------------------------------
            Check("parse_rejects_garbage", () =>
            {
                foreach (var bad in new[] { "", "{}", "not json", "{\"loupedeck\": 1}", "[1, 2]", "null",
                                            "{\"loupedeck\": true, \"lightroom\": false, \"keys\": 3, \"five_mode\": \"keys\"}" })
                    if (BridgeStatus.Parse(bad) != null) return "accepted " + bad;
                var good = "{\"loupedeck\": true, \"lightroom\": false, \"keys\": \"allowed\", \"five_mode\": \"keys\", \"settings_url\": \"http://127.0.0.1:7690/\"}";
                var want = new BridgeStatus(true, false, "allowed", "keys", "http://127.0.0.1:7690/", false);
                var nullUrl = "{\"loupedeck\": false, \"lightroom\": false, \"keys\": \"allowed\", \"five_mode\": \"ratings\", \"settings_url\": null}";
                var parsedNull = BridgeStatus.Parse(nullUrl);
                if (parsedNull == null || parsedNull.SettingsUrl != null) return "null url";
                var parsed = BridgeStatus.Parse(good);
                return want.Equals(parsed) ? null : "parsed " + parsed;
            });

            Check("parse_reads_busy", () =>
            {
                var busy = BridgeStatus.Parse("{\"loupedeck\": false, \"lightroom\": true, \"keys\": \"allowed\", \"five_mode\": \"ratings\", \"settings_url\": null, \"loupedeck_busy\": true}");
                if (busy == null || !busy.LoupedeckBusy) return "busy not read";
                var old = BridgeStatus.Parse("{\"loupedeck\": false, \"lightroom\": true, \"keys\": \"allowed\", \"five_mode\": \"ratings\", \"settings_url\": null}");
                return old != null && !old.LoupedeckBusy ? null : "a line without the field";
            });

            // ---- the supervisor -----------------------------------------------------------------------------
            Check("quit_after_forced_kill_releases_keys", () =>
            {
                // Review Focus 2: Quit → killed after 5 s exited without letting go of held keys.
                var s = new BridgeSupervisor();
                s.Start();
                if (!Same(s.Quit(bridgeRunning: true), SupervisorAction.StopBridge)) return "quit didn't stop the bridge";
                var output = s.Exited(-1, 1);                    // Process.Kill's exit code
                return Same(output, SupervisorAction.ReleaseKeys, SupervisorAction.TerminateApp) ? null : Show(output);
            });

            Check("quit_after_clean_stop_just_exits", () =>
            {
                var s = new BridgeSupervisor();
                s.Start();
                s.Quit(bridgeRunning: true);
                var output = s.Exited(0, 1);
                return Same(output, SupervisorAction.TerminateApp) ? null : Show(output);
            });

            Check("crash_releases_alerts_and_schedules_once", () =>
            {
                var s = new BridgeSupervisor();
                if (!Same(s.Start(), SupervisorAction.Spawn)) return "start";
                var output = s.Exited(1, 0);
                return Same(output, SupervisorAction.ReleaseKeys, SupervisorAction.Alert(Alert.Stopped(willRestart: true)),
                            SupervisorAction.ScheduleRestart(1, 5)) ? null : Show(output);
            });

            Check("manual_restart_during_wait_spawns_once", () =>
            {
                var s = new BridgeSupervisor();
                s.Start();
                s.Exited(1, 0);
                if (!Same(s.ManualRestart(), SupervisorAction.Spawn)) return "manual restart didn't spawn";
                var late = s.RestartTimerFired(1);
                return late.Count == 0 ? null : "the stale timer also spawned: " + Show(late);
            });

            Check("stale_restart_click_does_nothing", () =>
            {
                var s = new BridgeSupervisor();
                s.Start();
                s.Exited(1, 0);
                if (!Same(s.RestartTimerFired(1), SupervisorAction.Spawn)) return "the timer didn't restart it";
                var click = s.ManualRestart();
                return click.Count == 0 ? null : "a second bridge: " + Show(click);
            });

            Check("status_ignored_once_the_bridge_is_gone", () =>
            {
                var s = new BridgeSupervisor();
                s.Start();
                if (!s.AcceptsStatus) return "a running bridge's status was ignored";
                s.Exited(1, 0);
                if (s.AcceptsStatus) return "accepted status from a bridge that has exited";
                s.Quit(bridgeRunning: false);
                return s.AcceptsStatus ? "accepted status while quitting" : null;
            });

            Check("already_running_quits_the_app", () =>
            {
                var s = new BridgeSupervisor();
                s.Start();
                var output = s.Exited(3, 0);
                return Same(output, SupervisorAction.TerminateApp) ? null : Show(output);
            });

            Check("update_stops_the_bridge_without_quitting", () =>
            {
                var s = new BridgeSupervisor();
                s.Start();
                var stop = s.StopForUpdate(bridgeRunning: true);
                if (!Same(stop, SupervisorAction.StopBridge)) return "stop: " + Show(stop);
                if (s.AcceptsStatus || s.IsStopped) return "the menu would show it as running or stopped";
                var exited = s.Exited(0, 1);
                if (!Same(exited, SupervisorAction.ReadyToSwap)) return "exited: " + Show(exited);
                return s.State == BridgeSupervisor.States.Updating ? null : "state " + s.State;
            });

            Check("update_after_a_forced_stop_releases_keys", () =>
            {
                var s = new BridgeSupervisor();
                s.Start();
                s.StopForUpdate(bridgeRunning: true);
                var exited = s.Exited(-1, 1);
                return Same(exited, SupervisorAction.ReleaseKeys, SupervisorAction.ReadyToSwap) ? null : Show(exited);
            });

            Check("update_when_stopped_swaps_at_once", () =>
            {
                var s = new BridgeSupervisor();
                s.Start();
                s.SpawnFailed();
                var stop = s.StopForUpdate(bridgeRunning: false);
                return Same(stop, SupervisorAction.ReadyToSwap) ? null : Show(stop);
            });

            Check("update_cancels_a_pending_restart", () =>
            {
                var s = new BridgeSupervisor();
                s.Start();
                var crash = s.Exited(1, 0);
                var scheduled = crash.FirstOrDefault(a => a.Kind == SupervisorAction.Kinds.ScheduleRestart);
                if (scheduled == null) return "no restart scheduled: " + Show(crash);
                s.StopForUpdate(bridgeRunning: false);
                var fired = s.RestartTimerFired(scheduled.Token);
                return fired.Count == 0 ? null : "restarted mid-update: " + Show(fired);
            });

            Check("failed_update_restarts_the_bridge", () =>
            {
                var s = new BridgeSupervisor();
                s.Start();
                s.StopForUpdate(bridgeRunning: true);
                s.Exited(0, 1);
                var back = s.UpdateAbandoned();
                if (!Same(back, SupervisorAction.Spawn) || s.State != BridgeSupervisor.States.Running) return Show(back) + ", " + s.State;
                return s.UpdateAbandoned().Count == 0 ? null : "spawned twice";
            });

            Check("second_update_request_is_ignored", () =>
            {
                var s = new BridgeSupervisor();
                s.Start();
                s.StopForUpdate(bridgeRunning: true);
                return s.StopForUpdate(bridgeRunning: true).Count == 0 ? null : "stopped twice";
            });

            Check("quit_during_an_update_just_quits", () =>
            {
                var s = new BridgeSupervisor();
                s.Start();
                s.StopForUpdate(bridgeRunning: true);
                s.Quit(bridgeRunning: true);
                var exited = s.Exited(0, 1);
                return Same(exited, SupervisorAction.TerminateApp) ? null : Show(exited);
            });

            // ---- versions -----------------------------------------------------------------------------------
            Check("version_compare", () =>
            {
                var a = Version.Parse("0.10.0"); var b = Version.Parse("0.9.9");
                var c = Version.Parse("v0.5.1"); var d = Version.Parse("0.5.0");
                if (a == null || b == null || c == null || d == null) return "didn't parse";
                if (!(a > b) || !(c > d) || !(d == Version.Parse("v0.5.0")) || d > d || !(d >= d)) return "order";
                foreach (var bad in new[] { "0.5", "x.y.z", "", "1.2.3.4", "1.-2.3", "1.2.3 ", "١.2.3", "99999999999.0.0", null })
                    if (Version.Parse(bad) != null) return "accepted " + bad;
                return d.ToString() == "0.5.0" ? null : "ToString " + d;
            });

            // ---- the build info and the runtime (Windows) ---------------------------------------------------
            Check("runtime_paths_bundled_and_repo", () =>
            {
                var bundled = RuntimePaths.Resolve(BuildInfo.Parse("{\"runtime\": \"bundled\", \"version\": \"0.6.0\"}"),
                                                   @"C:\Users\Zoë Ünal\AppData\Local\Programs\LoupedeckBridge");
                if (bundled?.Python != @"C:\Users\Zoë Ünal\AppData\Local\Programs\LoupedeckBridge\python\python.exe"
                    || bundled.Workdir != @"C:\Users\Zoë Ünal\AppData\Local\Programs\LoupedeckBridge\app")
                    return "bundled: " + bundled;
                var repo = RuntimePaths.Resolve(BuildInfo.Parse("{\"runtime\": \"repo\", \"repo\": \"C:\\\\src\\\\lb\", \"is_dev\": true}"), @"C:\x");
                if (repo?.Python != @"C:\src\lb\.venv\Scripts\python.exe" || repo.Workdir != @"C:\src\lb") return "repo: " + repo;
                if (RuntimePaths.Resolve(BuildInfo.Parse("{\"runtime\": \"weird\"}"), @"C:\x") != null) return "accepted a weird runtime";
                if (RuntimePaths.Resolve(BuildInfo.Parse("{\"runtime\": \"repo\"}"), @"C:\x") != null) return "repo without a path";
                return RuntimePaths.Resolve(null, @"C:\x") == null ? null : "no build info";
            });

            Check("bridge_arguments", () =>
            {
                var argv = BridgeCommand.Arguments(new[] { "--debug" });
                return argv.SequenceEqual(new[] { "-E", "-s", "-B", "-X", "utf8", "-m", "bridge", "--debug" })
                    ? null : string.Join(" ", argv);
            });

            Check("build_info_names", () =>
            {
                var dev = BuildInfo.Parse("{\"runtime\": \"repo\", \"repo\": \"C:\\\\r\", \"version\": \"0.6.0\", \"is_dev\": true, \"signer_sha256\": \"\"}");
                if (dev.Name != "LoupedeckBridge Dev" || dev.MutexName != @"Local\LoupedeckBridge Dev"
                    || dev.QuitEventName != @"Local\LoupedeckBridge Dev.quit") return "dev: " + dev.Name + " " + dev.MutexName;
                var release = BuildInfo.Parse("{\"runtime\": \"bundled\", \"version\": \"0.6.0\", \"is_dev\": false, \"signer_sha256\": \"ab\"}");
                if (release.Name != "LoupedeckBridge" || release.MutexName != @"Local\LoupedeckBridge") return "release: " + release.Name;
                return release.Version?.ToString() == "0.6.0" && release.SignerSha256 == "ab" && !release.IsDev
                    ? null : "fields";
            });

            Check("build_info_rejects_garbage", () =>
            {
                foreach (var bad in new[] { "", "not json", "[]", "null", "{\"runtime\": 3}", "{\"is_dev\": \"yes\"}" })
                    if (BuildInfo.Parse(bad) != null) return "accepted " + bad;
                var noVersion = BuildInfo.Parse("{\"runtime\": \"bundled\", \"version\": \"latest\"}");
                if (noVersion == null || noVersion.Version != null) return "an unreadable version should be null, the rest kept";
                return BuildInfo.Load(@"C:\does\not\exist\LoupedeckBridge.json") == null ? null : "loaded a missing file";
            });

            // ---- the tray icon's tooltip --------------------------------------------------------------------
            Check("problem_text_names_busy", () =>
            {
                var running = BridgeSupervisor.States.Running;
                if (TrayText.Problem(running, false, Line(false, busy: true)) != "the Loupedeck is in use by another program")
                    return "busy: " + TrayText.Problem(running, false, Line(false, busy: true));
                var cases = new (BridgeSupervisor.States, bool, BridgeStatus, string)[]
                {
                    (BridgeSupervisor.States.Updating, false, Line(true), "updating…"),
                    (BridgeSupervisor.States.Stopped, true, Line(true), "the bridge has stopped"),
                    (running, false, null, "starting…"),
                    (running, false, Line(false), "the Loupedeck isn't connected"),
                    (running, false, new BridgeStatus(true, false, "allowed", "ratings", null, false), "Lightroom isn't connected"),
                    (running, false, Line(true), "all good"),
                };
                foreach (var (state, stopped, status, want) in cases)
                    if (TrayText.Problem(state, stopped, status) != want) return $"{want}: got {TrayText.Problem(state, stopped, status)}";
                return null;
            });

            Check("tooltips_fit", () =>
            {
                // NotifyIcon.Text takes at most 63 characters on .NET Framework (longer throws).
                var texts = new[] { "updating…", "the bridge has stopped", "starting…", "the Loupedeck is in use by another program",
                                    "the Loupedeck isn't connected", "Lightroom isn't connected", "all good" };
                foreach (var name in new[] { "LoupedeckBridge", "LoupedeckBridge Dev" })
                    foreach (var text in texts)
                        if (TrayText.Tooltip(name, text).Length > 63) return TrayText.Tooltip(name, text);
                return null;
            });

            Check("command_line_quotes_paths", () =>
            {
                // Review Focus 1: paths with spaces, accents, trailing backslashes and quotes survive the command lines
                // the tray app builds (the bridge's arguments; --finish-update's install folder).
                var cases = new[]
                {
                    new[] { "--finish-update", "1234", @"C:\Users\Zoë Ünal\AppData\Local\Programs\LoupedeckBridge" },
                    new[] { @"C:\path with space\", "plain", "" },
                    new[] { "say \"hi\"", @"back\\slashes\\", "tab\tthere", @"C:\no space\" },
                };
                foreach (var argv in cases)
                {
                    var back = SplitLikeWindows(CommandLine.Join(argv));
                    if (!back.SequenceEqual(argv)) return CommandLine.Join(argv) + " → " + string.Join(" | ", back);
                }
                return null;
            });

            return failures == 0 ? 0 : 1;
        }
    }
}
