using System;
using System.IO;

namespace PenguLoader.Main
{
    static class Module
    {
        private static string ModuleName => "core.dll";
        private static string TargetName => LCU.ClientUxProcessName;
        private static string ModulePath => Path.Combine(AppDomain.CurrentDomain.BaseDirectory, ModuleName);
        private static string DebuggerValue => $"rundll32 \"{ModulePath}\", #6000 ";

        private static string SymlinkName => "version.dll";
        private static string SymlinkPath => Path.Combine(Config.LeaguePath, SymlinkName);

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

                    return string.Compare(resolved, modulePath, false) == 0;
                }
                else
                {
                    var param = IFEO.GetDebugger(TargetName);
                    return DebuggerValue.Equals(param, StringComparison.OrdinalIgnoreCase);
                }
            }
        }

        public static bool SetActive(bool active)
        {
            if (IsActivated != active)
            {
                if (Config.UseSymlink)
                {
                    var path = SymlinkPath;
                    Utils.DeletePath(path);

                    if (active)
                        Symlink.Create(path, ModulePath);
                }
                else if (active)
                {
                    IFEO.SetDebugger(TargetName, DebuggerValue);
                }
                else
                {
                    IFEO.RemoveDebugger(TargetName);
                }

                if (IsActivated != active)
                    return false;
            }

            RoseConfig.SetLoaderState(active);
            return true;
        }
    }
}
