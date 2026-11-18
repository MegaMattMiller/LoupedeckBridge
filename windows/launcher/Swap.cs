// Putting a new version in place, and going back (milestone 7). A running program can't be moved or deleted on
// Windows (the Mac app moves itself to the Trash), so an update is finished by the *new* copy, started from
// <install>.new after the old one has exited (`LoupedeckBridge.exe --finish-update`):
//   1. the install folder is renamed to <install>.previous (replacing an older one)
//   2. the new copy copies itself into the install folder
// If step 2 fails, the partial copy is removed and .previous is renamed back, so there's always a working version.
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
            var previous = PreviousDir(installDir);
            try
            {
                if (Directory.Exists(previous)) Retry(() => Directory.Delete(previous, recursive: true));
                Retry(() => Directory.Move(installDir, previous));
            }
            catch (Exception e) when (e is IOException || e is UnauthorizedAccessException)
            {
                return $"{InstallStep.MoveOldAside}: {e.Message}";
            }
            try
            {
                copyTree(newDir, installDir);
                return null;
            }
            catch (Exception e) when (e is IOException || e is UnauthorizedAccessException)
            {
                try
                {
                    if (Directory.Exists(installDir)) Retry(() => Directory.Delete(installDir, recursive: true));
                    Retry(() => Directory.Move(previous, installDir));
                }
                catch (Exception back) when (back is IOException || back is UnauthorizedAccessException)
                {
                    return $"{InstallStep.CopyNewIn}: {e.Message} (and the previous version couldn't be put back: {back.Message})";
                }
                return $"{InstallStep.CopyNewIn}: {e.Message}";
            }
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
                return $"{InstallStep.Unzip}: couldn't copy the previous version ({e.Message})";
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
