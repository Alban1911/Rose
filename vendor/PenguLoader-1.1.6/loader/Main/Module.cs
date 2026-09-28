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
                    // Compare the module the debugger runs rather than the exact text, like
                    // current upstream: the same hook written with other spacing or case is
                    // active, and reinstalling it is refused while the client has it loaded
                    var path = DebuggerModulePath(IFEO.GetDebugger(TargetName));
                    return path != null && IsSamePath(path, ModulePath);
                }
            }
        }

        // core.dll path of a 'rundll32 "<core.dll>", #6000' debugger value, or null
        private static string DebuggerModulePath(string debugger)
        {
            var value = (debugger ?? string.Empty).Trim();
            if (!value.StartsWith("rundll32 ", StringComparison.OrdinalIgnoreCase))
                return null;

            var start = value.IndexOf('"');
            var end = start < 0 ? -1 : value.IndexOf('"', start + 1);
            if (end < 0 || value.Substring(end + 1).Replace(" ", string.Empty) != ",#6000")
                return null;

            return value.Substring(start + 1, end - start - 1);
        }

        private static bool IsSamePath(string a, string b)
        {
            try
            {
                return Utils.NormalizePath(a) == Utils.NormalizePath(b);
            }
            catch
            {
                return false;
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
