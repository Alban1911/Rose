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
        private static string ModulePath => Path.GetFullPath(Path.Combine(LoaderDir, ModuleName));
        internal static string DebuggerValue => IFEO.BuildDebuggerCommand(ModulePath);

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

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool WritePrivateProfileString(
            string section,
            string key,
            string value,
            string filePath);

        internal static Func<string, string, string, string, bool> ConfigWriter { get; set; } = WritePrivateProfileString;

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

                return IFEO.IsActivated(TargetName, ModulePath);
            }
        }

        public static ActivationResult SetActive(bool active)
        {
            if (!Elevation.IsElevated())
                return Elevation.RunElevated(active, false);
            if (IsActivated == active)
                return WriteConfigOrFailure(active);

            ActivationResult result;
            if (Config.UseSymlink)
            {
                result = SetSymlinkActive(active);
            }
            else
            {
                result = active
                    ? IFEO.Activate(TargetName, ModulePath)
                    : IFEO.Deactivate(TargetName);
            }

            if (!result.Succeeded)
                return result;

            // core.dll reads these values when it is loaded by LeagueClientUx.
            // The registry/symlink operation is intentionally completed first.
            var configResult = WriteConfigOrFailure(active);
            if (!configResult.Succeeded)
            {
                var registryState = active ? "true" : "false";
                Logger.Error(
                    "Config",
                    "stage=WriteCoreConfig failed native=" + configResult.NativeErrorCode +
                    " registryActive=" + registryState + " configUpdated=false");
                Logger.Error(
                    "Activation",
                    "partialState registryActive=" + registryState + " configUpdated=false");
                return ActivationResult.Failure(
                    ActivationStage.WriteCoreConfig,
                    configResult.ErrorKind,
                    configResult.NativeErrorCode,
                    configResult.NativeErrorMessage +
                    " Registry state was changed but Rose core configuration was not updated.",
                    true);
            }

            if (IsActivated != active)
            {
                return ActivationResult.Failure(
                    ActiveStage(active),
                    ActivationErrorKind.Other,
                    0,
                    "The final activation state did not match the requested state.");
            }

            return ActivationResult.Success();
        }

        private static ActivationResult SetSymlinkActive(bool active)
        {
            if (!TryDeleteSymlink())
            {
                return ActivationResult.FromWin32(
                    ActivationStage.DeleteSymlink,
                    Marshal.GetLastWin32Error(),
                    "Unable to remove the existing League symlink.");
            }

            if (active && !Symlink.Create(SymlinkPath, ModulePath))
            {
                var nativeErrorCode = Marshal.GetLastWin32Error();
                return ActivationResult.FromWin32(
                    ActivationStage.CreateSymlink,
                    nativeErrorCode);
            }

            return ActivationResult.Success();
        }

        private static bool TryDeleteSymlink()
        {
            try
            {
                if (File.Exists(SymlinkPath))
                    File.Delete(SymlinkPath);
                return !File.Exists(SymlinkPath);
            }
            catch (Exception ex)
            {
                Logger.Error("Module", "Failed to remove symlink", ex);
                return false;
            }
        }

        private static ActivationResult WriteConfigOrFailure(
            bool active)
        {
            try
            {
                var configPath = RoseConfigPath;
                var directory = Path.GetDirectoryName(configPath);

                if (!Directory.Exists(directory))
                    Directory.CreateDirectory(directory);

                if (!ConfigWriter("General", "disabled", active ? "0" : "1", configPath) ||
                    !ConfigWriter("General", "loaderpath", active ? LoaderDir : string.Empty, configPath))
                {
                    var nativeErrorCode = Marshal.GetLastWin32Error();
                    return ActivationResult.FromWin32(ActivationStage.WriteCoreConfig, nativeErrorCode);
                }

                return ActivationResult.Success();
            }
            catch (Exception ex)
            {
                Logger.Error("Module", "Failed to update Rose core configuration", ex);
                return ActivationResult.Failure(
                    ActivationStage.WriteCoreConfig,
                    ActivationErrorKind.Other,
                    0,
                    ex.Message);
            }
        }

        private static ActivationStage ActiveStage(bool active)
        {
            return Config.UseSymlink
                ? (active ? ActivationStage.CreateSymlink : ActivationStage.DeleteSymlink)
                : (active ? ActivationStage.SetDebugger : ActivationStage.DeleteDebugger);
        }
    }
}
