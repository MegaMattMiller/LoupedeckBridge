// LoupedeckBridge.exe: a tray app that runs the Python bridge as a child process (milestone 7), the Windows twin of
// macos/launcher/main.swift. The dev build runs this repo's code with its .venv; a release carries its own Python and
// code (RuntimePaths in Policies.cs, from LoupedeckBridge.json next to the exe).
//
//   LoupedeckBridge.exe [bridge arguments…]     the tray app (a second copy exits at once)
//   LoupedeckBridge.exe --quit                  ask the running copy to quit as if from its menu, and wait (≤ 10 s):
//                                               exit 0 when it's gone (or wasn't running), 1 if it's still there
//   LoupedeckBridge.exe --login on|off|status   Start at login from the command line (tools/bridgectl.ps1 login)

using System;
using System.IO;
using System.Linq;
using System.Threading;
using System.Windows.Forms;

namespace LoupedeckBridge
{
    static class Program
    {
        [STAThread]
        static int Main(string[] args)
        {
            var exe = Application.ExecutablePath;
            var appDir = Path.GetDirectoryName(exe);
            var info = BuildInfo.Load(Path.Combine(appDir, BuildInfo.FileName));
            if (info == null)
            {
                Log.Write($"{BuildInfo.FileName} is missing or unreadable next to {exe}; rebuild or reinstall the app", "ERROR");
                return 2;
            }
            if (args.Length > 0 && args[0] == "--login") return LoginItem.Command(info.Name, exe, args.Length > 1 ? args[1] : "status");
            if (args.Length > 0 && args[0] == "--quit") return QuitRunningCopy(info);
            if (args.Length > 0 && args[0] == "--check-signature") return CheckSignature(info, args);

            var paths = RuntimePaths.Resolve(info, appDir);
            if (paths == null)
            {
                Log.Write($"{BuildInfo.FileName} doesn't say which Python to run (runtime / repo); rebuild the app", "ERROR");
                return 2;
            }
            using (var mutex = new Mutex(true, info.MutexName, out var first))
            {
                if (!first) return 0;                     // already in the tray: quietly
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new TrayApp(info, paths, exe, args.ToArray()));
                GC.KeepAlive(mutex);
            }
            return 0;
        }

        /// `--check-signature FILE [--pinned SHA256]`: would the updater accept FILE (signed, in FILE.p7s, with this
        /// build's pinned release key, or the one given)? Exit 0 yes, 1 no: the release workflow's and CI's last check.
        static int CheckSignature(BuildInfo info, string[] args)
        {
            if (args.Length != 2 && !(args.Length == 4 && args[2] == "--pinned"))
            {
                Console.Error.WriteLine("usage: LoupedeckBridge.exe --check-signature FILE [--pinned SHA256]");
                return 2;
            }
            string problem;
            try
            {
                problem = Signature.Problem(File.ReadAllBytes(args[1]), File.ReadAllBytes(args[1] + ".p7s"),
                                            args.Length == 4 ? args[3] : info.SignerSha256);
            }
            catch (Exception e) when (e is IOException || e is UnauthorizedAccessException)
            {
                problem = "couldn't read it or its signature: " + e.Message;
            }
            Console.WriteLine(problem == null ? "ok: signed with the pinned LoupedeckBridge release key" : "refused: " + problem);
            return problem == null ? 0 : 1;
        }

        static int QuitRunningCopy(BuildInfo info)
        {
            if (!EventWaitHandle.TryOpenExisting(info.QuitEventName, out var quit))
            {
                Console.WriteLine("not running");
                return 0;
            }
            using (quit) quit.Set();
            for (var i = 0; i < 100; i++)
            {
                if (!Mutex.TryOpenExisting(info.MutexName, out var mutex))
                {
                    Console.WriteLine("stopped");
                    return 0;
                }
                mutex.Dispose();
                Thread.Sleep(100);
            }
            Console.WriteLine("still running after 10 s");
            return 1;
        }
    }
}
