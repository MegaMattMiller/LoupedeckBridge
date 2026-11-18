// Is a download signed with the user's own LoupedeckBridge release key? (milestone 7; the Mac's Signature.swift)
// A Windows release zip carries a detached CMS signature (.p7s, from tools/sign_windows_zip.sh) over its exact bytes.
// The check: the signature verifies (signature only: the certificate is self-signed, so there's no chain to build),
// it has exactly one signer, and that signer's certificate has the SHA-256 this build pins (LoupedeckBridge.json's
// signer_sha256, the same fingerprint as the Mac app's and tools/install.sh's). This is what makes updates safe: only
// builds signed with the user's key are ever installed, even if a GitHub release were tampered with.

using System;
using System.Security.Cryptography;
using System.Security.Cryptography.Pkcs;
using System.Text.RegularExpressions;

namespace LoupedeckBridge
{
    static class Signature
    {
        /// The reason `content` isn't signed with the pinned key, in plain words, or null if it is.
        public static string Problem(byte[] content, byte[] p7s, string pinnedSha256)
        {
            if (pinnedSha256 == null || !Regex.IsMatch(pinnedSha256, "^[0-9A-Fa-f]{64}$"))
                return "no release key is pinned in this build";
            var cms = new SignedCms(new ContentInfo(content), detached: true);
            try { cms.Decode(p7s); }
            catch (Exception e) when (e is CryptographicException || e is ArgumentException) { return "the signature is unreadable"; }
            if (cms.SignerInfos.Count != 1) return "the signature should have exactly one signer";
            var signer = cms.SignerInfos[0];
            if (signer.Certificate == null) return "the signature is unreadable";
            try { signer.CheckSignature(verifySignatureOnly: true); }
            catch (CryptographicException) { return "the signature doesn't match the download"; }
            using (var sha = SHA256.Create())
            {
                var leaf = BitConverter.ToString(sha.ComputeHash(signer.Certificate.RawData)).Replace("-", "");
                return string.Equals(leaf, pinnedSha256, StringComparison.OrdinalIgnoreCase) ? null : "it's signed with another key";
            }
        }
    }
}
