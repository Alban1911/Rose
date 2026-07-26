using System;
using System.Diagnostics;
using System.IO;
using Microsoft.Win32;

namespace PenguLoader.Main
{
    internal static class IFEO
    {
        private static string IFEO_PATH => @"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options";
        private static string VALUE_NAME => "Debugger";

        public static string GetDebugger(string target)
        {
            using (var key = Registry.LocalMachine.OpenSubKey(IFEO_PATH))
            {
                if (key == null)
                    return string.Empty;

                using (var image = key.OpenSubKey(target))
                {
                    if (image == null)
                        return string.Empty;

                    return image.GetValue(VALUE_NAME) as string;
                }
            }
        }

        public static void SetDebugger(string t, string d)
        {
            d = d.Replace("\"", "\\\"");
            Invoke($"reg add \"HKLM\\{IFEO_PATH}\\{t}\" /v \"{VALUE_NAME}\" /t REG_SZ /d \"{d}\" /f");
        }

        public static void RemoveDebugger(string t)
        {
            Invoke($"reg delete \"HKLM\\{IFEO_PATH}\\{t}\" /f");
        }

        public static void Invoke(string args)
        {
            using (var process = new Process
            {
                StartInfo = new ProcessStartInfo
                {
                    FileName = "cmd.exe",
                    Arguments = $"/C {args}",
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    UseShellExecute = false,
                    CreateNoWindow = true
                }
            })
            {
                process.Start();
                process.WaitForExit();
                var error = process.StandardError.ReadToEnd();

                if (process.ExitCode != 0 || !string.IsNullOrEmpty(error))
                {
                    throw new InvalidOperationException(error);
                }
            }
        }
    }
}