// The tray app's rules, kept free of WinForms so tests/PolicyTests.cs can check them directly. Ported from
// macos/launcher/Policies.swift (milestone 7), with the same numbers:
// - which status lines the bridge sends (bridge/status.py), and what the tooltip says
// - when to alert (AlertPolicy), and when to restart a bridge that stopped (RestartPolicy, BridgeSupervisor)
// - which Python to run (RuntimePaths, BridgeCommand), and release versions (Version)
// Time is seconds as a plain double (the app passes a monotonic clock).

using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;

namespace LoupedeckBridge
{
    /// Reading JSON with the .NET Framework's own parser (no packages).
    public static class Json
    {
        /// The JSON object in `text`, or null for anything else.
        public static Dictionary<string, object> Object(string text)
        {
            if (string.IsNullOrWhiteSpace(text)) return null;
            try { return new JavaScriptSerializer().DeserializeObject(text) as Dictionary<string, object>; }
            catch (Exception e) when (e is ArgumentException || e is InvalidOperationException) { return null; }
        }

        /// A field that may be missing or null (value = default); false only if it's there with another type.
        public static bool Optional<T>(Dictionary<string, object> fields, string key, out T value)
        {
            value = default;
            if (!fields.TryGetValue(key, out var raw) || raw == null) return true;
            if (!(raw is T typed)) return false;
            value = typed;
            return true;
        }

        /// A field that must be there, with this type.
        public static bool Required<T>(Dictionary<string, object> fields, string key, out T value)
        {
            value = default;
            if (!fields.TryGetValue(key, out var raw) || !(raw is T typed)) return false;
            value = typed;
            return true;
        }
    }

    /// One status line from the bridge.
    public sealed class BridgeStatus : IEquatable<BridgeStatus>
    {
        public bool Loupedeck { get; }
        public bool Lightroom { get; }
        public string Keys { get; }            // "allowed", "missing" or "unavailable"
        public string FiveMode { get; }        // "ratings", "colours" or "keys"
        public string SettingsUrl { get; }     // null when the settings page is off
        public bool LoupedeckBusy { get; }     // another program has the Loupedeck open (milestone 7)

        public BridgeStatus(bool loupedeck, bool lightroom, string keys, string fiveMode, string settingsUrl,
                            bool loupedeckBusy)
        {
            Loupedeck = loupedeck; Lightroom = lightroom; Keys = keys; FiveMode = fiveMode; SettingsUrl = settingsUrl;
            LoupedeckBusy = loupedeckBusy;
        }

        /// The status in one line of the bridge's output, or null for anything else.
        public static BridgeStatus Parse(string line)
        {
            var f = Json.Object(line);
            if (f == null) return null;
            if (!Json.Required(f, "loupedeck", out bool loupedeck) || !Json.Required(f, "lightroom", out bool lightroom)
                || !Json.Required(f, "keys", out string keys) || !Json.Required(f, "five_mode", out string fiveMode)
                || !Json.Optional(f, "settings_url", out string url) || !Json.Optional(f, "loupedeck_busy", out bool busy))
                return null;
            return new BridgeStatus(loupedeck, lightroom, keys, fiveMode, url, busy);
        }

        public bool Equals(BridgeStatus other) =>
            other != null && Loupedeck == other.Loupedeck && Lightroom == other.Lightroom && Keys == other.Keys
            && FiveMode == other.FiveMode && SettingsUrl == other.SettingsUrl && LoupedeckBusy == other.LoupedeckBusy;
        public override bool Equals(object obj) => Equals(obj as BridgeStatus);
        public override int GetHashCode() => (Keys ?? "").GetHashCode() ^ (FiveMode ?? "").GetHashCode();
        public override string ToString() =>
            $"loupedeck={Loupedeck} busy={LoupedeckBusy} lightroom={Lightroom} keys={Keys} five={FiveMode} url={SettingsUrl}";
    }

    public sealed class Alert : IEquatable<Alert>
    {
        public enum Kinds { Disconnected, Back, BridgeStopped }
        public Kinds Kind { get; }
        public bool WillRestart { get; }       // BridgeStopped only

        Alert(Kinds kind, bool willRestart) { Kind = kind; WillRestart = willRestart; }

        public static readonly Alert Disconnected = new Alert(Kinds.Disconnected, false);
        public static readonly Alert Back = new Alert(Kinds.Back, false);
        public static Alert Stopped(bool willRestart) => new Alert(Kinds.BridgeStopped, willRestart);

        public bool Equals(Alert other) => other != null && Kind == other.Kind && WillRestart == other.WillRestart;
        public override bool Equals(object obj) => Equals(obj as Alert);
        public override int GetHashCode() => (int)Kind * 2 + (WillRestart ? 1 : 0);
        public override string ToString() => Kind == Kinds.BridgeStopped ? $"BridgeStopped(willRestart: {WillRestart})" : Kind.ToString();
    }

    /// When to alert about the Loupedeck (the design's rules):
    /// - "disconnected" only for a Loupedeck that was connected during this run (armed by the first connect), still
    ///   gone after `Debounce` seconds, not within `WakeGrace` of a wake, at most once per `MinInterval` (a held-back
    ///   alert fires later if it's still gone);
    /// - "back" only after a "disconnected" was shown.
    /// Windows needs no keyboard permission, so there's no "keys missing" alert.
    public sealed class AlertPolicy
    {
        public double Debounce = 3.0;
        public double WakeGrace = 15.0;
        public double MinInterval = 60.0;

        bool armed;                            // a Loupedeck has connected during this run
        bool connected;
        double? goneSince;                     // a drop waiting to become an alert
        bool shownDisconnect;                  // so "back" follows only a shown "disconnected"
        double lastDisconnect = double.NegativeInfinity;
        double wakeUntil = double.NegativeInfinity;

        public List<Alert> Status(BridgeStatus s, double now)
        {
            var output = new List<Alert>();
            if (s.Loupedeck)
            {
                armed = true;
                goneSince = null;
                if (shownDisconnect)
                {
                    shownDisconnect = false;
                    output.Add(Alert.Back);
                }
            }
            else if (connected && armed && goneSince == null)
            {
                goneSince = now;
            }
            connected = s.Loupedeck;
            return output;
        }

        /// Called about once a second: sends a pending "disconnected" once the rules allow it.
        public List<Alert> Tick(double now)
        {
            if (goneSince == null || connected || now - goneSince.Value < Debounce || now < wakeUntil
                || now - lastDisconnect < MinInterval) return new List<Alert>();
            goneSince = null;
            shownDisconnect = true;
            lastDisconnect = now;
            return new List<Alert> { Alert.Disconnected };
        }

        /// USB devices re-enumerate on wake: hold disconnect alerts for a while.
        public void DidWake(double now) => wakeUntil = now + WakeGrace;

        /// The bridge exited: what it last said about the Loupedeck no longer counts. Its shutdown isn't an unplug,
        /// so a pending "disconnected" is dropped.
        public void BridgeStopped()
        {
            armed = false;
            connected = false;
            goneSince = null;
        }

        /// A new bridge run: nothing is known about the Loupedeck until it connects again.
        public void BridgeRestarted() => BridgeStopped();
    }

    /// When to restart a bridge that stopped by itself: after `Delay` seconds, at most `MaxRestarts` times in
    /// `Window` seconds. A clean exit (0) or "already running" (3) is never a crash.
    public sealed class RestartPolicy
    {
        public const int AlreadyRunning = 3;   // bridge/__main__.py EXIT_ALREADY_RUNNING
        public double Delay = 5.0;
        public double Window = 600.0;
        public int MaxRestarts = 3;
        readonly List<double> restarts = new List<double>();

        public bool ShouldRestart(int exitCode, double now)
        {
            if (exitCode == 0 || exitCode == AlreadyRunning) return false;
            restarts.RemoveAll(t => now - t >= Window);
            if (restarts.Count >= MaxRestarts) return false;
            restarts.Add(now);
            return true;
        }
    }

    /// What the app does when the bridge starts, exits or restarts, or the user quits.
    public sealed class SupervisorAction : IEquatable<SupervisorAction>
    {
        public enum Kinds { Spawn, StopBridge, ReleaseKeys, Alert, ScheduleRestart, TerminateApp, ReadyToSwap }
        public Kinds Kind { get; }
        public Alert AlertToShow { get; }      // Alert only
        public int Token { get; }              // ScheduleRestart only: only the newest scheduled restart may fire
        public double After { get; }           // ScheduleRestart only, seconds

        SupervisorAction(Kinds kind, Alert alert = null, int token = 0, double after = 0)
        {
            Kind = kind; AlertToShow = alert; Token = token; After = after;
        }

        public static readonly SupervisorAction Spawn = new SupervisorAction(Kinds.Spawn);
        public static readonly SupervisorAction StopBridge = new SupervisorAction(Kinds.StopBridge);     // "stop", then kill after 5 s
        public static readonly SupervisorAction ReleaseKeys = new SupervisorAction(Kinds.ReleaseKeys);   // it ended without its own clean-up
        public static readonly SupervisorAction TerminateApp = new SupervisorAction(Kinds.TerminateApp);
        public static readonly SupervisorAction ReadyToSwap = new SupervisorAction(Kinds.ReadyToSwap);   // an update may now proceed
        public static SupervisorAction Alert(Alert alert) => new SupervisorAction(Kinds.Alert, alert: alert);
        public static SupervisorAction ScheduleRestart(int token, double after) =>
            new SupervisorAction(Kinds.ScheduleRestart, token: token, after: after);

        public bool Equals(SupervisorAction other) =>
            other != null && Kind == other.Kind && Token == other.Token && After == other.After
            && Equals(AlertToShow, other.AlertToShow);
        public override bool Equals(object obj) => Equals(obj as SupervisorAction);
        public override int GetHashCode() => (int)Kind ^ Token;
        public override string ToString() => Kind == Kinds.Alert ? $"Alert({AlertToShow})"
            : Kind == Kinds.ScheduleRestart ? $"ScheduleRestart({Token}, {After})" : Kind.ToString();
    }

    /// The decisions only, so they're testable without WinForms; the app (TrayApp.cs) carries out the actions.
    /// Keys are let go after a forced stop, status lines from a bridge on its way out are ignored, and a restart
    /// (automatic or from the menu) can never start a second bridge.
    public sealed class BridgeSupervisor
    {
        public enum States { Idle, Running, WaitingToRestart, Stopped, Updating, Quitting }
        public States State { get; private set; } = States.Idle;
        RestartPolicy restarts = new RestartPolicy();
        int token;

        /// Status lines count only while the bridge runs, not once it's exiting, stopped or quitting.
        public bool AcceptsStatus => State == States.Running;
        /// The menu shows "stopped" (and offers Restart) in these states.
        public bool IsStopped => State == States.Stopped || State == States.WaitingToRestart;
        public double RestartDelay => restarts.Delay;

        public List<SupervisorAction> Start()
        {
            State = States.Running;
            return new List<SupervisorAction> { SupervisorAction.Spawn };
        }

        public List<SupervisorAction> SpawnFailed()
        {
            State = States.Stopped;
            return new List<SupervisorAction> { SupervisorAction.Alert(Alert.Stopped(willRestart: false)) };
        }

        public List<SupervisorAction> Exited(int code, double now)
        {
            var hard = code != 0 && code != RestartPolicy.AlreadyRunning;   // no clean-up of its own
            var output = new List<SupervisorAction>();
            if (hard) output.Add(SupervisorAction.ReleaseKeys);
            if (State == States.Quitting)
            {
                output.Add(SupervisorAction.TerminateApp);
                return output;
            }
            if (State == States.Updating)
            {
                output.Add(SupervisorAction.ReadyToSwap);
                return output;
            }
            if (code == RestartPolicy.AlreadyRunning)
            {
                State = States.Stopped;
                return new List<SupervisorAction> { SupervisorAction.TerminateApp };   // another LoupedeckBridge runs
            }
            var restart = restarts.ShouldRestart(code, now);
            if (hard) output.Add(SupervisorAction.Alert(Alert.Stopped(willRestart: restart)));
            if (restart)
            {
                token += 1;
                State = States.WaitingToRestart;
                output.Add(SupervisorAction.ScheduleRestart(token, restarts.Delay));
            }
            else
            {
                State = States.Stopped;        // exit 0: a deliberate stop; or the budget is used up
            }
            return output;
        }

        public List<SupervisorAction> RestartTimerFired(int fired)
        {
            if (State != States.WaitingToRestart || fired != token) return new List<SupervisorAction>();
            State = States.Running;
            return new List<SupervisorAction> { SupervisorAction.Spawn };
        }

        /// "Restart bridge" in the menu: only when it's stopped (a stale menu click does nothing).
        public List<SupervisorAction> ManualRestart()
        {
            if (!IsStopped) return new List<SupervisorAction>();
            token += 1;                        // cancels a pending automatic restart
            restarts = new RestartPolicy();    // a fresh budget after a deliberate restart
            State = States.Running;
            return new List<SupervisorAction> { SupervisorAction.Spawn };
        }

        /// An update is about to replace the app: stop the bridge like Quit does, but keep the app running so it can
        /// hand over (or bring the bridge back if the update fails). A pending automatic restart is cancelled.
        public List<SupervisorAction> StopForUpdate(bool bridgeRunning)
        {
            if (State == States.Updating || State == States.Quitting) return new List<SupervisorAction>();
            token += 1;
            State = States.Updating;
            return new List<SupervisorAction> { bridgeRunning ? SupervisorAction.StopBridge : SupervisorAction.ReadyToSwap };
        }

        /// The update failed after the bridge was stopped: start it again, with a fresh restart budget.
        public List<SupervisorAction> UpdateAbandoned()
        {
            if (State != States.Updating) return new List<SupervisorAction>();
            restarts = new RestartPolicy();
            State = States.Running;
            return new List<SupervisorAction> { SupervisorAction.Spawn };
        }

        public List<SupervisorAction> Quit(bool bridgeRunning)
        {
            if (State == States.Quitting) return new List<SupervisorAction>();
            State = States.Quitting;
            return new List<SupervisorAction> { bridgeRunning ? SupervisorAction.StopBridge : SupervisorAction.TerminateApp };
        }
    }

    /// Which Python to run, and where, from the build info:
    /// - "bundled" (releases): the Python and code in the app's folder
    /// - "repo" (the dev build): the checkout's .venv and code
    public sealed class RuntimePaths
    {
        public string Python { get; }
        public string Workdir { get; }

        RuntimePaths(string python, string workdir) { Python = python; Workdir = workdir; }

        public static RuntimePaths Resolve(BuildInfo info, string appDir)
        {
            switch (info?.Runtime)
            {
                case "bundled":
                    return new RuntimePaths(System.IO.Path.Combine(appDir, "python", "python.exe"),
                                            System.IO.Path.Combine(appDir, "app"));
                case "repo":
                    if (string.IsNullOrEmpty(info.Repo)) return null;
                    return new RuntimePaths(System.IO.Path.Combine(info.Repo, ".venv", "Scripts", "python.exe"), info.Repo);
                default:
                    return null;
            }
        }

        public override string ToString() => Python + " in " + Workdir;
    }

    public static class BridgeCommand
    {
        /// The bridge's Python arguments. -E: ignore PYTHON* variables; -s: ignore the user's own site-packages;
        /// -B: never write __pycache__ (a release comes precompiled); -X utf8: UTF-8 for files and pipes.
        public static List<string> Arguments(IEnumerable<string> extra) =>
            new List<string> { "-E", "-s", "-B", "-X", "utf8", "-m", "bridge" }.Concat(extra ?? Enumerable.Empty<string>()).ToList();
    }

    /// Building a Windows command line that the started program splits back into exactly these arguments
    /// (CommandLineToArgvW's rules: quotes around anything with spaces or quotes; backslashes doubled before a quote
    /// and at the end of a quoted argument).
    public static class CommandLine
    {
        public static string Quote(string arg)
        {
            if (arg.Length > 0 && arg.IndexOfAny(new[] { ' ', '\t', '\n', '\v', '"' }) < 0) return arg;
            var quoted = new System.Text.StringBuilder("\"");
            for (var i = 0; ; i++)
            {
                var backslashes = 0;
                while (i < arg.Length && arg[i] == '\\') { i++; backslashes++; }
                if (i == arg.Length)
                {
                    quoted.Append('\\', backslashes * 2);
                    break;
                }
                if (arg[i] == '"') quoted.Append('\\', backslashes * 2 + 1).Append('"');
                else quoted.Append('\\', backslashes).Append(arg[i]);
            }
            return quoted.Append('"').ToString();
        }

        public static string Join(IEnumerable<string> args) => string.Join(" ", args.Select(Quote));
    }

    /// A release version: three numbers, compared numerically ("0.10.0" > "0.9.9"). A leading "v" is allowed.
    public sealed class Version : IComparable<Version>, IEquatable<Version>
    {
        static readonly Regex Shape = new Regex(@"^v?([0-9]+)\.([0-9]+)\.([0-9]+)$", RegexOptions.CultureInvariant);
        readonly int[] parts;

        Version(int[] parts) { this.parts = parts; }

        public static Version Parse(string text)
        {
            if (text == null) return null;
            var m = Shape.Match(text);
            if (!m.Success) return null;
            var parts = new int[3];
            for (var i = 0; i < 3; i++)
                if (!int.TryParse(m.Groups[i + 1].Value, System.Globalization.NumberStyles.None,
                                  System.Globalization.CultureInfo.InvariantCulture, out parts[i])) return null;
            return new Version(parts);
        }

        public int CompareTo(Version other)
        {
            if (other is null) return 1;
            for (var i = 0; i < 3; i++)
                if (parts[i] != other.parts[i]) return parts[i].CompareTo(other.parts[i]);
            return 0;
        }

        public bool Equals(Version other) => !(other is null) && CompareTo(other) == 0;
        public override bool Equals(object obj) => Equals(obj as Version);
        public override int GetHashCode() => parts[0] * 1_000_000 + parts[1] * 1_000 + parts[2];
        public override string ToString() => string.Join(".", parts);

        public static bool operator ==(Version a, Version b) => a is null ? b is null : a.Equals(b);
        public static bool operator !=(Version a, Version b) => !(a == b);
        public static bool operator <(Version a, Version b) => !(a is null) && a.CompareTo(b) < 0;
        public static bool operator >(Version a, Version b) => !(a is null) && a.CompareTo(b) > 0;
        public static bool operator <=(Version a, Version b) => !(a > b);
        public static bool operator >=(Version a, Version b) => !(a < b);
    }

    // ---- updates (the Mac's Policies.swift, for the Windows downloads) ----------------------------------------

    /// The newest release, from GitHub's "latest release" JSON. Only a full release (not a draft or pre-release) with
    /// all three Windows downloads counts: LoupedeckBridge-v<ver>-windows-x64.zip, its .sha256 and its .p7s.
    public sealed class ReleaseInfo
    {
        public Version Version { get; }
        public Uri Zip { get; }
        public Uri Sha256 { get; }
        public Uri Signature { get; }

        ReleaseInfo(Version version, Uri zip, Uri sha256, Uri signature)
        {
            Version = version; Zip = zip; Sha256 = sha256; Signature = signature;
        }

        public static string AssetName(Version version) => $"LoupedeckBridge-v{version}-windows-x64.zip";

        /// A download address the updater may use: https on github.com (its downloads then redirect to GitHub's own
        /// storage), ending in exactly the expected file name. Anything else, e.g. a saved entry someone changed, is
        /// refused (security review; the signature check would refuse the file anyway).
        static Uri GitHubDownload(string link, string fileName)
        {
            if (!Uri.TryCreate(link, UriKind.Absolute, out var url) || url.Scheme != Uri.UriSchemeHttps
                || !string.Equals(url.Host, "github.com", StringComparison.OrdinalIgnoreCase)) return null;
            return string.Equals(Uri.UnescapeDataString(url.Segments.LastOrDefault() ?? ""), fileName, StringComparison.Ordinal)
                ? url : null;
        }

        public static ReleaseInfo Parse(string json)
        {
            var f = Json.Object(json);
            if (f == null || !Json.Required(f, "tag_name", out string tag) || !Json.Optional(f, "draft", out bool draft)
                || !Json.Optional(f, "prerelease", out bool prerelease) || draft || prerelease
                || !Json.Required(f, "assets", out object[] assets)) return null;
            var version = Version.Parse(tag);
            if (version == null) return null;
            var urls = new Dictionary<string, Uri>();
            foreach (var asset in assets.OfType<Dictionary<string, object>>())
            {
                if (Json.Required(asset, "name", out string name) && Json.Required(asset, "browser_download_url", out string link)
                    && GitHubDownload(link, name) is Uri url)
                    urls[name] = url;
            }
            var zip = AssetName(version);
            if (!urls.TryGetValue(zip, out var zipUrl) || !urls.TryGetValue(zip + ".sha256", out var shaUrl)
                || !urls.TryGetValue(zip + ".p7s", out var sigUrl)) return null;
            return new ReleaseInfo(version, zipUrl, shaUrl, sigUrl);
        }

        /// For the app's saved preferences, so a found update survives a relaunch.
        public string Saved() => new JavaScriptSerializer().Serialize(new Dictionary<string, string>
        {
            ["version"] = Version.ToString(), ["zip"] = Zip.ToString(), ["sha256"] = Sha256.ToString(),
            ["signature"] = Signature.ToString(),
        });

        /// A saved release, if it's still newer than the running version (null once installed, or if unreadable).
        public static ReleaseInfo Restore(string saved, Version newerThan)
        {
            var f = Json.Object(saved);
            if (f == null || !Json.Required(f, "version", out string v) || !Json.Required(f, "zip", out string zip)
                || !Json.Required(f, "sha256", out string sha) || !Json.Required(f, "signature", out string sig)) return null;
            var version = Version.Parse(v);
            if (version == null || !(version > newerThan)) return null;
            var name = AssetName(version);
            var (zipUrl, shaUrl, sigUrl) = (GitHubDownload(zip, name), GitHubDownload(sha, name + ".sha256"),
                                            GitHubDownload(sig, name + ".p7s"));
            return zipUrl == null || shaUrl == null || sigUrl == null ? null : new ReleaseInfo(version, zipUrl, shaUrl, sigUrl);
        }
    }

    /// When to ask GitHub: never for dev builds or when turned off; not in the first 30 s after launch; then at most
    /// once a day.
    public sealed class UpdateSchedule
    {
        public TimeSpan Interval = TimeSpan.FromHours(24);
        public TimeSpan FirstDelay = TimeSpan.FromSeconds(30);

        public bool ShouldCheck(DateTime nowUtc, DateTime? lastCheckUtc, bool enabled, bool isDev, TimeSpan sinceLaunch)
        {
            if (isDev || !enabled || sinceLaunch < FirstDelay) return false;
            return lastCheckUtc == null || nowUtc - lastCheckUtc.Value >= Interval;
        }
    }

    /// One alert per newer version (the menu item stays as long as it's available). LastAnnounced is saved, so a
    /// relaunch doesn't alert again for the same version.
    public sealed class UpdateNotice
    {
        public Version LastAnnounced { get; private set; }

        public UpdateNotice(Version lastAnnounced = null) { LastAnnounced = lastAnnounced; }

        public bool Announce(Version version, Version current)
        {
            if (!(version > current)) return false;
            if (LastAnnounced != null && version <= LastAnnounced) return false;
            LastAnnounced = version;
            return true;
        }
    }

    /// Background work whose outcome always arrives as a result (final review, minor 3): an exception of any kind, even one
    /// nobody foresaw, becomes `failed(its innermost message)`, so an update check or install fails with a reason
    /// instead of .NET's crash dialog and a menu stuck at "Checking...".
    public static class Background
    {
        public static System.Threading.Tasks.Task<T> Safely<T>(Func<T> work, Func<string, T> failed) =>
            System.Threading.Tasks.Task.Run(() =>
            {
                try { return work(); }
                catch (Exception e)
                {
                    while (e is AggregateException && e.InnerException != null) e = e.InnerException;
                    return failed(e.Message);
                }
            });
    }

    /// The install steps, in order. Everything is checked (Verify) before anything is unpacked, stopped or moved. A
    /// running program can't be moved on Windows, so the new copy finishes the swap after this one exits (HandOver).
    public enum InstallStep { Download, Verify, Unzip, StopBridge, HandOver, MoveOldAside, CopyNewIn, LaunchNew }

    public static class Updates
    {
        public static readonly InstallStep[] InstallOrder =
        {
            InstallStep.Download, InstallStep.Verify, InstallStep.Unzip, InstallStep.StopBridge, InstallStep.HandOver,
            InstallStep.MoveOldAside, InstallStep.CopyNewIn, InstallStep.LaunchNew,
        };

        /// How the menu and alerts name a step (final review, minor 5: not "MoveOldAside").
        public static string StepLabel(InstallStep step)
        {
            switch (step)
            {
                case InstallStep.Download: return "downloading";
                case InstallStep.Verify: return "checking it";
                case InstallStep.Unzip: return "unpacking";
                case InstallStep.StopBridge: return "stopping the bridge";
                case InstallStep.HandOver: return "handing over";
                case InstallStep.MoveOldAside: return "moving the old version aside";
                case InstallStep.CopyNewIn: return "putting the new version in place";
                default: return "starting the new version";
            }
        }

        public const string Folder = "LoupedeckBridge";

        /// Why a release zip's entries aren't safe to unpack, or null. Everything must be inside LoupedeckBridge/, no
        /// entry may climb out (..), name a drive or a stream (:), or start at the root; the exe and its build info
        /// must be there. (Backslashes count as separators, as Windows would treat them.)
        public static string ZipLayoutProblem(IEnumerable<string> entryNames)
        {
            var names = entryNames.Select(n => n.Replace('\\', '/')).ToList();
            if (names.Count == 0) return "the download is empty";
            foreach (var name in names)
            {
                if (name.StartsWith("/") || name.Contains(":")) return $"it holds an unsafe path ({name})";
                if (name.Split('/').Any(part => part == "..")) return $"it holds an unsafe path ({name})";
                if (!name.StartsWith(Folder + "/")) return $"it should hold only a {Folder} folder (it holds {name})";
            }
            if (!names.Contains(Folder + "/LoupedeckBridge.exe")) return "it has no LoupedeckBridge.exe";
            if (!names.Contains(Folder + "/" + BuildInfo.FileName)) return $"it has no {BuildInfo.FileName}";
            return null;
        }

        /// The first reason not to install a downloaded release, in plain words, or null if it may be installed.
        /// `found` is the build info inside the download.
        public static string InstallProblem(BuildInfo found, Version current, bool shaOK, bool signatureOK, bool allowOlder)
        {
            if (!shaOK) return "the download is damaged (its SHA-256 doesn't match)";
            if (!signatureOK) return "it isn't signed with your LoupedeckBridge release key";
            if (found == null || found.Runtime != "bundled" || found.IsDev) return "it isn't a LoupedeckBridge release";
            if (found.Version == null) return "it has no readable version";
            if (found.Version <= current && !allowOlder) return $"it isn't newer than the installed v{current}";
            return null;
        }
    }

    /// The tray icon's tooltip.
    public static class TrayText
    {
        public static string Problem(BridgeSupervisor.States state, bool isStopped, BridgeStatus status)
        {
            if (state == BridgeSupervisor.States.Updating) return "updating…";
            if (isStopped) return "the bridge has stopped";
            if (status == null) return "starting…";
            if (status.LoupedeckBusy) return "the Loupedeck is in use by another program";
            if (!status.Loupedeck) return "the Loupedeck isn't connected";
            if (!status.Lightroom) return "Lightroom isn't connected";
            return "all good";
        }

        /// NotifyIcon.Text takes at most 63 characters on .NET Framework.
        public static string Tooltip(string name, string problem) => name + ": " + problem;
    }
}
