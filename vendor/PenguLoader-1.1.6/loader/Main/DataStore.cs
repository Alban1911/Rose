using System;
using System.Diagnostics;
using System.IO;
using System.Windows;

namespace PenguLoader.Main
{
    internal static class DataStore
    {
        public static bool IsDataStore(string path)
        {
            if (string.IsNullOrEmpty(path))
                return false;

            return Path.GetFileName(path).Equals("datastore", StringComparison.OrdinalIgnoreCase)
                && File.Exists(path);
        }

        public static void DumpDataStore(string path)
        {
            try
            {
                var output = Path.GetTempFileName();
                var bytes = File.ReadAllBytes(path);

                if (bytes.Length == 0)
                {
                    MessageBox.Show("Your DataStore is empty!",
                        Program.Name, MessageBoxButton.OK, MessageBoxImage.Information);
                    return;
                }

                Transform(bytes);
                File.WriteAllBytes(output, bytes);

                Process.Start(new ProcessStartInfo
                {
                    FileName = "notepad.exe",
                    Arguments = $"\"{output}\"",
                    UseShellExecute = false
                });
            }
            catch
            {
                MessageBox.Show($"Failed to dump DataStore from path: {path}",
                    Program.Name, MessageBoxButton.OK, MessageBoxImage.Information);
            }
        }

        static void Transform(byte[] bytes)
        {
            const string KEY = "A5dgY6lz9fpG9kGNiH1mZ";

            if (bytes != null && bytes.Length > 0)
            {
                for (int i = 0; i < bytes.Length; i++)
                {
                    bytes[i] ^= (byte)KEY[i % KEY.Length];
                }
            }
        }
    }
}