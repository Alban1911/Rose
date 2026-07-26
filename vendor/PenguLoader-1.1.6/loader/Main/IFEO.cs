using System;

namespace PenguLoader.Main
{
    internal static class IFEO
    {
        internal const string IFEO_PATH =
            @"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options";
        internal const string VALUE_NAME = "Debugger";

        private static IRegistryApi _registryApi = new Win32RegistryApi();

        internal static IRegistryApi RegistryApi
        {
            get { return _registryApi; }
            set { _registryApi = value ?? new Win32RegistryApi(); }
        }

        public static ActivationResult Activate(string target, string modulePath)
        {
            IRegistryHandle ifeoHandle;
            Logger.Debug(
                "IFEO",
                "stage=OpenIFEO path=\"" + IFEO_PATH +
                "\" access=KEY_CREATE_SUB_KEY(0x0004)");
            var result = RegistryApi.OpenLocalMachine(
                IFEO_PATH,
                Win32Registry.KEY_CREATE_SUB_KEY,
                out ifeoHandle);
            if (result != Win32Registry.ERROR_SUCCESS)
                return NativeFailure(ActivationStage.OpenIFEO, result);

            Logger.Info("IFEO", "stage=OpenIFEO succeeded");

            using (ifeoHandle)
            {
                IRegistryHandle targetHandle;
                uint disposition;
                Logger.Debug(
                    "IFEO",
                    "stage=CreateTarget target=\"" + target +
                    "\" access=KEY_SET_VALUE(0x0002)");
                result = RegistryApi.CreateSubKey(
                    ifeoHandle,
                    target,
                    Win32Registry.KEY_SET_VALUE,
                    out targetHandle,
                    out disposition);
                if (result != Win32Registry.ERROR_SUCCESS)
                    return NativeFailure(ActivationStage.CreateTarget, result);

                Logger.Info(
                    "IFEO",
                    "stage=CreateTarget succeeded disposition=" +
                    (disposition == Win32Registry.REG_CREATED_NEW_KEY
                        ? "created_new"
                        : "opened_existing"));

                using (targetHandle)
                {
                    var value = BuildDebuggerCommand(modulePath);
                    Logger.Debug(
                        "IFEO",
                        "stage=SetDebugger valueName=\"Debugger\" valueType=REG_SZ dllPath=\"" +
                        modulePath + "\" entry=\"#6000\"");
                    result = RegistryApi.SetString(targetHandle, VALUE_NAME, value);
                    if (result != Win32Registry.ERROR_SUCCESS)
                        return NativeFailure(ActivationStage.SetDebugger, result);

                    Logger.Info("IFEO", "stage=SetDebugger succeeded");
                    return ActivationResult.Success();
                }
            }
        }

        public static ActivationResult Deactivate(string target)
        {
            var targetPath = IFEO_PATH + "\\" + target;
            IRegistryHandle targetHandle;
            Logger.Debug(
                "IFEO",
                "stage=DeleteDebugger access=KEY_SET_VALUE(0x0002)");
            var result = RegistryApi.OpenLocalMachine(
                targetPath,
                Win32Registry.KEY_SET_VALUE,
                out targetHandle);
            if (result == Win32Registry.ERROR_FILE_NOT_FOUND ||
                result == Win32Registry.ERROR_PATH_NOT_FOUND)
            {
                Logger.Info(
                    "IFEO",
                    "Debugger value was already absent; treating deactivation as successful");
                return ActivationResult.Success();
            }

            if (result != Win32Registry.ERROR_SUCCESS)
                return NativeFailure(ActivationStage.DeleteDebugger, result);

            using (targetHandle)
            {
                result = RegistryApi.DeleteValue(targetHandle, VALUE_NAME);
                if (result == Win32Registry.ERROR_FILE_NOT_FOUND)
                {
                    Logger.Info(
                        "IFEO",
                        "Debugger value was already absent; treating deactivation as successful");
                    return ActivationResult.Success();
                }

                if (result != Win32Registry.ERROR_SUCCESS)
                    return NativeFailure(ActivationStage.DeleteDebugger, result);

                Logger.Info("IFEO", "Debugger value deleted; target key preserved");
                return ActivationResult.Success();
            }
        }

        public static bool IsActivated(string target, string modulePath)
        {
            var targetPath = IFEO_PATH + "\\" + target;
            IRegistryHandle targetHandle;
            var result = RegistryApi.OpenLocalMachine(
                targetPath,
                Win32Registry.KEY_QUERY_VALUE,
                out targetHandle);
            var targetExists = result == Win32Registry.ERROR_SUCCESS;
            Logger.Debug("IFEO", "Query target key exists=" + targetExists.ToString().ToLowerInvariant());
            if (!targetExists)
                return false;

            using (targetHandle)
            {
                string debugger;
                result = RegistryApi.QueryString(targetHandle, VALUE_NAME, out debugger);
                var debuggerExists = result == Win32Registry.ERROR_SUCCESS;
                Logger.Debug("IFEO", "Debugger value exists=" + debuggerExists.ToString().ToLowerInvariant());
                if (!debuggerExists)
                    return false;

                if (string.IsNullOrEmpty(debugger))
                    return false;

                var usesRundll32 = debugger.StartsWith("rundll32", StringComparison.OrdinalIgnoreCase);
                Logger.Debug("IFEO", "Debugger command usesRundll32=" + usesRundll32.ToString().ToLowerInvariant());
                if (!usesRundll32)
                    return false;

                var extractedPath = ExtractQuotedPath(debugger);
                Logger.Debug("IFEO", "Extracted module path=\"" + (extractedPath ?? string.Empty) + "\"");
                Logger.Debug("IFEO", "Expected module path=\"" + modulePath + "\"");
                if (extractedPath == null)
                    return false;

                var activated = string.Equals(
                    NormalizePath(extractedPath),
                    NormalizePath(modulePath),
                    StringComparison.Ordinal);
                Logger.Debug("IFEO", "Activated=" + activated.ToString().ToLowerInvariant());
                return activated;
            }
        }

        internal static string BuildDebuggerCommand(string modulePath)
        {
            return "rundll32 \"" + modulePath + "\", #6000";
        }

        internal static string ExtractQuotedPath(string value)
        {
            if (value == null)
                return null;

            var start = value.IndexOf('"');
            if (start < 0)
                return null;

            var end = value.IndexOf('"', start + 1);
            if (end < 0)
                return null;

            return value.Substring(start + 1, end - start - 1);
        }

        internal static string NormalizePath(string path)
        {
            return path == null ? null : path.ToLowerInvariant().Replace('/', '\\');
        }

        private static ActivationResult NativeFailure(ActivationStage stage, int nativeErrorCode)
        {
            var result = ActivationResult.FromWin32(stage, nativeErrorCode);
            Logger.Error(
                "IFEO",
                "stage=" + ActivationResult.StageName(stage) +
                " failed win32=" + result.NativeErrorCode +
                " kind=" + ActivationResult.ErrorKindName(result.ErrorKind) +
                " message=\"" + result.NativeErrorMessage.Replace("\"", "'") + "\"");
            return result;
        }
    }
}
