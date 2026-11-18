// Copying a download to disk with a size cap, hashing it as it arrives (milestone 7; the Mac's Download.swift).

using System;
using System.IO;
using System.Security.Cryptography;

namespace LoupedeckBridge
{
    sealed class DownloadTooLargeException : Exception
    {
        public DownloadTooLargeException(long limit) : base($"it's bigger than {limit / (1024 * 1024)} MB, so it isn't a release") { }
    }

    static class Download
    {
        /// A release is about 30 MB, so anything past 200 MB isn't one.
        public const long Limit = 209_715_200;

        /// Copies `from` to `to`, refusing more than `limit` bytes; returns the SHA-256 in lowercase hex.
        public static string CopyCapped(Stream from, Stream to, long limit)
        {
            using (var sha = SHA256.Create())
            {
                var buffer = new byte[81920];
                long total = 0;
                int read;
                while ((read = from.Read(buffer, 0, buffer.Length)) > 0)
                {
                    total += read;
                    if (total > limit) throw new DownloadTooLargeException(limit);
                    sha.TransformBlock(buffer, 0, read, null, 0);
                    to.Write(buffer, 0, read);
                }
                sha.TransformFinalBlock(buffer, 0, 0);
                return BitConverter.ToString(sha.Hash).Replace("-", "").ToLowerInvariant();
            }
        }
    }
}
