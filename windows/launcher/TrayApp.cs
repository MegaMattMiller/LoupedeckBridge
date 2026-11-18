// The tray icon, its menu and alerts, and the bridge's supervision: the Mac app's StatusMenu.swift. The decisions
// are in Policies.cs (tested); this file carries them out.

using System;
using System.Diagnostics;
using System.Globalization;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

namespace LoupedeckBridge
{
    sealed class TrayApp : ApplicationContext
    {
        readonly BuildInfo info;
        readonly RuntimePaths paths;
        readonly string exe;
        readonly string appDir;
        readonly string[] bridgeArguments;
        readonly Updater updater;                        // release builds only
        Action pendingSwap;                              // what an update does once the bridge has stopped
        readonly NotifyIcon icon;
        readonly ContextMenuStrip menu = new ContextMenuStrip();
        readonly Control ui = new Control();             // marshals bridge events onto this thread
        readonly Stopwatch clock = Stopwatch.StartNew();
        readonly System.Windows.Forms.Timer ticker = new System.Windows.Forms.Timer { Interval = 1000 };
        readonly BridgeSupervisor supervisor = new BridgeSupervisor();
        readonly AlertPolicy alerts = new AlertPolicy();
        readonly EventWaitHandle quitEvent;
        readonly RegisteredWaitHandle quitWait;
        BridgeProcess bridge;
        BridgeStatus current;
        bool exiting;

        double Now => clock.Elapsed.TotalSeconds;

        public TrayApp(BuildInfo info, RuntimePaths paths, string exe, string appDir, string[] bridgeArguments)
        {
            this.info = info;
            this.paths = paths;
            this.exe = exe;
            this.appDir = appDir;
            this.bridgeArguments = bridgeArguments;
            ui.CreateControl();
            _ = ui.Handle;
            icon = new NotifyIcon { Icon = Icons.Attention, Text = TrayText.Tooltip(info.Name, "starting…"),
                                    ContextMenuStrip = menu, Visible = true };
            menu.Opening += (_, __) => BuildMenu();
            ticker.Tick += (_, __) => Post(alerts.Tick(Now));
            ticker.Start();
            SystemEvents.PowerModeChanged += OnPowerModeChanged;
            SystemEvents.SessionEnding += OnSessionEnding;
            // `LoupedeckBridge.exe --quit` (tools/bridgectl.ps1 stop, tools/install.ps1) sets this event.
            quitEvent = new EventWaitHandle(false, EventResetMode.AutoReset, info.QuitEventName);
            quitWait = ThreadPool.RegisterWaitForSingleObject(quitEvent, (_, __) => OnUi(Quit), null, Timeout.Infinite, false);
            Log.Write($"{info.Name} {(info.IsDev ? "(repo)" : "v" + info.Version)} started; bridge: {paths}");
            if (!info.IsDev && info.Version != null)
            {
                updater = new Updater(info, appDir)
                {
                    Notify = Notify,
                    StopBridge = then => { pendingSwap = then; Perform(supervisor.StopForUpdate(bridge?.Running ?? false)); },
                    AbandonUpdate = () => Perform(supervisor.UpdateAbandoned()),
                    Exit = ExitApp,
                    OnUi = OnUi,
                };
                Swap.CleanUp(appDir);                        // the .new folder the last update came from
                var failed = Prefs.GetString("UpdateFailed");
                if (failed != null)
                {
                    Prefs.Delete("UpdateFailed");
                    Notify("The update didn't finish", failed + $". v{info.Version} is running.", ToolTipIcon.Warning);
                }
                updater.Start();
            }
            Perform(supervisor.Start());
        }

        void OnUi(Action action)
        {
            try { ui.BeginInvoke(action); }
            catch (Exception e) when (e is InvalidOperationException || e is ObjectDisposedException) { }
        }

        // ---- the bridge -------------------------------------------------------------------------------------
        void Perform(System.Collections.Generic.List<SupervisorAction> actions)
        {
            foreach (var action in actions)
            {
                switch (action.Kind)
                {
                    case SupervisorAction.Kinds.Spawn: SpawnBridge(); break;
                    case SupervisorAction.Kinds.StopBridge: bridge?.Stop(); break;
                    case SupervisorAction.Kinds.ReleaseKeys:
                        Log.Write("the bridge ended without letting go of keys; releasing them");
                        KeyRelease.ReleaseAll();
                        break;
                    case SupervisorAction.Kinds.Alert: Post(new[] { action.AlertToShow }); break;
                    case SupervisorAction.Kinds.ScheduleRestart:
                        var token = action.Token;
                        var timer = new System.Windows.Forms.Timer { Interval = (int)(action.After * 1000) };
                        timer.Tick += (_, __) =>
                        {
                            timer.Stop();
                            timer.Dispose();
                            Perform(supervisor.RestartTimerFired(token));
                        };
                        timer.Start();
                        break;
                    case SupervisorAction.Kinds.TerminateApp: ExitApp(); break;
                    case SupervisorAction.Kinds.ReadyToSwap:            // the bridge has stopped for an update
                        var then = pendingSwap;
                        pendingSwap = null;
                        then?.Invoke();
                        break;
                }
            }
            UpdateIcon();
        }

        void SpawnBridge()
        {
            alerts.BridgeRestarted();
            current = null;
            var next = new BridgeProcess();
            next.StatusReceived += status => OnUi(() => Received(next, status));
            next.Exited += code => OnUi(() => BridgeExited(next, code));
            bridge = next;
            if (!next.Start(paths, bridgeArguments)) Perform(supervisor.SpawnFailed());
        }

        void Received(BridgeProcess from, BridgeStatus status)
        {
            if (from != bridge || !supervisor.AcceptsStatus) return;
            current = status;
            Post(alerts.Status(status, Now));
            UpdateIcon();
        }

        void BridgeExited(BridgeProcess from, int code)
        {
            if (from != bridge) return;
            Log.Write($"the bridge exited ({code})", code == 0 || code == RestartPolicy.AlreadyRunning ? "INFO" : "WARNING");
            alerts.BridgeStopped();
            current = null;
            Perform(supervisor.Exited(code, Now));
        }

        void OnPowerModeChanged(object sender, PowerModeChangedEventArgs e)
        {
            if (e.Mode == PowerModes.Resume) OnUi(() => alerts.DidWake(Now));
        }

        void OnSessionEnding(object sender, SessionEndingEventArgs e) => bridge?.Stop();   // signing out or shutting down

        // ---- the icon and its menu --------------------------------------------------------------------------
        bool AllGood => supervisor.AcceptsStatus && current != null && current.Loupedeck && current.Lightroom;

        void UpdateIcon()
        {
            if (icon == null || exiting) return;
            var good = AllGood;
            icon.Icon = good ? Icons.Good : Icons.Attention;
            icon.Text = TrayText.Tooltip(info.Name, good ? "all good" : TrayText.Problem(supervisor.State, supervisor.IsStopped,
                                                                                          supervisor.AcceptsStatus ? current : null));
        }

        void BuildMenu()
        {
            menu.Items.Clear();
            menu.Items.Add(Info(info.IsDev ? "LoupedeckBridge Dev (repo)" : $"LoupedeckBridge v{info.Version}", null));
            menu.Items.Add(new ToolStripSeparator());
            if (supervisor.State == BridgeSupervisor.States.Updating)
            {
                menu.Items.Add(Info("The bridge is stopped for the update", null));
            }
            else if (supervisor.IsStopped)
            {
                menu.Items.Add(Info("The bridge has stopped", false));
                menu.Items.Add(Action("Restart bridge", () => Perform(supervisor.ManualRestart())));
                menu.Items.Add(Action("Open log", OpenLog));
                // An update that keeps failing (the restart budget is used up) can be undone.
                var previous = supervisor.State == BridgeSupervisor.States.Stopped ? updater?.PreviousVersion : null;
                if (previous != null) menu.Items.Add(Action($"Go back to the previous version (v{previous})…", () => updater.GoBack()));
            }
            else if (current != null)
            {
                menu.Items.Add(current.LoupedeckBusy ? Info("Loupedeck: in use by another program", false)
                                                     : Info("Loupedeck: " + (current.Loupedeck ? "connected" : "not connected"), current.Loupedeck));
                menu.Items.Add(Info("Lightroom: " + (current.Lightroom ? "connected" : "not connected"), current.Lightroom));
                var mode = string.IsNullOrEmpty(current.FiveMode) ? "?"
                    : CultureInfo.InvariantCulture.TextInfo.ToTitleCase(current.FiveMode);
                menu.Items.Add(Info("Five buttons: " + mode, null));
            }
            else
            {
                menu.Items.Add(Info("Starting…", null));
            }
            menu.Items.Add(new ToolStripSeparator());
            var settings = Action("Open settings…", OpenSettings);
            settings.Enabled = current?.SettingsUrl != null;
            menu.Items.Add(settings);
            var login = Action("Start at login", ToggleLogin);
            login.Checked = LoginItem.IsOn(info.Name);
            menu.Items.Add(login);
            if (updater != null)
            {
                menu.Items.Add(new ToolStripSeparator());
                if (updater.Phase == Updater.Phases.Installing)
                    menu.Items.Add(Info($"Installing {updater.Target}: {Updates.StepLabel(updater.Step)}…", null));
                else if (updater.Available != null)
                    menu.Items.Add(Action($"Update available: v{updater.Available.Version} – Install…", () => updater.InstallAvailable()));
                var check = Action(updater.Phase == Updater.Phases.Checking ? "Checking for updates…" : "Check for updates now",
                                   () => updater.CheckNow());
                check.Enabled = updater.Phase == Updater.Phases.Idle;
                menu.Items.Add(check);
                var automatic = Action("Check for updates automatically", () => updater.Automatic = !updater.Automatic);
                automatic.Checked = updater.Automatic;
                menu.Items.Add(automatic);
            }
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add(Action("Quit " + info.Name, Quit));
        }

        static ToolStripMenuItem Info(string text, bool? ok)
        {
            var item = new ToolStripMenuItem(text) { Enabled = false };
            if (ok.HasValue) item.Image = ok.Value ? Icons.GreenDot : Icons.OrangeDot;
            return item;
        }

        static ToolStripMenuItem Action(string text, Action action)
        {
            var item = new ToolStripMenuItem(text);
            item.Click += (_, __) => action();
            return item;
        }

        void OpenSettings()
        {
            var url = current?.SettingsUrl;
            if (url != null && url.StartsWith("http://127.0.0.1:", StringComparison.Ordinal)) Open(url);
        }

        void OpenLog() => Open(Log.FilePath);

        static void Open(string target)
        {
            try { Process.Start(new ProcessStartInfo(target) { UseShellExecute = true }); }
            catch (Exception e) when (e is System.ComponentModel.Win32Exception || e is System.IO.FileNotFoundException)
            {
                Log.Write($"couldn't open {target}: {e.Message}", "WARNING");
            }
        }

        void ToggleLogin()
        {
            try
            {
                var on = !LoginItem.IsOn(info.Name);
                LoginItem.Set(info.Name, exe, on);
                Log.Write("Start at login: " + (on ? "on" : "off"));
            }
            catch (Exception e) when (e is UnauthorizedAccessException || e is System.Security.SecurityException
                                      || e is System.IO.IOException)
            {
                MessageBox.Show("Couldn't change Start at login: " + e.Message, info.Name, MessageBoxButtons.OK,
                                MessageBoxIcon.Warning);
            }
        }

        // ---- quitting ---------------------------------------------------------------------------------------
        /// Quit: stop the bridge (it lets go of held keys; if it has to be forced, this app does), then exit.
        void Quit()
        {
            if (supervisor.State != BridgeSupervisor.States.Quitting) Log.Write("quitting");
            Perform(supervisor.Quit(bridge?.Running ?? false));
        }

        void ExitApp()
        {
            if (exiting) return;
            exiting = true;
            ticker.Stop();
            SystemEvents.PowerModeChanged -= OnPowerModeChanged;
            SystemEvents.SessionEnding -= OnSessionEnding;
            quitWait.Unregister(null);
            quitEvent.Dispose();
            icon.Visible = false;
            icon.Dispose();
            ExitThread();
        }

        // ---- alerts -----------------------------------------------------------------------------------------
        void Post(System.Collections.Generic.IEnumerable<Alert> list)
        {
            foreach (var alert in list)
            {
                switch (alert.Kind)
                {
                    case Alert.Kinds.Disconnected:
                        Notify("Loupedeck disconnected", "Check its USB cable or dongle. The controls work again as soon as it's back.",
                               ToolTipIcon.Warning);
                        break;
                    case Alert.Kinds.Back:
                        Notify("Loupedeck is back", "Its controls work again.", ToolTipIcon.Info);
                        break;
                    case Alert.Kinds.BridgeStopped:
                        Notify(info.Name + " stopped", alert.WillRestart
                            ? "It hit an error and is restarting. Details are in its log."
                            : "It stopped after repeated errors. Use the tray icon to restart it or open the log.", ToolTipIcon.Error);
                        break;
                }
            }
        }

        void Notify(string title, string body, ToolTipIcon kind)
        {
            Log.Write("alert: " + title);
            icon.ShowBalloonTip(10000, title, body, kind);
        }
    }
}
