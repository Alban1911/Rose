using Microsoft.Win32;

namespace PenguLoader.Main
{
    internal static class IFEO
    {
        private static string IFEO_PATH => @"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options";
        private static string VALUE_NAME => "Debugger";

        public static string GetDebugger(string target)
        {
            using (var key = OpenIfeo(false))
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

        // Written through the registry API like current upstream: the value went
        // through "cmd /C reg add" before, which cut it at a & in the user's path
        // (e.g. C:\Users\Tom&Jerry) and dropped ^, leaving a broken debugger
        public static void SetDebugger(string target, string debugger)
        {
            using (var key = OpenIfeo(true))
            using (var image = key.CreateSubKey(target, true))
            {
                image.SetValue(VALUE_NAME, debugger, RegistryValueKind.String);
            }
        }

        // Only the Debugger value: the key can hold other settings (e.g. exploit protection)
        public static void RemoveDebugger(string target)
        {
            using (var key = OpenIfeo(true))
            using (var image = key.OpenSubKey(target, true))
            {
                image?.DeleteValue(VALUE_NAME, false);
            }
        }

        // The 64-bit view, which LeagueClientUx.exe uses, whatever this process' bitness
        private static RegistryKey OpenIfeo(bool writable)
        {
            using (var hklm = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, RegistryView.Registry64))
            {
                return hklm.OpenSubKey(IFEO_PATH, writable);
            }
        }
    }
}
