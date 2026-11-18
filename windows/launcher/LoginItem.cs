// Start at login: a value named after the build ("LoupedeckBridge" or "LoupedeckBridge Dev") under the user's Run key,
// so it shows in Task Manager → Startup apps. Off until ticked in the menu.

using System;
using Microsoft.Win32;

namespace LoupedeckBridge
{
    static class LoginItem
    {
        const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";

        public static bool IsOn(string name)
        {
            using (var key = Registry.CurrentUser.OpenSubKey(RunKey)) return key?.GetValue(name) != null;
        }

        public static void Set(string name, string exe, bool on)
        {
            using (var key = Registry.CurrentUser.CreateSubKey(RunKey))
            {
                if (on) key.SetValue(name, "\"" + exe + "\"");      // a path can't contain quotes
                else key.DeleteValue(name, throwOnMissingValue: false);
            }
        }

        /// `LoupedeckBridge.exe --login on|off|status`: prints "on" or "off" (tools/bridgectl.ps1 login).
        public static int Command(string name, string exe, string arg)
        {
            try
            {
                if (arg == "on" || arg == "off") Set(name, exe, arg == "on");
                else if (arg != "status")
                {
                    Console.Error.WriteLine("usage: LoupedeckBridge.exe --login on|off|status");
                    return 2;
                }
                Console.WriteLine(IsOn(name) ? "on" : "off");
                return 0;
            }
            catch (Exception e) when (e is UnauthorizedAccessException || e is System.Security.SecurityException
                                      || e is System.IO.IOException)
            {
                Console.Error.WriteLine("couldn't change Start at login: " + e.Message);
                return 1;
            }
        }
    }
}
