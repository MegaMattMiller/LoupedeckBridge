// The menu-bar icon and menu, the alerts, and Start at login (milestone 5).
// The rules for when to alert and when to restart live in Policies.swift (tested separately).

import AppKit
import ServiceManagement
import UserNotifications

/// Start at login, through macOS's own Login Items (System Settings → General → Login Items).
/// Off until the user turns it on; nothing registers itself.
enum LoginItem {
    static var isOn: Bool { SMAppService.mainApp.status == .enabled }

    static var state: String {
        switch SMAppService.mainApp.status {
        case .enabled: return "on"
        case .requiresApproval: return "waiting for approval in System Settings → General → Login Items"
        default: return "off"
        }
    }

    static func set(_ on: Bool) throws {
        if on {
            try SMAppService.mainApp.register()
        } else if SMAppService.mainApp.status != .notRegistered && SMAppService.mainApp.status != .notFound {
            try SMAppService.mainApp.unregister()
        }
    }

    /// `--login on|off|status` (tools/bridgectl login): prints the state; 0 = done, 1 = failed, 2 = usage.
    static func command(_ arg: String) -> Int32 {
        do {
            switch arg {
            case "on": try set(true)
            case "off": try set(false)
            case "status": break
            default:
                fputs("usage: LoupedeckBridge --login on|off|status\n", stderr)
                return 2
            }
        } catch {
            fputs("couldn't change Start at login: \(error.localizedDescription)\n", stderr)
            return 1
        }
        print("Start at login: \(state)")
        return 0
    }
}

final class AppController: NSObject, NSApplicationDelegate, NSMenuDelegate, UNUserNotificationCenterDelegate {
    private let paths: RuntimePaths
    private let arguments: [String]
    private let title: String                 // "LoupedeckBridge v0.5.0", or "LoupedeckBridge Dev (repo)"
    private var bridge: BridgeProcess?
    private var statusItem: NSStatusItem?
    private var current: BridgeStatus?        // the bridge's last status line
    private var supervisor = BridgeSupervisor()   // start / exit / restart / quit decisions (Policies.swift)
    private var alerts = AlertPolicy()
    private var signalSources: [DispatchSourceSignal] = []
    private var timer: Timer?

    private func now() -> Double { ProcessInfo.processInfo.systemUptime }

    init(paths: RuntimePaths, arguments: [String], info: [String: Any]) {
        self.paths = paths
        self.arguments = arguments
        let version = info["LBVersion"] as? String ?? "?"
        self.title = (info["LBIsDev"] as? Bool ?? false) ? "LoupedeckBridge Dev (repo, v\(version))"
                                                          : "LoupedeckBridge v\(version)"
        super.init()
        // Before the bridge is spawned, so an early stop request can't leave it running without us.
        for sig in [SIGTERM, SIGINT, SIGHUP] {
            signal(sig, SIG_IGN)
            let source = DispatchSource.makeSignalSource(signal: sig, queue: .main)
            source.setEventHandler { [weak self] in self?.quit() }
            source.resume()
            signalSources.append(source)
        }
    }

    // ---- lifecycle ----------------------------------------------------------
    func applicationDidFinishLaunching(_ notification: Notification) {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        let menu = NSMenu()
        menu.delegate = self
        item.menu = menu
        statusItem = item

        let center = UNUserNotificationCenter.current()
        center.delegate = self
        center.requestAuthorization(options: [.alert, .sound]) { granted, error in
            if !granted {
                BridgeProcess.log("alerts are off: notifications aren't allowed (\(error?.localizedDescription ?? "the user said no"))")
            }
        }
        NSWorkspace.shared.notificationCenter.addObserver(self, selector: #selector(didWake),
                                                          name: NSWorkspace.didWakeNotification, object: nil)
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            guard let self = self else { return }
            self.post(self.alerts.tick(at: self.now()))
        }
        perform(supervisor.start())
    }

    /// Carries out the supervisor's decisions.
    private func perform(_ actions: [SupervisorAction]) {
        for action in actions {
            switch action {
            case .spawn:
                spawnBridge()
            case .stopBridge:
                bridge?.stop()                     // bridgeExited then finishes the quit
                DispatchQueue.main.asyncAfter(deadline: .now() + 7) { NSApp.terminate(nil) }   // a last resort
            case .releaseKeys:
                BridgeProcess.releaseKeys()        // its own clean-up may not have run
            case .alert(let alert):
                post([alert])
            case .scheduleRestart(let token, let delay):
                DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
                    guard let self = self else { return }
                    self.perform(self.supervisor.restartTimerFired(token: token))
                }
            case .terminateApp:
                NSApp.terminate(nil)
            }
        }
        updateIcon()
    }

    private func spawnBridge() {
        guard !(bridge?.running ?? false) else { return }   // never two bridges
        alerts.bridgeRestarted()
        let process = BridgeProcess(python: paths.python, workdir: paths.workdir, arguments: arguments)
        process.onStatus = { [weak self] status in self?.received(status) }
        process.onExit = { [weak self] code in self?.bridgeExited(code) }
        bridge = process
        current = nil
        if process.start() {
            BridgeProcess.log("bridge started (pid \(process.pid))")
        } else {
            perform(supervisor.spawnFailed())
        }
    }

    private func received(_ status: BridgeStatus) {
        guard supervisor.acceptsStatus else { return }      // a bridge on its way out
        current = status
        post(alerts.status(status, at: now()))
        updateIcon()
    }

    private func bridgeExited(_ code: Int32) {
        alerts.bridgeStopped()                     // its shutdown isn't the Loupedeck being unplugged
        current = nil
        let actions = supervisor.exited(code: code, at: now())
        if code == RestartPolicy.alreadyRunning {
            BridgeProcess.log("another LoupedeckBridge is already running; this one quits")
        } else {
            let restarting = actions.contains { if case .scheduleRestart = $0 { return true }; return false }
            BridgeProcess.log("the bridge stopped (exit code \(code))" + (restarting ? "; restarting in 5 s" : ""),
                              level: code == 0 ? "INFO" : "ERROR")
        }
        perform(actions)
    }

    @objc private func didWake() {
        alerts.didWake(at: now())
    }

    // ---- the icon -----------------------------------------------------------
    private var allGood: Bool {
        guard supervisor.acceptsStatus, let s = current else { return false }
        return s.loupedeck && s.lightroom && s.keys != "missing"
    }

    private func updateIcon() {
        guard let button = statusItem?.button else { return }
        let good = allGood
        let image = NSImage(systemSymbolName: good ? "slider.horizontal.3" : "exclamationmark.triangle",
                            accessibilityDescription: good ? "LoupedeckBridge" : "LoupedeckBridge needs attention")
        image?.isTemplate = true
        button.image = image
        button.title = image == nil ? "LB" : ""
        button.toolTip = good ? "LoupedeckBridge: all good" : "LoupedeckBridge: \(problem)"
    }

    private var problem: String {
        if supervisor.isStopped { return "the bridge has stopped" }
        guard let s = current else { return "starting…" }
        if !s.loupedeck { return "the Loupedeck isn't connected" }
        if !s.lightroom { return "Lightroom isn't connected" }
        if s.keys == "missing" { return "keyboard keys need permission" }
        return "all good"
    }

    // ---- the menu -----------------------------------------------------------
    func menuNeedsUpdate(_ menu: NSMenu) {
        menu.removeAllItems()
        menu.addItem(info(title, ok: nil))
        menu.addItem(.separator())
        if supervisor.isStopped {
            menu.addItem(info("The bridge has stopped", ok: false))
            menu.addItem(action("Restart bridge", #selector(restartFromMenu)))
            menu.addItem(action("Open log", #selector(openLog)))
        } else if let s = current {
            menu.addItem(info("Loupedeck: " + (s.loupedeck ? "connected" : "not connected"), ok: s.loupedeck))
            menu.addItem(info("Lightroom: " + (s.lightroom ? "connected" : "not connected"), ok: s.lightroom))
            let keys = ["allowed": "allowed", "missing": "need permission"][s.keys] ?? "not available here"
            menu.addItem(info("Keyboard keys: " + keys, ok: s.keys != "missing"))
            menu.addItem(info("Five buttons: " + s.five_mode.capitalized, ok: nil))
        } else {
            menu.addItem(info("Starting…", ok: nil))
        }
        menu.addItem(.separator())
        let settings = action("Open settings…", #selector(openSettings))
        settings.isEnabled = current?.settings_url != nil
        menu.addItem(settings)
        let login = action("Start at login", #selector(toggleLogin))
        login.state = LoginItem.isOn ? .on : .off
        menu.addItem(login)
        menu.addItem(.separator())
        menu.addItem(action("Quit LoupedeckBridge", #selector(quitFromMenu)))
    }

    /// A status line: a coloured dot (green / orange) or none, and text that can't be clicked.
    private func info(_ title: String, ok: Bool?) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        item.isEnabled = false
        if let ok = ok, let dot = NSImage(systemSymbolName: "circle.fill", accessibilityDescription: ok ? "OK" : "Problem") {
            item.image = dot.withSymbolConfiguration(.init(paletteColors: [ok ? .systemGreen : .systemOrange]))
        }
        return item
    }

    private func action(_ title: String, _ selector: Selector) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: selector, keyEquivalent: "")
        item.target = self
        return item
    }

    @objc private func openSettings() {
        if let url = current?.settings_url.flatMap(URL.init(string:)) { NSWorkspace.shared.open(url) }
    }

    @objc private func openLog() {
        NSWorkspace.shared.open(BridgeProcess.logURL)
    }

    @objc private func toggleLogin() {
        do {
            try LoginItem.set(!LoginItem.isOn)
            BridgeProcess.log("Start at login: \(LoginItem.state)")
        } catch {
            let alert = NSAlert()
            alert.messageText = "Couldn't change Start at login"
            alert.informativeText = error.localizedDescription
            alert.runModal()
        }
    }

    @objc private func restartFromMenu() {
        perform(supervisor.manualRestart())        // nothing if it's already running again
    }

    @objc private func quitFromMenu() {
        quit()
    }

    /// Quit: stop the bridge (it lets go of held keys; if it has to be forced, the app does), then exit.
    /// Also on SIGTERM / SIGINT / SIGHUP.
    private func quit() {
        if supervisor.state != .quitting { BridgeProcess.log("quitting") }
        perform(supervisor.quit(bridgeRunning: bridge?.running ?? false))
    }

    // ---- alerts -------------------------------------------------------------
    private func post(_ list: [Alert]) {
        for alert in list {
            let content = UNMutableNotificationContent()
            switch alert {
            case .disconnected:
                content.title = "Loupedeck disconnected"
                content.body = "Check its USB cable or dongle. The controls work again as soon as it's back."
            case .back:
                content.title = "Loupedeck is back"
                content.body = "Its controls work again."
            case .keysMissing:
                content.title = "Keyboard keys need permission"
                content.body = "Allow LoupedeckBridge in System Settings → Privacy & Security → Accessibility."
            case .bridgeStopped(let willRestart):
                content.title = "LoupedeckBridge stopped"
                content.body = willRestart
                    ? "It hit an error and is restarting. Details are in its log."
                    : "It stopped after repeated errors. Use the menu-bar icon to restart it or open the log."
            }
            let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
            UNUserNotificationCenter.current().add(request) { error in
                if let error = error { BridgeProcess.log("couldn't show an alert: \(error.localizedDescription)") }
            }
        }
    }

    // Show alerts as banners even if macOS thinks the app is in front.
    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound])
    }
}
