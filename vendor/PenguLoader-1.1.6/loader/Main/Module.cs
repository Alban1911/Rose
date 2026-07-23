using System;
using System.IO;
using System.Runtime.InteropServices;

namespace PenguLoader.Main
{
    // Pengu's original activation mechanism. The loader is registered as the
    // debugger for LeagueClientUx.exe, so Windows starts core.dll when the UX
    // process launches. No proxy DLL is copied into the League directory.
    static class Module
    {
        private static string ModuleName => "core.dll";
        private static string TargetName => LCU.ClientUxProcessName;
        private static string LoaderDir => AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\', '/');
        private static string ModulePath => Path.Combine(LoaderDir, ModuleName);
        private static string DebuggerValue => $"rundll32 \"{ModulePath}\", #6000 ";

        private static string SymlinkName => "version.dll";
        private static string SymlinkPath => Path.Combine(Config.LeaguePath, SymlinkName);

        private static string RoseConfigPath
        {
            get
            {
                var localAppData = DesktopUser.GetLocalAppData();
                return Path.Combine(localAppData, "Rose", "config.ini");
            }
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
        private static extern bool WritePrivateProfileString(
            string section,
            string key,
            string value,
            string filePath);

        public static bool IsFound => File.Exists(ModulePath);

        public static bool IsLoaded => Utils.IsFileInUse(ModulePath);

        public static bool IsActivated
        {
            get
            {
                if (Config.UseSymlink)
                {
                    if (!LCU.IsValidDir(Config.LeaguePath))
                        return false;

                    var resolved = Utils.NormalizePath(Symlink.Resolve(SymlinkPath));
                    var modulePath = Utils.NormalizePath(ModulePath);
                    return string.Equals(resolved, modulePath, StringComparison.OrdinalIgnoreCase);
                }

                var debugger = IFEO.GetDebugger(TargetName);
                return DebuggerValue.Equals(debugger, StringComparison.OrdinalIgnoreCase);
            }
        }

        public static bool SetActive(bool active)
        {
            if (IsActivated == active)
            {
                WriteCoreConfig(active);
                return true;
            }

            if (Config.UseSymlink)
            {
                Utils.DeletePath(SymlinkPath);

                if (active)
                    Symlink.Create(SymlinkPath, ModulePath);
            }
            else if (active)
            {
                IFEO.SetDebugger(TargetName, DebuggerValue);
            }
            else
            {
                IFEO.RemoveDebugger(TargetName);
            }

            // core.dll reads these values when it is loaded by LeagueClientUx.
            // Keep this in sync with the activation mechanism so IFEO launches
            // do not immediately disable the native hook.
            WriteCoreConfig(active);

            return IsActivated == active;
        }

        private static void WriteCoreConfig(bool active)
        {
            var configPath = RoseConfigPath;
            var directory = Path.GetDirectoryName(configPath);

            if (!Directory.Exists(directory))
                Directory.CreateDirectory(directory);

            WritePrivateProfileString("General", "disabled", active ? "0" : "1", configPath);
            WritePrivateProfileString("General", "loaderpath", active ? LoaderDir : string.Empty, configPath);
        }
    }
}