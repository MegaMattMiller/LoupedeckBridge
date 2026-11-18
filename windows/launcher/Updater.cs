// Update checks and installs, for release builds only (milestone 7; the Mac's Updater.swift). Dev builds have none.
//
// The decisions are elsewhere and tested: when to check (UpdateSchedule), what counts as a release (ReleaseInfo),
// whether a download may be installed (Signature, Updates.ZipLayoutProblem, Updates.InstallProblem), in what order
// (Updates.InstallOrder), and the swap itself (Swap). This file does the network, file and process work.
// The only internet use in LoupedeckBridge: api.github.com and GitHub's release downloads.

using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace LoupedeckBridge
{
    sealed class Updater
    {
        public static readonly Uri LatestUrl = new Uri("https://api.github.com/repos/MegaMattMiller/LoupedeckBridge/releases/latest");
        public enum Phases { Idle, Checking, Installing }

        readonly BuildInfo info;
        readonly string installDir;
        readonly Version current;
        readonly UpdateSchedule schedule = new UpdateSchedule();
        readonly UpdateNotice notice;
        readonly DateTime launched = DateTime.UtcNow;
        readonly Timer timer = new Timer { Interval = 60_000 };
        readonly HttpClient http;

        public ReleaseInfo Available { get; private set; }
        public Phases Phase { get; private set; } = Phases.Idle;
        public InstallStep Step { get; private set; }
        public string Target { get; private set; } = "";        // what's being installed: "v0.6.1"

        // From the tray app:
        public Action<string, string, ToolTipIcon> Notify = (_, __, ___) => { };
        public Action<Action> StopBridge = then => then();       // stop the bridge for the update, then call back
        public Action AbandonUpdate = () => { };                 // failed after the bridge was stopped: restart it
        public Action Exit = () => { };                          // the new copy has taken over
        public Action<Action> OnUi = action => action();

        public Updater(BuildInfo info, string installDir)
        {
            this.info = info;
            this.installDir = installDir;
            current = info.Version;
            ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;
            http = new HttpClient { Timeout = TimeSpan.FromMinutes(5) };
            http.DefaultRequestHeaders.UserAgent.ParseAdd($"LoupedeckBridge/{current}");
            // What earlier runs found and announced (Start at login relaunches the app every day).
            Available = ReleaseInfo.Restore(Prefs.GetString("AvailableRelease"), current);
            if (Available == null) Prefs.Delete("AvailableRelease");
            notice = new UpdateNotice(Version.Parse(Prefs.GetString("AnnouncedVersion")));
        }

        /// "Check for updates automatically" (on unless turned off).
        public bool Automatic
        {
            get => Prefs.GetBool("AutoUpdateCheck", true);
            set => Prefs.Set("AutoUpdateCheck", value ? 1 : 0);
        }

        /// The version kept by the last update, if it can be gone back to.
        public string PreviousVersion
        {
            get
            {
                var previous = Swap.PreviousDir(installDir);
                return Swap.GoBackProblem(previous) == null
                    ? BuildInfo.Load(Path.Combine(previous, BuildInfo.FileName))?.Version?.ToString() : null;
            }
        }

        public static string StepLabel(InstallStep step)
        {
            switch (step)
            {
                case InstallStep.Download: return "downloading";
                case InstallStep.Verify: return "checking it";
                case InstallStep.Unzip: return "unpacking";
                case InstallStep.StopBridge: return "stopping the bridge";
                default: return "handing over";
            }
        }

        // ---- checking -----------------------------------------------------------------------------------------
        public void Start()
        {
            timer.Tick += (_, __) => CheckIfDue();
            timer.Start();
        }

        void CheckIfDue()
        {
            if (Phase == Phases.Idle && schedule.ShouldCheck(DateTime.UtcNow, Prefs.GetDate("LastUpdateCheck"), Automatic,
                                                             info.IsDev, DateTime.UtcNow - launched))
                Check(manual: false);
        }

        /// "Check for updates now": says what it found, even "up to date".
        public void CheckNow()
        {
            if (Phase == Phases.Idle) Check(manual: true);
        }

        void Check(bool manual)
        {
            Phase = Phases.Checking;
            Task.Run(async () =>
            {
                try
                {
                    var request = new HttpRequestMessage(HttpMethod.Get, LatestUrl);
                    request.Headers.Accept.ParseAdd("application/vnd.github+json");
                    using (var cancel = new System.Threading.CancellationTokenSource(TimeSpan.FromSeconds(15)))
                    using (var response = await http.SendAsync(request, cancel.Token))
                    {
                        if (response.StatusCode != HttpStatusCode.OK) return ((ReleaseInfo)null, $"GitHub answered {(int)response.StatusCode}");
                        var release = ReleaseInfo.Parse(await response.Content.ReadAsStringAsync());
                        return (release, release == null ? "GitHub's answer had no Windows release in it" : null);
                    }
                }
                catch (Exception e) when (e is HttpRequestException || e is TaskCanceledException || e is WebException)
                {
                    return ((ReleaseInfo)null, e.Message);
                }
            }).ContinueWith(t => OnUi(() => Checked(t.Result.Item1, t.Result.Item2, manual)));
        }

        void Checked(ReleaseInfo release, string why, bool manual)
        {
            Phase = Phases.Idle;
            Prefs.SetDate("LastUpdateCheck", DateTime.UtcNow);     // a failed check also waits a day: no alert, no retry storm
            if (release == null)
            {
                Log.Write("update check failed: " + why);
                if (manual) Notify("Couldn't check for updates", why + ". Try again later.", ToolTipIcon.Warning);
                return;
            }
            if (!(release.Version > current))
            {
                Available = null;
                Prefs.Delete("AvailableRelease");
                Log.Write($"update check: up to date (v{current})");
                if (manual) Notify("LoupedeckBridge is up to date", $"v{current} is the newest version.", ToolTipIcon.Info);
                return;
            }
            Available = release;
            Prefs.Set("AvailableRelease", release.Saved());
            Log.Write($"update check: v{release.Version} is available (this is v{current})");
            var first = notice.Announce(release.Version, current);
            if (first && notice.LastAnnounced != null) Prefs.Set("AnnouncedVersion", notice.LastAnnounced.ToString());
            if (first || manual)
                Notify($"LoupedeckBridge v{release.Version} is available",
                       "Install it from the tray icon's menu: Update available.", ToolTipIcon.Info);
        }

        // ---- installing ---------------------------------------------------------------------------------------
        public void InstallAvailable()
        {
            if (Available == null || Phase != Phases.Idle) return;
            Begin("v" + Available.Version);
            var release = Available;
            Task.Run(() => Prepare(release)).ContinueWith(t => OnUi(() => AfterPrepare(t.Result)));
        }

        /// "Go back to the previous version": the copy kept by the last update, handed over the same way.
        public void GoBack()
        {
            var previous = PreviousVersion;
            if (previous == null || Phase != Phases.Idle) return;
            Begin("v" + previous);
            Step = InstallStep.Unzip;
            Task.Run(() => Swap.GoBack(installDir, Swap.CopyTree)).ContinueWith(t => OnUi(() => AfterPrepare(t.Result)));
        }

        void Begin(string target)
        {
            Phase = Phases.Installing;
            Target = target;
            Step = InstallStep.Download;
            Log.Write($"installing {target}");
        }

        void AfterPrepare(string problem)
        {
            if (problem != null)
            {
                Failed(problem, bridgeStopped: false);
                return;
            }
            Step = InstallStep.StopBridge;
            StopBridge(HandOver);
        }

        /// Everything up to the hand-over that can run in the background: download, check, unpack into <install>.new.
        /// Returns null, or the failed step and why.
        string Prepare(ReleaseInfo release)
        {
            var temp = Path.Combine(Path.GetTempPath(), "LoupedeckBridge-update-" + release.Version);
            try
            {
                if (Directory.Exists(temp)) Directory.Delete(temp, recursive: true);
                Directory.CreateDirectory(temp);
                var zip = Path.Combine(temp, ReleaseInfo.AssetName(release.Version));
                string hash;
                Step = InstallStep.Download;
                try
                {
                    hash = Fetch(release.Zip, zip, Download.Limit);
                    Fetch(release.Sha256, zip + ".sha256", 65_536);
                    Fetch(release.Signature, zip + ".p7s", 65_536);
                }
                catch (Exception e) when (e is HttpRequestException || e is TaskCanceledException || e is WebException
                                          || e is IOException || e is DownloadTooLargeException || e is AggregateException)
                {
                    return $"{StepLabel(InstallStep.Download)}: {(e as AggregateException)?.InnerException?.Message ?? e.Message}";
                }

                Step = InstallStep.Verify;
                var expected = File.ReadAllText(zip + ".sha256", Encoding.UTF8).Trim().Split(' ', '\t').FirstOrDefault() ?? "";
                var shaOK = string.Equals(hash, expected, StringComparison.OrdinalIgnoreCase);
                var signature = shaOK ? Signature.Problem(File.ReadAllBytes(zip), File.ReadAllBytes(zip + ".p7s"), info.SignerSha256) : null;
                if (!shaOK || signature != null)
                    return Updates.InstallProblem(null, current, shaOK, signatureOK: false, allowOlder: false)
                           + (signature != null ? $" ({signature})" : "");
                BuildInfo found;
                try
                {
                    using (var archive = ZipFile.OpenRead(zip))
                    {
                        var layout = Updates.ZipLayoutProblem(archive.Entries.Select(e => e.FullName));
                        if (layout != null) return layout;
                        using (var reader = new StreamReader(archive.GetEntry($"{Updates.Folder}/{BuildInfo.FileName}").Open(), Encoding.UTF8))
                            found = BuildInfo.Parse(reader.ReadToEnd());
                    }
                }
                catch (InvalidDataException e) { return "it isn't a valid zip: " + e.Message; }
                var problem = Updates.InstallProblem(found, current, shaOK: true, signatureOK: true, allowOlder: false);
                if (problem != null) return problem;
                if (found.Version != release.Version) return $"it holds v{found.Version}, not v{release.Version}";

                Step = InstallStep.Unzip;
                var unzip = installDir + ".unzip";
                var target = Swap.NewDir(installDir);
                if (Directory.Exists(unzip)) Directory.Delete(unzip, recursive: true);
                if (Directory.Exists(target)) Directory.Delete(target, recursive: true);
                ZipFile.ExtractToDirectory(zip, unzip);           // refuses entries outside the folder, too
                Directory.Move(Path.Combine(unzip, Updates.Folder), target);
                Directory.Delete(unzip, recursive: true);
                return null;
            }
            catch (Exception e) when (e is IOException || e is UnauthorizedAccessException || e is InvalidDataException)
            {
                return $"{StepLabel(Step)}: {e.Message}";
            }
            finally
            {
                try { if (Directory.Exists(temp)) Directory.Delete(temp, recursive: true); } catch (IOException) { }
            }
        }

        string Fetch(Uri url, string path, long limit)
        {
            using (var response = http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead).GetAwaiter().GetResult())
            {
                response.EnsureSuccessStatusCode();
                using (var body = response.Content.ReadAsStreamAsync().GetAwaiter().GetResult())
                using (var file = File.Create(path))
                    return Download.CopyCapped(body, file, limit);
            }
        }

        /// The bridge has stopped: start the new copy, which finishes the swap once this app has exited.
        void HandOver()
        {
            Step = InstallStep.HandOver;
            var exe = Path.Combine(Swap.NewDir(installDir), "LoupedeckBridge.exe");
            try
            {
                var args = new[] { "--finish-update", Process.GetCurrentProcess().Id.ToString(), installDir };
                Process.Start(new ProcessStartInfo(exe, CommandLine.Join(args)) { UseShellExecute = true });
                Log.Write($"handed over to {Target}; quitting");
                Exit();
            }
            catch (Exception e) when (e is System.ComponentModel.Win32Exception || e is FileNotFoundException)
            {
                Failed($"{StepLabel(InstallStep.HandOver)}: {e.Message}", bridgeStopped: true);
            }
        }

        void Failed(string why, bool bridgeStopped)
        {
            Log.Write($"couldn't install {Target}: {why}", "WARNING");
            Notify($"Couldn't install {Target}", $"{why}. v{current} keeps running.", ToolTipIcon.Warning);
            Phase = Phases.Idle;
            if (bridgeStopped) AbandonUpdate();
        }
    }
}
