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

        public static void SetDebugger(string target, string value)
        {
            using (var key = Registry.LocalMachine.CreateSubKey($@"{IFEO_PATH}\{target}", true))
            {
                key.SetValue(VALUE_NAME, value, RegistryValueKind.String);
            }
        }

        public static void RemoveDebugger(string target)
        {
            Registry.LocalMachine.DeleteSubKeyTree($@"{IFEO_PATH}\{target}", false);
        }
    }
}