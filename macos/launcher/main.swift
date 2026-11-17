// LoupedeckBridge.app: a menu-bar app that runs the Python bridge as a child process.
//
// macOS grants the Accessibility (keyboard) permission to the *app* that started a process, so the bridge
// runs as a child of this app (posix_spawn, not exec) rather than of Terminal or the Claude app. The dev
// build runs this repo's code with its .venv (editing it never needs a rebuild); a release carries its own
// Python and code (RuntimePaths in Policies.swift).
//
//   LoupedeckBridge [bridge arguments…]    the menu-bar app (milestone 5)
//   LoupedeckBridge --login on|off|status  Start at login from the command line (tools/bridgectl login)
//   LoupedeckBridge --check-permission     one-shot permission check: no menu-bar icon
//   LoupedeckBridge --check-signature APP  would the updater accept APP? (signed with this build's pinned
//                                          release key; exit 0 yes, 1 no) — the release workflow's last check

import AppKit

let arguments = Array(CommandLine.arguments.dropFirst())

if arguments.first == "--login" {
    exit(LoginItem.command(arguments.count > 1 ? arguments[1] : "status"))
}

let info = Bundle.main.infoDictionary ?? [:]

if arguments.first == "--check-signature" {
    guard arguments.count == 2 else {
        fputs("usage: LoupedeckBridge --check-signature APP\n", stderr)
        exit(2)
    }
    let problem = Signature.problem(app: URL(fileURLWithPath: arguments[1]), identifier: releaseBundleID,
                                    pinnedSHA256: info["LBSignerSHA256"] as? String ?? "")
    print(problem.map { "refused: \($0)" } ?? "ok: signed with the pinned LoupedeckBridge release key")
    exit(problem == nil ? 0 : 1)
}
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
