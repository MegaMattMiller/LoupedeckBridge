// The release's update preferences, under HKCU\Software\LoupedeckBridge (the Mac app's UserDefaults): "check for
// updates automatically", the last check, a found update and its announcement, and a note from an update that didn't
// finish (shown on the next start). Dev builds never update, so they never write here. And the Apps entry's version.

using System;
using System.Globalization;
using Microsoft.Win32;

namespace LoupedeckBridge
{
    static class Prefs
    {
        const string Key = @"Software\LoupedeckBridge";

        public static string GetString(string name)
        {
            using (var key = Registry.CurrentUser.OpenSubKey(Key)) return key?.GetValue(name) as string;
        }

        public static void Set(string name, object value)
        {
            try { using (var key = Registry.CurrentUser.CreateSubKey(Key)) key.SetValue(name, value); }
            catch (Exception e) when (e is UnauthorizedAccessException || e is System.Security.SecurityException) { }
        }

        public static void Delete(string name)
        {
            try { using (var key = Registry.CurrentUser.OpenSubKey(Key, writable: true)) key?.DeleteValue(name, throwOnMissingValue: false); }
            catch (Exception e) when (e is UnauthorizedAccessException || e is System.Security.SecurityException) { }
        }

        public static bool GetBool(string name, bool fallback)
        {
            using (var key = Registry.CurrentUser.OpenSubKey(Key)) return key?.GetValue(name) is int value ? value != 0 : fallback;
        }

        public static DateTime? GetDate(string name) =>
            DateTime.TryParse(GetString(name), CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind, out var when)
                ? when.ToUniversalTime() : (DateTime?)null;

        public static void SetDate(string name, DateTime whenUtc) => Set(name, whenUtc.ToString("o", CultureInfo.InvariantCulture));
    }

    static class Registration
    {
        /// The Settings → Apps entry tools/install.ps1 made (none for a dev build, or a copy it didn't install).
        public const string UninstallKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\LoupedeckBridge";

        public static void SetDisplayVersion(string version, string uninstallKey = UninstallKey)
        {
            try { using (var key = Registry.CurrentUser.OpenSubKey(uninstallKey, writable: true)) key?.SetValue("DisplayVersion", version); }
            catch (Exception e) when (e is UnauthorizedAccessException || e is System.Security.SecurityException) { }
        }
    }
}
