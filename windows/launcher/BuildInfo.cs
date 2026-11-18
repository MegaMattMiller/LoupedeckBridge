// What kind of build this is, from LoupedeckBridge.json next to the exe: the Windows twin of the Mac app's
// Info.plist keys (LBRuntime, LBRepoPath, LBVersion, LBIsDev, LBSignerSHA256). tools/build_windows_app.ps1 writes it.
//   {"runtime": "bundled"|"repo", "repo": "C:\\…", "version": "0.6.0", "is_dev": false, "signer_sha256": "…"}

using System;
using System.IO;
using System.Text;

namespace LoupedeckBridge
{
    public sealed class BuildInfo
    {
        public const string FileName = "LoupedeckBridge.json";

        public string Runtime { get; private set; }        // "bundled" (releases) or "repo" (the dev build)
        public string Repo { get; private set; }           // the dev build's checkout
        public Version Version { get; private set; }       // null if missing or unreadable
        public bool IsDev { get; private set; }
        public string SignerSha256 { get; private set; }   // the release key's certificate SHA-256 updates must match

        public string Name => IsDev ? "LoupedeckBridge Dev" : "LoupedeckBridge";
        /// One copy per user session (and the dev build and the release never share it).
        public string MutexName => @"Local\" + Name;
        /// Set by `LoupedeckBridge.exe --quit` to ask the running copy to quit as if from its menu.
        public string QuitEventName => MutexName + ".quit";

        /// The build info in `json`, or null if it isn't a JSON object or a field has the wrong type.
        public static BuildInfo Parse(string json)
        {
            var fields = Json.Object(json);
            if (fields == null) return null;
            if (!Json.Optional(fields, "runtime", out string runtime) || !Json.Optional(fields, "repo", out string repo)
                || !Json.Optional(fields, "version", out string version) || !Json.Optional(fields, "is_dev", out bool isDev)
                || !Json.Optional(fields, "signer_sha256", out string signer)) return null;
            return new BuildInfo
            {
                Runtime = runtime, Repo = repo, Version = Version.Parse(version), IsDev = isDev, SignerSha256 = signer ?? "",
            };
        }

        /// The build info in the file at `path`, or null if it's missing or unreadable.
        public static BuildInfo Load(string path)
        {
            try { return Parse(File.ReadAllText(path, Encoding.UTF8)); }
            catch (Exception e) when (e is IOException || e is UnauthorizedAccessException || e is ArgumentException
                                      || e is NotSupportedException) { return null; }
        }
    }
}
