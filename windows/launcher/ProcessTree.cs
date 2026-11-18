// Ending the bridge completely (milestone 7 live check). A venv's python.exe (the dev build's) is only a launcher: it
// starts the real Python as its own child. Killing the launcher alone would leave the real bridge running, holding
// the Loupedeck and the single-instance lock, so the next restart would fail with "already running". So a forced stop
// also ends the launcher's Python child, and once the launcher has exited, an orphaned Python child is ended too.
// Only children the filter accepts (python.exe) are ever touched: the bridge also starts other programs (the browser,
// for the settings page), and those are never ended. The release's bundled python.exe has no launcher: a no-op there.

using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;

namespace LoupedeckBridge
{
    static class ProcessTree
    {
        public static bool IsPython(string exeName) =>
            string.Equals(exeName, "python.exe", StringComparison.OrdinalIgnoreCase)
            || string.Equals(exeName, "pythonw.exe", StringComparison.OrdinalIgnoreCase);

        /// The direct children of `parentId` that the filter accepts and that started after `parentStart` (so a
        /// reused process id can't make an unrelated process look like a child).
        public static List<int> Children(int parentId, DateTime parentStart, Func<string, bool> accept)
        {
            var found = new List<int>();
            foreach (var (pid, ppid, name) in Snapshot())
            {
                if (ppid != parentId || !accept(name)) continue;
                try
                {
                    using (var p = Process.GetProcessById(pid))
                        if (p.StartTime >= parentStart) found.Add(pid);
                }
                catch (Exception e) when (e is ArgumentException || e is InvalidOperationException || e is Win32Exception) { }
            }
            return found;
        }

        /// Kill `root` and its accepted children.
        public static void Kill(Process root, Func<string, bool> accept)
        {
            DateTime start;
            try { start = root.StartTime; }
            catch (Exception e) when (e is InvalidOperationException || e is Win32Exception) { return; }
            var children = Children(root.Id, start, accept);
            TryKill(root);
            foreach (var pid in children) TryKill(pid);
        }

        /// After `parentId` has exited: end its accepted children that are still running.
        public static void EndOrphans(int parentId, DateTime parentStart, Func<string, bool> accept)
        {
            foreach (var pid in Children(parentId, parentStart, accept)) TryKill(pid);
        }

        static void TryKill(int pid)
        {
            try { using (var p = Process.GetProcessById(pid)) TryKill(p); }
            catch (ArgumentException) { }
        }

        static void TryKill(Process p)
        {
            try
            {
                if (p.HasExited) return;
                p.Kill();
                p.WaitForExit(5000);
            }
            catch (Exception e) when (e is InvalidOperationException || e is Win32Exception) { }
        }

        // ---- every process's id, parent id and exe name (Toolhelp32) -------------------------------------------
        static IEnumerable<(int pid, int ppid, string name)> Snapshot()
        {
            var list = new List<(int, int, string)>();
            var snapshot = CreateToolhelp32Snapshot(SnapProcess, 0);
            if (snapshot == InvalidHandle) return list;
            try
            {
                var entry = new PROCESSENTRY32W { dwSize = (uint)Marshal.SizeOf(typeof(PROCESSENTRY32W)) };
                for (var ok = Process32FirstW(snapshot, ref entry); ok; ok = Process32NextW(snapshot, ref entry))
                    list.Add(((int)entry.th32ProcessID, (int)entry.th32ParentProcessID, Path.GetFileName(entry.szExeFile)));
            }
            finally { CloseHandle(snapshot); }
            return list;
        }

        const uint SnapProcess = 0x00000002;
        static readonly IntPtr InvalidHandle = new IntPtr(-1);

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        struct PROCESSENTRY32W
        {
            public uint dwSize;
            public uint cntUsage;
            public uint th32ProcessID;
            public IntPtr th32DefaultHeapID;
            public uint th32ModuleID;
            public uint cntThreads;
            public uint th32ParentProcessID;
            public int pcPriClassBase;
            public uint dwFlags;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)] public string szExeFile;
        }

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern IntPtr CreateToolhelp32Snapshot(uint flags, uint processId);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern bool Process32FirstW(IntPtr snapshot, ref PROCESSENTRY32W entry);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern bool Process32NextW(IntPtr snapshot, ref PROCESSENTRY32W entry);

        [DllImport("kernel32.dll")]
        static extern bool CloseHandle(IntPtr handle);
    }
}
