// Putting a new version in place, and going back (milestone 7). A running program can't be moved or deleted on
// Windows (the Mac app moves itself to the Trash), so an update is finished by the *new* copy, started from
// <install>.new after the old one has exited (`LoupedeckBridge.exe --finish-update`):
//   1. the install folder is renamed to <install>.previous (an older .previous waits as <install>.older meanwhile)
//   2. the new copy copies itself into the install folder
// If either step fails, the partial copy is removed and .previous and .older are renamed back, so there's always a
// working version and the version Go back returns to. Only then is .older deleted.
// "Go back to the previous version" copies .previous into .new and hands over the same way. The install path never
// changes, so Start at login and the Start menu entry keep working.

using System;
using System.IO;
using System.Threading;

namespace LoupedeckBridge
{
    static class Swap
    {
        public static string PreviousDir(string installDir) => installDir.TrimEnd('\\', '/') + ".previous";
        public static string NewDir(string installDir) => installDir.TrimEnd('\\', '/') + ".new";
        public static string OlderDir(string installDir) => installDir.TrimEnd('\\', '/') + ".older";

        /// The folder that holds every copy of the app (the install folder, .new, .previous, .older): where the app
        /// stands. Windows won't rename a folder that is a process's current folder, and the programs a process starts
        /// (a browser, Notepad) inherit its current folder (final review, milestone 7).
        public static string OutsideFolder(string appDir) => Path.GetDirectoryName(Path.GetFullPath(appDir).TrimEnd('\\', '/'));

        /// Is `appDir` the .new folder of `installDir`? `--finish-update` only ever runs from there (security review:
        /// a wrong argument must never move or delete some other folder).
        public static bool IsNewDirOf(string appDir, string installDir)
        {
            try
            {
                string Full(string path) => Path.GetFullPath(path).TrimEnd('\\', '/');
                return string.Equals(Full(appDir), Full(NewDir(installDir)), StringComparison.OrdinalIgnoreCase);
            }
            catch (Exception e) when (e is ArgumentException || e is NotSupportedException || e is PathTooLongException)
            {
                return false;
            }
        }

        /// Swap `newDir` in; null when done, otherwise "<step>: <reason>" (with the old version back in place).
        public static string Run(string installDir, string newDir, Action<string, string> copyTree)
        {
            Environment.CurrentDirectory = OutsideFolder(installDir);    // never stand in a folder about to be renamed
            var previous = PreviousDir(installDir);
            var older = OlderDir(installDir);
            var hadPrevious = Directory.Exists(previous);
            try
            {
                if (Directory.Exists(older)) Retry(() => Directory.Delete(older, recursive: true));   // a swap cut short
                if (hadPrevious) Retry(() => Directory.Move(previous, older));
            }
            catch (Exception e) when (e is IOException || e is UnauthorizedAccessException)
            {
                return $"{Updates.StepLabel(InstallStep.MoveOldAside)}: {e.Message}";
            }
            try
            {
                Retry(() => Directory.Move(installDir, previous));
            }
            catch (Exception e) when (e is IOException || e is UnauthorizedAccessException)
            {
                try
                {
                    if (hadPrevious) Retry(() => Directory.Move(older, previous));
                }
                catch (Exception back) when (back is IOException || back is UnauthorizedAccessException)
                {
                    return $"{Updates.StepLabel(InstallStep.MoveOldAside)}: {e.Message} (the version before it is in {older}: {back.Message})";
                }
                return $"{Updates.StepLabel(InstallStep.MoveOldAside)}: {e.Message}";
            }
            try
            {
                copyTree(newDir, installDir);
            }
            catch (Exception e) when (e is IOException || e is UnauthorizedAccessException)
            {
                try
                {
                    if (Directory.Exists(installDir)) Retry(() => Directory.Delete(installDir, recursive: true));
                    Retry(() => Directory.Move(previous, installDir));
                    if (hadPrevious) Retry(() => Directory.Move(older, previous));
                }
                catch (Exception back) when (back is IOException || back is UnauthorizedAccessException)
                {
                    return $"{Updates.StepLabel(InstallStep.CopyNewIn)}: {e.Message} (and the previous version couldn't be put back: {back.Message})";
                }
                return $"{Updates.StepLabel(InstallStep.CopyNewIn)}: {e.Message}";
            }
            if (hadPrevious)
            {
                try { Retry(() => Directory.Delete(older, recursive: true)); }
                catch (Exception e) when (e is IOException || e is UnauthorizedAccessException) { }   // the next swap removes it
            }
            return null;
        }

        /// After a swap, the copy to start: the installed one, or, if a failed swap couldn't put it back, the previous one,
        /// or else the new one (final review, minor 4: never a missing exe, which would leave nothing running).
        public static string ExeToStart(string installDir)
        {
            foreach (var dir in new[] { installDir, PreviousDir(installDir), NewDir(installDir) })
            {
                var exe = Path.Combine(dir, "LoupedeckBridge.exe");
                if (File.Exists(exe)) return exe;
            }
            return Path.Combine(installDir, "LoupedeckBridge.exe");
        }

        /// Prepare going back: copy .previous into .new, to be handed over like an update.
        public static string GoBack(string installDir, Action<string, string> copyTree)
        {
            var previous = PreviousDir(installDir);
            var problem = GoBackProblem(previous);
            if (problem != null) return problem;
            var target = NewDir(installDir);
            try
            {
                if (Directory.Exists(target)) Retry(() => Directory.Delete(target, recursive: true));
                copyTree(previous, target);
                return null;
            }
            catch (Exception e) when (e is IOException || e is UnauthorizedAccessException)
            {
                return $"{Updates.StepLabel(InstallStep.Unzip)}: couldn't copy the previous version ({e.Message})";
            }
        }

        /// Why `previousDir` can't be gone back to, or null: it must be a complete release of a readable version.
        /// (Its signature isn't checked again: it was checked when it was downloaded, and anything that could change it
        /// in the user's own folder could change the installed copy too.)
        public static string GoBackProblem(string previousDir)
        {
            if (!File.Exists(Path.Combine(previousDir, "LoupedeckBridge.exe"))) return "there's no previous version";
            var info = BuildInfo.Load(Path.Combine(previousDir, BuildInfo.FileName));
            if (info == null || info.Runtime != "bundled" || info.IsDev || info.Version == null)
                return "the previous version is incomplete";
            return null;
        }

        /// At startup: remove the .new folder an update left (its copy may still be exiting; retried for a while).
        public static void CleanUp(string installDir)
        {
            var leftover = NewDir(installDir);
            if (!Directory.Exists(leftover)) return;
            new Thread(() =>
            {
                for (var i = 0; i < 30 && Directory.Exists(leftover); i++)
                {
                    try { Directory.Delete(leftover, recursive: true); }
                    catch (Exception e) when (e is IOException || e is UnauthorizedAccessException) { Thread.Sleep(1000); }
                }
            }) { IsBackground = true, Name = "update clean-up" }.Start();
        }

        public static void CopyTree(string from, string to)
        {
            Directory.CreateDirectory(to);
            foreach (var file in Directory.GetFiles(from)) File.Copy(file, Path.Combine(to, Path.GetFileName(file)), overwrite: true);
            foreach (var dir in Directory.GetDirectories(from)) CopyTree(dir, Path.Combine(to, Path.GetFileName(dir)));
        }

        /// Antivirus scanners briefly hold files a new program was just written with: try a few times.
        static void Retry(Action action)
        {
            for (var attempt = 1; ; attempt++)
            {
                try
                {
                    action();
                    return;
                }
                catch (IOException) when (attempt < 10) { Thread.Sleep(300); }
                catch (UnauthorizedAccessException) when (attempt < 10) { Thread.Sleep(300); }
            }
        }
    }
}
