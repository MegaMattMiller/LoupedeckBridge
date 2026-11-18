// The tray app's own messages go to the bridge's log, in its format, as on the Mac (BridgeProcess.swift's log).

using System;
using System.Globalization;
using System.IO;
using System.Text;

namespace LoupedeckBridge
{
    static class Log
    {
        static readonly object Gate = new object();

        public static string Folder =>
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "loupedeck-lr-bridge", "logs");

        public static string FilePath => Path.Combine(Folder, "bridge.log");

        public static void Write(string message, string level = "INFO")
        {
            var stamp = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss','fff", CultureInfo.InvariantCulture);
            Append($"{stamp} {level,-7} launcher: {message}{Environment.NewLine}");
        }

        /// Appends text as UTF-8. The file is opened for each write, sharing delete access, so the bridge's log
        /// rotation (a rename) never fails because the tray app has it open.
        public static void Append(string text)
        {
            lock (Gate)
            {
                try
                {
                    Directory.CreateDirectory(Folder);
                    using (var file = new FileStream(FilePath, FileMode.Append, FileAccess.Write,
                                                     FileShare.ReadWrite | FileShare.Delete))
                    {
                        var bytes = new UTF8Encoding(false).GetBytes(text);
                        file.Write(bytes, 0, bytes.Length);
                    }
                }
                catch (Exception e) when (e is IOException || e is UnauthorizedAccessException) { }
            }
        }
    }
}
