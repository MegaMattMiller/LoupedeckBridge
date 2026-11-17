// LoupedeckBridge.app: a menu-bar app that runs this repo's Python bridge as a child process.
//
// macOS grants the Accessibility (keyboard) permission to the *app* that started a process, so the bridge
// runs as a child of this app (posix_spawn, not exec) rather than of Terminal or the Claude app. The
// Python code is read from the repo at run time: editing it never needs a rebuild.
//
//   LoupedeckBridge [bridge arguments…]    the menu-bar app (milestone 5)
//   LoupedeckBridge --login on|off|status  Start at login from the command line (tools/bridgectl login)
//   LoupedeckBridge --check-permission     one-shot permission check: no menu-bar icon

import AppKit

let arguments = Array(CommandLine.arguments.dropFirst())

if arguments.first == "--login" {
    exit(LoginItem.command(arguments.count > 1 ? arguments[1] : "status"))
}

let info = Bundle.main.infoDictionary ?? [:]
guard let paths = RuntimePaths.resolve(info: info, bundle: Bundle.main.bundlePath) else {
    BridgeProcess.log("Info.plist doesn't say which Python to run (LBRuntime / LBRepoPath); rebuild the app",
                      level: "ERROR")
    exit(2)
}

if arguments.contains("--check-permission") {
    exit(BridgeProcess.runOnce(paths: paths, arguments: arguments))
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)        // menu-bar only: no Dock icon (LSUIElement too)
let controller = AppController(paths: paths, arguments: arguments, info: info)   // installs signal handlers first
app.delegate = controller
app.run()
