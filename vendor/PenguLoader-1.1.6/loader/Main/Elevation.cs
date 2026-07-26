using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Security.Principal;

namespace PenguLoader.Main
{
    internal interface IElevatedProcessRunner
    {
        ElevatedProcessResult Run(string executable, string arguments, string workingDirectory);
    }

    internal sealed class ElevatedProcessResult
    {
        private ElevatedProcessResult(bool started, int exitCode, int nativeErrorCode, string errorMessage)
        {
            Started = started;
            ExitCode = exitCode;
            NativeErrorCode = nativeErrorCode;
            ErrorMessage = errorMessage ?? string.Empty;
        }

        public bool Started { get; }
        public int ExitCode { get; }
        public int NativeErrorCode { get; }
        public string ErrorMessage { get; }

        public static ElevatedProcessResult Completed(int exitCode)
        {
            return new ElevatedProcessResult(true, exitCode, 0, string.Empty);
        }

        public static ElevatedProcessResult Failed(int nativeErrorCode, string errorMessage)
        {
            return new ElevatedProcessResult(false, -1, nativeErrorCode, errorMessage);
        }
    }

    internal static class Elevation
    {
        private static IElevatedProcessRunner _processRunner = new ShellElevatedProcessRunner();

        internal static IElevatedProcessRunner ProcessRunner
        {
            get { return _processRunner; }
            set { _processRunner = value ?? new ShellElevatedProcessRunner(); }
        }

        public static bool IsAdministrator()
        {
            try
            {
                using (var identity = WindowsIdentity.GetCurrent())
                {
                    return new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator);
                }
            }
            catch (Exception ex)
            {
                Logger.Error("Elevation", "Failed to determine administrator membership", ex);
                return false;
            }
        }

        internal static Func<bool> IsElevatedOverride { get; set; }

        public static bool IsElevated()
        {
            var overrideValue = IsElevatedOverride;
            if (overrideValue != null)
                return overrideValue();

            return IsElevatedCore();
        }

        private static bool IsElevatedCore()
        {
            try
            {
                // TokenElevation can be true for an administrator token that
                // still has only Medium integrity. HKLM writes require High.
                var integrityLevel = GetIntegrityLevel();
                return string.Equals(integrityLevel, "High", StringComparison.Ordinal) ||
                    string.Equals(integrityLevel, "System", StringComparison.Ordinal) ||
                    string.Equals(integrityLevel, "Protected", StringComparison.Ordinal);
            }
            catch (Exception ex)
            {
                Logger.Error("Elevation", "Failed to determine token elevation", ex);
            }
            return false;
        }

        public static string GetProcessUser()
        {
            try
            {
                using (var identity = WindowsIdentity.GetCurrent())
                    return identity.Name ?? string.Empty;
            }
            catch { return string.Empty; }
        }

        public static string GetIntegrityLevel()
        {
            try
            {
                using (var identity = WindowsIdentity.GetCurrent())
                {
                    var tokenLevel = GetTokenIntegrityLevel(identity.Token);
                    if (!string.IsNullOrEmpty(tokenLevel))
                        return tokenLevel;

                    if (identity.Groups != null)
                    {
                        foreach (var group in identity.Groups)
                        {
                            var parts = group.Value.Split('-');
                            uint rid;
                            if (parts.Length == 0 || !uint.TryParse(parts[parts.Length - 1], out rid))
                                continue;
                            var level = GetIntegrityLevelName(rid);
                            if (!level.StartsWith("Unknown(", StringComparison.Ordinal))
                                return level;
                        }
                    }
                }
            }
            catch { }
            return "Unknown";
        }

        public static ActivationResult RunElevated(bool active, bool silent)
        {
            var executable = GetCurrentExecutablePath();
            var arguments = active ? "--install --silent" : "--uninstall --silent";
            var workingDirectory = AppDomain.CurrentDomain.BaseDirectory;
            Logger.Info("Elevation", "Launching elevated child");
            Logger.Info("Elevation", "Executable=" + executable);
            Logger.Info("Elevation", "Arguments=" + arguments);
            Logger.Info("Elevation", "Verb=runas");

            ElevatedProcessResult processResult;
            try
            {
                processResult = ProcessRunner.Run(executable, arguments, workingDirectory);
            }
            catch (Win32Exception ex)
            {
                return LogProcessFailure(ex.NativeErrorCode, ex.Message);
            }
            catch (Exception ex)
            {
                Logger.Error("Elevation", "Failed to launch elevated child", ex);
                return ActivationResult.Failure(ActivationStage.RunElevated, ActivationErrorKind.Other, 0, ex.Message);
            }

            if (processResult == null || !processResult.Started)
            {
                return LogProcessFailure(
                    processResult == null ? 0 : processResult.NativeErrorCode,
                    processResult == null ? "The elevated process did not start." : processResult.ErrorMessage);
            }

            Logger.Info("Elevation", "Child exited exitCode=" + processResult.ExitCode);
            var result = ActivationResult.DecodeExitCode(processResult.ExitCode);
            if (!result.Succeeded)
            {
                Logger.Error("Elevation", "Decoded failure stage=" + ActivationResult.StageName(result.Stage) +
                    " kind=" + ActivationResult.ErrorKindName(result.ErrorKind) +
                    " partialState=" + result.PartialState);
            }
            return result;
        }

        private static ActivationResult LogProcessFailure(int nativeErrorCode, string message)
        {
            var result = ActivationResult.FromWin32(ActivationStage.RunElevated, nativeErrorCode, message);
            Logger.Error("Elevation", "Elevated child failed win32=" + nativeErrorCode +
                " kind=" + ActivationResult.ErrorKindName(result.ErrorKind) +
                " message=\"" + result.NativeErrorMessage.Replace("\"", "'") + "\"");
            return result;
        }

        private static string GetCurrentExecutablePath()
        {
            try { return Process.GetCurrentProcess().MainModule.FileName; }
            catch { return System.Reflection.Assembly.GetEntryAssembly().Location; }
        }

        private sealed class ShellElevatedProcessRunner : IElevatedProcessRunner
        {
            public ElevatedProcessResult Run(string executable, string arguments, string workingDirectory)
            {
                var startInfo = new ProcessStartInfo
                {
                    FileName = executable,
                    Arguments = arguments,
                    Verb = "runas",
                    UseShellExecute = true,
                    WorkingDirectory = workingDirectory,
                    WindowStyle = ProcessWindowStyle.Hidden
                };
                try
                {
                    using (var process = Process.Start(startInfo))
                    {
                        if (process == null)
                            return ElevatedProcessResult.Failed(0, "Process.Start returned null.");
                        process.WaitForExit();
                        return ElevatedProcessResult.Completed(process.ExitCode);
                    }
                }
                catch (Win32Exception ex) { return ElevatedProcessResult.Failed(ex.NativeErrorCode, ex.Message); }
                catch (Exception ex) { return ElevatedProcessResult.Failed(0, ex.Message); }
            }
        }

        internal static string GetIntegrityLevelName(uint rid)
        {
            switch (rid)
            {
                case 0x0000: return "Untrusted";
                case 0x1000: return "Low";
                case 0x2000: return "Medium";
                case 0x2100: return "MediumPlus";
                case 0x3000: return "High";
                case 0x4000: return "System";
                case 0x5000: return "Protected";
                default: return "Unknown(" + rid + ")";
            }
        }
        private static string GetTokenIntegrityLevel(IntPtr token)
        {
            int length;
            GetTokenInformation(token, TOKEN_INFORMATION_CLASS.TokenIntegrityLevel, IntPtr.Zero, 0, out length);
            if (length <= 0)
                return null;

            var buffer = System.Runtime.InteropServices.Marshal.AllocHGlobal(length);
            try
            {
                if (!GetTokenInformation(token, TOKEN_INFORMATION_CLASS.TokenIntegrityLevel, buffer, length, out length))
                    return null;

                var sidPointer = System.Runtime.InteropServices.Marshal.ReadIntPtr(buffer);
                var sid = new SecurityIdentifier(sidPointer);
                var sidParts = sid.Value.Split('-');
                uint rid;
                if (sidParts.Length == 0 || !uint.TryParse(sidParts[sidParts.Length - 1], out rid))
                    return null;
                return GetIntegrityLevelName(rid);
            }
            catch
            {
                return null;
            }
            finally
            {
                System.Runtime.InteropServices.Marshal.FreeHGlobal(buffer);
            }
        }
        private enum TOKEN_INFORMATION_CLASS { TokenElevation = 20, TokenIntegrityLevel = 25 }

        [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
        private struct TOKEN_ELEVATION { public uint TokenIsElevated; }

        [System.Runtime.InteropServices.DllImport("advapi32.dll", SetLastError = true)]
        [return: System.Runtime.InteropServices.MarshalAs(System.Runtime.InteropServices.UnmanagedType.Bool)]
        private static extern bool GetTokenInformation(
            IntPtr tokenHandle,
            TOKEN_INFORMATION_CLASS tokenInformationClass,
            out TOKEN_ELEVATION tokenInformation,
            int tokenInformationLength,
            out int returnLength);
        [System.Runtime.InteropServices.DllImport("advapi32.dll", SetLastError = true)]
        [return: System.Runtime.InteropServices.MarshalAs(System.Runtime.InteropServices.UnmanagedType.Bool)]
        private static extern bool GetTokenInformation(
            IntPtr tokenHandle,
            TOKEN_INFORMATION_CLASS tokenInformationClass,
            IntPtr tokenInformation,
            int tokenInformationLength,
            out int returnLength);
    }
}
