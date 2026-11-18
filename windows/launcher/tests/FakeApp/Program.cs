// A stand-in for LoupedeckBridge.exe (tests only). It appends "<its own path> <arguments>" to $LB_FAKE_LOG, then:
//   (no arguments)  stays running for 60 s if LB_FAKE_STAY=1, otherwise exits at once
//   --quit          ends the other running copies of itself (same path) and exits 0; with LB_FAKE_WONT_QUIT=1 it
//                   leaves them and exits 1, like a LoupedeckBridge that won't quit
//   --login status  prints "off"

using System;
using System.Diagnostics;
using System.IO;
using System.Threading;

static class FakeApp
{
    static int Main(string[] args)
    {
        var self = Process.GetCurrentProcess();
        var path = self.MainModule.FileName;
        var log = Environment.GetEnvironmentVariable("LB_FAKE_LOG");
        if (!string.IsNullOrEmpty(log)) File.AppendAllText(log, path + " " + string.Join(" ", args) + "\n");
        if (args.Length > 0 && args[0] == "--quit")
        {
            if (Environment.GetEnvironmentVariable("LB_FAKE_WONT_QUIT") == "1") return 1;
            foreach (var p in Process.GetProcessesByName(Path.GetFileNameWithoutExtension(path)))
            {
                try
                {
                    if (p.Id == self.Id || !string.Equals(p.MainModule.FileName, path, StringComparison.OrdinalIgnoreCase)) continue;
                    p.Kill();
                    p.WaitForExit(5000);
                }
                catch (Exception) { }
            }
            return 0;
        }
        if (args.Length > 0 && args[0] == "--login")
        {
            Console.WriteLine("off");
            return 0;
        }
        if (Environment.GetEnvironmentVariable("LB_FAKE_STAY") == "1") Thread.Sleep(60000);
        return 0;
    }
}
