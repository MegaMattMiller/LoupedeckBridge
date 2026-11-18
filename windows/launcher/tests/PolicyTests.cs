// Checks for the Windows tray app's rules (Policies.cs, BuildInfo.cs), built and run by tests/test_windows_launcher.py.
// Prints "ok <name>" or "FAIL <name>: <why>" per check, and exits non-zero on any failure. Most are ported from
// macos/launcher/tests/PolicyTests.swift with the same names. Time is a plain double (seconds).

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Runtime.InteropServices;

namespace LoupedeckBridge
{
    static class PolicyTests
    {
        static int failures;
        static readonly List<string> scratch = new List<string>();   // removed at the end (final review, minor 12)

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

            // ---- ending the bridge's process tree (live check: a venv's python.exe is a launcher with a child) ----
            // cmd.exe stands in for the launcher, and the ping.exe it starts for the real Python.
            Process StartTree()
            {
                var root = Process.Start(new ProcessStartInfo("cmd.exe", "/c ping -n 30 127.0.0.1 >nul")
                                         { UseShellExecute = false, CreateNoWindow = true });
                for (var i = 0; i < 50 && ProcessTree.Children(root.Id, root.StartTime, IsPing).Count == 0; i++)
                    System.Threading.Thread.Sleep(100);
                return root;
            }
            bool Gone(int pid)
            {
                try { using (var p = Process.GetProcessById(pid)) return p.WaitForExit(5000); }
                catch (ArgumentException) { return true; }
            }
            bool IsPing(string name) => string.Equals(name, "ping.exe", StringComparison.OrdinalIgnoreCase);

            Check("kill_ends_the_bridge_and_its_python", () =>
            {
                var root = StartTree();
                var child = ProcessTree.Children(root.Id, root.StartTime, IsPing).SingleOrDefault();
                if (child == 0) return "no child to test with";
                ProcessTree.Kill(root, IsPing);
                return Gone(root.Id) && Gone(child) ? null : $"still running: root {!Gone(root.Id)}, child {!Gone(child)}";
            });

            Check("kill_leaves_other_children_alone", () =>
            {
                // The bridge may start other programs, e.g. the browser for the settings page: never end those.
                var root = StartTree();
                var child = ProcessTree.Children(root.Id, root.StartTime, IsPing).SingleOrDefault();
                ProcessTree.Kill(root, _ => false);
                var survived = !Gone(child);
                try { Process.GetProcessById(child).Kill(); } catch (Exception) { }
                return Gone(root.Id) && survived ? null : "the other child was ended too (or the root wasn't)";
            });

            Check("orphaned_python_is_ended_after_the_launcher_exits", () =>
            {
                var root = StartTree();
                var start = root.StartTime;
                var child = ProcessTree.Children(root.Id, start, IsPing).SingleOrDefault();
                root.Kill();                                    // only the launcher: its child is orphaned
                root.WaitForExit(5000);
                ProcessTree.EndOrphans(root.Id, start, IsPing);
                return Gone(child) ? null : "the orphan is still running";
            });

            // ---- the signature (fixtures made by tests/test_windows_launcher.py with openssl and
            //      tools/sign_windows_zip.sh: content.bin signed with throwaway identity A, other.p7s with B) ------
            var fixtures = args.Length > 0 ? args[0] : null;
            byte[] Fixture(string name) => System.IO.File.ReadAllBytes(System.IO.Path.Combine(fixtures, name));
            string PinnedA() => System.IO.File.ReadAllText(System.IO.Path.Combine(fixtures, "a.sha256")).Trim();

            Check("signature_accepts_the_pinned_certificate", () =>
            {
                if (fixtures == null) return "no fixtures folder given";
                var why = Signature.Problem(Fixture("content.bin"), Fixture("content.bin.p7s"), PinnedA());
                if (why != null) return why;
                return Signature.Problem(Fixture("content.bin"), Fixture("content.bin.p7s"), PinnedA().ToUpperInvariant());
            });

            Check("signature_refuses_another_certificate", () =>
            {
                // Review Focus 4: a release signed with someone else's key.
                if (fixtures == null) return "no fixtures folder given";
                var why = Signature.Problem(Fixture("content.bin"), Fixture("other.p7s"), PinnedA());
                return why == "it's signed with another key" ? null : "got: " + why;
            });

            Check("signature_refuses_a_changed_byte", () =>
            {
                if (fixtures == null) return "no fixtures folder given";
                var changed = Fixture("content.bin");
                changed[changed.Length / 2] ^= 1;
                var why = Signature.Problem(changed, Fixture("content.bin.p7s"), PinnedA());
                return why == "the signature doesn't match the download" ? null : "got: " + why;
            });

            Check("signature_needs_a_pinned_key", () =>
            {
                if (fixtures == null) return "no fixtures folder given";
                foreach (var pinned in new[] { "", null, "abc", new string('g', 64) })
                {
                    var why = Signature.Problem(Fixture("content.bin"), Fixture("content.bin.p7s"), pinned);
                    if (why != "no release key is pinned in this build") return $"pinned '{pinned}': {why}";
                }
                return null;
            });

            Check("signature_refuses_garbage", () =>
            {
                if (fixtures == null) return "no fixtures folder given";
                foreach (var bad in new[] { new byte[0], new byte[] { 1, 2, 3 }, Fixture("content.bin") })
                {
                    var why = Signature.Problem(Fixture("content.bin"), bad, PinnedA());
                    if (why != "the signature is unreadable") return "got: " + why;
                }
                return null;
            });

            // ---- releases and updates -----------------------------------------------------------------------
            string Asset(string name) =>
                $"{{\"name\": \"{name}\", \"browser_download_url\": \"https://github.com/o/r/releases/download/v0.6.0/{name}\"}}";
            var windowsZip = "LoupedeckBridge-v0.6.0-windows-x64.zip";
            var sampleRelease = "{\"tag_name\": \"v0.6.0\", \"draft\": false, \"prerelease\": false, \"assets\": ["
                + string.Join(", ", Asset("LoupedeckBridge-v0.6.0-macos-arm64.zip"), Asset("LoupedeckBridge-v0.6.0-macos-arm64.zip.sha256"),
                              Asset(windowsZip), Asset(windowsZip + ".sha256"), Asset(windowsZip + ".p7s")) + "]}";

            Check("release_parse_accepts_a_real_shape", () =>
            {
                var r = ReleaseInfo.Parse(sampleRelease);
                if (r == null) return "refused the sample";
                var base_ = "https://github.com/o/r/releases/download/v0.6.0/" + windowsZip;
                if (r.Version.ToString() != "0.6.0" || r.Zip.ToString() != base_ || r.Sha256.ToString() != base_ + ".sha256"
                    || r.Signature.ToString() != base_ + ".p7s") return $"{r.Version} {r.Zip} {r.Sha256} {r.Signature}";
                return ReleaseInfo.AssetName(Version.Parse("1.2.3")) == "LoupedeckBridge-v1.2.3-windows-x64.zip" ? null : "asset name";
            });

            Check("release_parse_rejects_garbage", () =>
            {
                var macOnly = "{\"tag_name\": \"v0.6.0\", \"draft\": false, \"prerelease\": false, \"assets\": ["
                    + Asset("LoupedeckBridge-v0.6.0-macos-arm64.zip") + ", " + Asset("LoupedeckBridge-v0.6.0-macos-arm64.zip.sha256") + "]}";
                var bad = new[]
                {
                    "", "{}", "{\"message\":\"API rate limit exceeded\"}", "not json", macOnly,
                    sampleRelease.Replace(".zip.p7s\"", ".zip.sig\""),
                    sampleRelease.Replace("\"draft\": false", "\"draft\": true"),
                    sampleRelease.Replace("\"prerelease\": false", "\"prerelease\": true"),
                    sampleRelease.Replace("\"v0.6.0\", \"draft", "\"latest\", \"draft"),
                    sampleRelease.Replace("https://github.com/o/r/releases/download/v0.6.0/" + windowsZip + "\"",
                                          "http://github.com/o/r/releases/download/v0.6.0/" + windowsZip + "\""),
                };
                for (var i = 0; i < bad.Length; i++) if (ReleaseInfo.Parse(bad[i]) != null) return "accepted case " + i;
                return null;
            });

            Check("check_schedule", () =>
            {
                var s = new UpdateSchedule();
                var now = new DateTime(2026, 11, 17, 12, 0, 0, DateTimeKind.Utc);
                bool Due(DateTime? last, bool enabled = true, bool dev = false, double since = 60) =>
                    s.ShouldCheck(now, last, enabled, dev, TimeSpan.FromSeconds(since));
                if (Due(null, dev: true) || Due(null, enabled: false) || Due(null, since: 10)) return "checked when it shouldn't";
                if (!Due(null)) return "no first check";
                if (!Due(now.AddHours(-24))) return "no check after 24 h";
                return Due(now.AddHours(-23)) ? "checked after 23 h" : null;
            });

            Check("notice_once_per_version", () =>
            {
                var n = new UpdateNotice();
                var current = Version.Parse("0.5.0");
                var answers = new[] { "0.6.0", "0.6.0", "0.6.1", "0.5.0" }.Select(v => n.Announce(Version.Parse(v), current)).ToArray();
                return answers.SequenceEqual(new[] { true, false, true, false }) ? null : string.Join(",", answers);
            });

            Check("notice_survives_a_relaunch", () =>
            {
                var n = new UpdateNotice(Version.Parse("0.6.0"));      // saved by the previous run
                var current = Version.Parse("0.5.0");
                if (n.Announce(Version.Parse("0.6.0"), current)) return "alerted again after a relaunch";
                return n.Announce(Version.Parse("0.6.1"), current) ? null : "no alert for a newer one";
            });

            Check("found_update_survives_a_relaunch", () =>
            {
                var r = ReleaseInfo.Parse(sampleRelease);
                var restored = ReleaseInfo.Restore(r.Saved(), Version.Parse("0.5.1"));
                if (restored == null || restored.Version != r.Version || restored.Signature != r.Signature) return "not restored";
                if (ReleaseInfo.Restore(r.Saved(), Version.Parse("0.6.0")) != null) return "kept once installed";
                return ReleaseInfo.Restore("garbage", Version.Parse("0.5.1")) == null ? null : "restored garbage";
            });

            Check("install_plan_order", () =>
            {
                var order = Updates.InstallOrder.ToList();
                var verify = order.IndexOf(InstallStep.Verify);
                return verify >= 0 && verify < order.IndexOf(InstallStep.StopBridge) && verify < order.IndexOf(InstallStep.MoveOldAside)
                       && verify < order.IndexOf(InstallStep.Unzip) ? null : string.Join(",", order);
            });

            var current_ = Version.Parse("0.6.0");
            BuildInfo Found(string json) => BuildInfo.Parse(json);
            var newer = Found("{\"runtime\": \"bundled\", \"version\": \"0.6.1\", \"is_dev\": false}");
            Check("install_plan_refuses_damaged", () =>
                Updates.InstallProblem(newer, current_, shaOK: false, signatureOK: true, allowOlder: false)
                    == "the download is damaged (its SHA-256 doesn't match)" ? null : "wrong reason");
            Check("install_plan_refuses_bad_signature", () =>
                Updates.InstallProblem(newer, current_, shaOK: true, signatureOK: false, allowOlder: false)
                    == "it isn't signed with your LoupedeckBridge release key" ? null : "wrong reason");
            Check("install_plan_refuses_not_a_release", () =>
            {
                foreach (var json in new[] { "{\"runtime\": \"repo\", \"repo\": \"C:\\\\r\", \"version\": \"0.6.1\", \"is_dev\": true}",
                                             "{\"runtime\": \"bundled\", \"version\": \"0.6.1\", \"is_dev\": true}", null })
                {
                    var why = Updates.InstallProblem(json == null ? null : Found(json), current_, true, true, false);
                    if (why != "it isn't a LoupedeckBridge release") return json + ": " + why;
                }
                return null;
            });
            Check("install_plan_refuses_no_version", () =>
                Updates.InstallProblem(Found("{\"runtime\": \"bundled\", \"version\": \"new\"}"), current_, true, true, false)
                    == "it has no readable version" ? null : "wrong reason");
            Check("install_plan_refuses_not_newer", () =>
            {
                var same = Found("{\"runtime\": \"bundled\", \"version\": \"0.6.0\"}");
                if (Updates.InstallProblem(same, current_, true, true, false) != "it isn't newer than the installed v0.6.0")
                    return "same version: " + Updates.InstallProblem(same, current_, true, true, false);
                return Updates.InstallProblem(same, current_, true, true, allowOlder: true) == null ? null : "-AllowOlder";
            });
            Check("install_plan_accepts_valid", () =>
                Updates.InstallProblem(newer, current_, true, true, false) is string why ? why : null);

            Check("zip_layout_refuses_unsafe_paths", () =>
            {
                // Review Focus 4: nothing may land outside the folder it's unpacked into.
                var good = new[] { "LoupedeckBridge/", "LoupedeckBridge/LoupedeckBridge.exe", "LoupedeckBridge/LoupedeckBridge.json",
                                   "LoupedeckBridge/app/bridge/__init__.py" };
                var goodWhy = Updates.ZipLayoutProblem(good);
                if (goodWhy != null) return "refused a good one: " + goodWhy;
                var bad = new[]
                {
                    good.Concat(new[] { "LoupedeckBridge/../evil.txt" }), good.Concat(new[] { @"LoupedeckBridge\..\evil.txt" }),
                    good.Concat(new[] { "C:/evil.txt" }), good.Concat(new[] { "/evil.txt" }), good.Concat(new[] { @"\evil.txt" }),
                    good.Concat(new[] { "Other/x" }), good.Concat(new[] { "LoupedeckBridge/app/x.txt:stream" }),
                    good.Where(n => !n.EndsWith(".exe")), good.Where(n => !n.EndsWith(".json")), new string[0],
                };
                for (var i = 0; i < bad.Length; i++) if (Updates.ZipLayoutProblem(bad[i]) == null) return "accepted case " + i;
                return null;
            });

            Check("download_is_capped_and_hashed", () =>
            {
                var data = Enumerable.Range(0, 1024).Select(i => (byte)i).ToArray();
                var sink = new System.IO.MemoryStream();
                var hash = Download.CopyCapped(new System.IO.MemoryStream(data), sink, limit: 1024);
                var want = BitConverter.ToString(System.Security.Cryptography.SHA256.Create().ComputeHash(data)).Replace("-", "").ToLowerInvariant();
                if (hash != want || sink.Length != 1024) return "hash or length";
                try
                {
                    Download.CopyCapped(new System.IO.MemoryStream(data), new System.IO.MemoryStream(), limit: 1023);
                    return "a download past the limit was accepted";
                }
                catch (DownloadTooLargeException) { return null; }
            });

            // ---- swapping a new version in (the new copy finishes the update after the old one exits) -------------
            string Scratch()
            {
                var top = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "lb-swap-" + Guid.NewGuid().ToString("N"));
                scratch.Add(top);
                var dir = System.IO.Path.Combine(top, "Programs");
                System.IO.Directory.CreateDirectory(dir);
                return dir;
            }
            string Version_(string dir) => System.IO.File.ReadAllText(System.IO.Path.Combine(dir, "version.txt"));
            void MakeApp(string dir, string version, bool complete = true)
            {
                System.IO.Directory.CreateDirectory(System.IO.Path.Combine(dir, "app"));
                System.IO.File.WriteAllText(System.IO.Path.Combine(dir, "version.txt"), version);
                System.IO.File.WriteAllText(System.IO.Path.Combine(dir, "app", "code.py"), "# v" + version);
                if (!complete) return;
                System.IO.File.WriteAllText(System.IO.Path.Combine(dir, "LoupedeckBridge.exe"), "MZ");
                System.IO.File.WriteAllText(System.IO.Path.Combine(dir, BuildInfo.FileName),
                    "{\"runtime\": \"bundled\", \"version\": \"" + version + "\", \"is_dev\": false}");
            }

            Check("swap_moves_old_aside_and_copies_new", () =>
            {
                var root = Scratch();
                var install = System.IO.Path.Combine(root, "LoupedeckBridge");
                MakeApp(install, "0.6.0");
                MakeApp(Swap.NewDir(install), "0.6.1");
                var why = Swap.Run(install, Swap.NewDir(install), Swap.CopyTree);
                if (why != null) return why;
                return Version_(install) == "0.6.1" && Version_(Swap.PreviousDir(install)) == "0.6.0"
                    ? null : $"installed {Version_(install)}, previous {Version_(Swap.PreviousDir(install))}";
            });

            Check("swap_replaces_an_older_previous", () =>
            {
                var root = Scratch();
                var install = System.IO.Path.Combine(root, "LoupedeckBridge");
                MakeApp(Swap.PreviousDir(install), "0.5.9");
                MakeApp(install, "0.6.0");
                MakeApp(Swap.NewDir(install), "0.6.1");
                var why = Swap.Run(install, Swap.NewDir(install), Swap.CopyTree);
                return why == null && Version_(Swap.PreviousDir(install)) == "0.6.0" ? null : why ?? "previous wasn't replaced";
            });

            Check("swap_failure_puts_the_old_back", () =>
            {
                // Review Focus 5: a copy that fails midway (a full disk, a locked file) puts the old version back.
                var root = Scratch();
                var install = System.IO.Path.Combine(root, "LoupedeckBridge");
                MakeApp(install, "0.6.0");
                MakeApp(Swap.NewDir(install), "0.6.1");
                var why = Swap.Run(install, Swap.NewDir(install), (from, to) =>
                {
                    System.IO.Directory.CreateDirectory(to);
                    System.IO.File.Copy(System.IO.Path.Combine(from, "version.txt"), System.IO.Path.Combine(to, "version.txt"));
                    throw new System.IO.IOException("There is not enough space on the disk.");
                });
                if (why == null || !why.StartsWith(Updates.StepLabel(InstallStep.CopyNewIn) + ": ")) return "result: " + why;
                if (Version_(install) != "0.6.0" || System.IO.File.ReadAllText(System.IO.Path.Combine(install, "app", "code.py")) != "# v0.6.0")
                    return "the old version isn't back intact";
                return System.IO.Directory.Exists(Swap.PreviousDir(install)) ? "a .previous was left behind" : null;
            });

            // ---- final review (milestone 7): the swap from inside the install folder, and the older .previous kept ---
            Check("swap_from_inside_the_install_folder", () =>
            {
                // A tray started by an update, or from the Start menu, stands in the install folder; Windows won't
                // rename a folder that is a process's current folder, so the finisher's swap must step out first.
                var root = Scratch();
                var install = System.IO.Path.Combine(root, "LoupedeckBridge");
                MakeApp(install, "0.6.0");
                MakeApp(Swap.NewDir(install), "0.6.1");
                var here = Environment.CurrentDirectory;
                try
                {
                    Environment.CurrentDirectory = install;
                    var why = Swap.Run(install, Swap.NewDir(install), Swap.CopyTree);
                    if (why != null) return why;
                    return Version_(install) == "0.6.1" ? null : "installed " + Version_(install);
                }
                finally { Environment.CurrentDirectory = here; }
            });

            Check("swap_failure_keeps_the_older_previous", () =>
            {
                // The old version can't be moved aside (a program holds a file in it): nothing changes, and the older
                // .previous (the version Go back returns to) is still there.
                var root = Scratch();
                var install = System.IO.Path.Combine(root, "LoupedeckBridge");
                MakeApp(Swap.PreviousDir(install), "0.5.9");
                MakeApp(install, "0.6.0");
                MakeApp(Swap.NewDir(install), "0.6.1");
                string why;
                using (System.IO.File.Open(System.IO.Path.Combine(install, "app", "code.py"), System.IO.FileMode.Open,
                                           System.IO.FileAccess.Read, System.IO.FileShare.Read))
                    why = Swap.Run(install, Swap.NewDir(install), Swap.CopyTree);
                if (why == null || !why.StartsWith(Updates.StepLabel(InstallStep.MoveOldAside) + ": ")) return "result: " + why;
                if (Version_(install) != "0.6.0") return "installed " + Version_(install);
                return System.IO.Directory.Exists(Swap.PreviousDir(install)) && Version_(Swap.PreviousDir(install)) == "0.5.9"
                    ? null : "the older .previous is gone";
            });

            Check("swap_copy_failure_keeps_the_older_previous", () =>
            {
                var root = Scratch();
                var install = System.IO.Path.Combine(root, "LoupedeckBridge");
                MakeApp(Swap.PreviousDir(install), "0.5.9");
                MakeApp(install, "0.6.0");
                MakeApp(Swap.NewDir(install), "0.6.1");
                var why = Swap.Run(install, Swap.NewDir(install), (from, to) => throw new System.IO.IOException("disk full"));
                if (why == null || !why.StartsWith(Updates.StepLabel(InstallStep.CopyNewIn) + ": ")) return "result: " + why;
                if (Version_(install) != "0.6.0") return "installed " + Version_(install);
                return System.IO.Directory.Exists(Swap.PreviousDir(install)) && Version_(Swap.PreviousDir(install)) == "0.5.9"
                    ? null : "the older .previous is gone";
            });

            Check("go_back_swaps_previous_in", () =>
            {
                var root = Scratch();
                var install = System.IO.Path.Combine(root, "LoupedeckBridge");
                MakeApp(install, "0.6.1");
                MakeApp(Swap.PreviousDir(install), "0.6.0");
                var why = Swap.GoBack(install, Swap.CopyTree) ?? Swap.Run(install, Swap.NewDir(install), Swap.CopyTree);
                if (why != null) return why;
                return Version_(install) == "0.6.0" && Version_(Swap.PreviousDir(install)) == "0.6.1"
                    ? null : $"installed {Version_(install)}, previous {Version_(Swap.PreviousDir(install))}";
            });

            Check("go_back_needs_a_complete_previous", () =>
            {
                var root = Scratch();
                var install = System.IO.Path.Combine(root, "LoupedeckBridge");
                if (Swap.GoBackProblem(Swap.PreviousDir(install)) == null) return "accepted a missing previous";
                MakeApp(Swap.PreviousDir(install), "0.6.0", complete: false);
                if (Swap.GoBackProblem(Swap.PreviousDir(install)) == null) return "accepted one without its exe";
                MakeApp(Swap.PreviousDir(install), "0.6.0");
                return Swap.GoBackProblem(Swap.PreviousDir(install));
            });

            // ---- security review (milestone 7): downloads only from GitHub, the swap only from its .new folder --------
            Check("release_parse_needs_github_downloads", () =>
            {
                var elsewhere = sampleRelease.Replace("https://github.com/o/r/releases/download/v0.6.0/" + windowsZip + "\"",
                                                      "https://example.com/o/r/releases/download/v0.6.0/" + windowsZip + "\"");
                return ReleaseInfo.Parse(elsewhere) == null ? null : "accepted a download from another host";
            });

            Check("restore_refuses_other_hosts_and_names", () =>
            {
                var saved = ReleaseInfo.Parse(sampleRelease).Saved();
                var current06 = Version.Parse("0.5.1");
                var otherHost = saved.Replace("https://github.com/", "https://example.com/");
                if (ReleaseInfo.Restore(otherHost, current06) != null) return "restored another host";
                var otherName = saved.Replace(windowsZip + ".p7s", "evil.p7s");
                return ReleaseInfo.Restore(otherName, current06) == null ? null : "restored another file name";
            });

            Check("finish_update_only_from_the_new_folder", () =>
            {
                var install = @"C:\Users\Zoë\AppData\Local\Programs\LoupedeckBridge";
                if (!Swap.IsNewDirOf(install + ".new", install)) return "refused the real .new folder";
                if (!Swap.IsNewDirOf(install.ToUpperInvariant() + ".NEW\\", install)) return "refused it with other case and a slash";
                foreach (var other in new[] { @"C:\Windows", install, install + ".previous", @"C:\Users\Zoë\Downloads\LoupedeckBridge" })
                    if (Swap.IsNewDirOf(other, install)) return "accepted " + other;
                return Swap.IsNewDirOf(@"C:\x.new", @"C:\Users") ? "accepted an unrelated folder" : null;
            });

            // ---- final review minors (milestone 7) ---------------------------------------------------------------
            Check("background_failures_become_results", () =>
            {
                // Minor 3: an error the updater didn't foresee (here, ones SignedCms or an unzip could throw) is a failed
                // check or install with its reason, never .NET's crash dialog or a menu stuck at "Checking...".
                var outcome = Background.Safely<string>(() => throw new NotSupportedException("odd signature"), why => "failed: " + why).Result;
                if (outcome != "failed: odd signature") return "got " + outcome;
                var nested = Background.Safely<string>(() => throw new AggregateException(new ArgumentException("bad entry")), why => why).Result;
                if (nested != "bad entry") return "got " + nested;
                return Background.Safely(() => "fine", why => "failed").Result == "fine" ? null : "a result was lost";
            });

            Check("finish_update_starts_whatever_copy_is_left", () =>
            {
                // Minor 4: if both the swap and its put-back fail, start the copy that's still whole, not a missing exe.
                var root = Scratch();
                var install = System.IO.Path.Combine(root, "LoupedeckBridge");
                MakeApp(install, "0.6.1");
                MakeApp(Swap.PreviousDir(install), "0.6.0");
                MakeApp(Swap.NewDir(install), "0.6.2");
                string Exe(string dir) => System.IO.Path.Combine(dir, "LoupedeckBridge.exe");
                if (Swap.ExeToStart(install) != Exe(install)) return "not the installed copy: " + Swap.ExeToStart(install);
                System.IO.Directory.Delete(install, true);
                if (Swap.ExeToStart(install) != Exe(Swap.PreviousDir(install))) return "not the previous copy: " + Swap.ExeToStart(install);
                System.IO.Directory.Delete(Swap.PreviousDir(install), true);
                return Swap.ExeToStart(install) == Exe(Swap.NewDir(install)) ? null : "not the new copy: " + Swap.ExeToStart(install);
            });

            Check("install_steps_are_named_in_plain_words", () =>
            {
                // Minor 5: an alert said "MoveOldAside: ...".
                var labels = new List<string>();
                foreach (InstallStep step in Enum.GetValues(typeof(InstallStep)))
                {
                    var label = Updates.StepLabel(step);
                    if (string.IsNullOrEmpty(label) || label.Contains(step.ToString())) return $"{step}: '{label}'";
                    labels.Add(label);
                }
                if (labels.Distinct().Count() != labels.Count) return "two steps share a label: " + string.Join(", ", labels);
                var root = Scratch();
                var install = System.IO.Path.Combine(root, "LoupedeckBridge");
                MakeApp(install, "0.6.0");
                MakeApp(Swap.NewDir(install), "0.6.1");
                var why = Swap.Run(install, Swap.NewDir(install), (from, to) => throw new System.IO.IOException("disk full"));
                return why != null && why.StartsWith(Updates.StepLabel(InstallStep.CopyNewIn) + ": ") ? null : "got " + why;
            });

            Environment.CurrentDirectory = System.IO.Path.GetTempPath();   // Swap.Run stepped into a scratch folder
            foreach (var dir in scratch)
            {
                try { System.IO.Directory.Delete(dir, recursive: true); }
                catch (Exception e) when (e is System.IO.IOException || e is UnauthorizedAccessException) { }
            }
            return failures == 0 ? 0 : 1;
        }
    }
}
