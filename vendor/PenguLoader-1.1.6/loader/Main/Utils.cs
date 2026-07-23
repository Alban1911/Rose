using System;
using System.Diagnostics;
using System.IO;

namespace PenguLoader.Main
{
    internal static class Utils
    {
        public static void OpenFolder(string path) => Process.Start("explorer.exe", $"\"{path}\"");

        public static void OpenLink(string url) => Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });

        public static bool IsFileInUse(string path)
        {
            if (!File.Exists(path)) return false;

            try
            {
                using (new FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.None)) { }
            }
            catch
            {
                return true;
            }

            return false;
        }

        public static void DeletePath(string path, bool isDir = false)
        {
            try
            {
                if (isDir) Directory.Delete(path, true);
                else File.Delete(path);
            }
            catch { }
        }

        public static void EnsureDirectoryExists(string path)
        {
            if (!Directory.Exists(path))
                Directory.CreateDirectory(path);
        }

        public static void EnsureFileExists(string path)
        {
            if (!File.Exists(path))
                File.Create(path).Close();
        }

        public static string NormalizePath(string path)
        {
            return Path.GetFullPath(new Uri(path).LocalPath)
                .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
                .ToUpperInvariant();
        }
    }
}