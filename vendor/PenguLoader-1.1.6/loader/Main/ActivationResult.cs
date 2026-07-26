using System;
using System.ComponentModel;

namespace PenguLoader.Main
{
    internal enum ActivationStage : byte
    {
        None = 0, OpenIFEO = 1, CreateTarget = 2, SetDebugger = 3,
        DeleteDebugger = 4, GetLeaguePath = 5, CreateSymlink = 6,
        DeleteSymlink = 7, RunElevated = 8
    }

    internal enum ActivationErrorKind : byte
    {
        None = 0, NotFound = 1, PermissionDenied = 2, AlreadyExists = 3,
        InvalidInput = 4, Cancelled = 5, Other = 255
    }

    internal sealed class ActivationResult
    {
        private ActivationResult(bool succeeded, ActivationStage stage, ActivationErrorKind errorKind,
            int nativeErrorCode, string nativeErrorMessage)
        {
            Succeeded = succeeded;
            Stage = stage;
            ErrorKind = errorKind;
            NativeErrorCode = nativeErrorCode;
            NativeErrorMessage = nativeErrorMessage ?? string.Empty;
        }

        public bool Succeeded { get; }
        public ActivationStage Stage { get; }
        public ActivationErrorKind ErrorKind { get; }
        public int NativeErrorCode { get; }
        public string NativeErrorMessage { get; }

        public static ActivationResult Success()
        {
            return new ActivationResult(true, ActivationStage.None, ActivationErrorKind.None, 0, string.Empty);
        }

        public static ActivationResult Failure(ActivationStage stage, ActivationErrorKind errorKind,
            int nativeErrorCode, string nativeErrorMessage)
        {
            return new ActivationResult(false, stage, errorKind, nativeErrorCode, nativeErrorMessage);
        }

        public static ActivationResult FromWin32(ActivationStage stage, int nativeErrorCode, string nativeErrorMessage = null)
        {
            var message = nativeErrorMessage;
            if (string.IsNullOrEmpty(message))
            {
                try { message = new Win32Exception(nativeErrorCode).Message; }
                catch { message = "Windows error " + nativeErrorCode; }
            }
            return Failure(stage, MapWin32Error(nativeErrorCode), nativeErrorCode, message);
        }

        public int EncodeExitCode()
        {
            return Succeeded ? 0 : ((int)(byte)Stage << 8) | (int)(byte)ErrorKind;
        }

        public static ActivationResult DecodeExitCode(int exitCode)
        {
            if (exitCode == 0) return Success();
            var unsignedExitCode = unchecked((uint)exitCode);
            return Failure((ActivationStage)((unsignedExitCode >> 8) & 0xff),
                (ActivationErrorKind)(unsignedExitCode & 0xff), 0, string.Empty);
        }

        public string ToOfficialStyleString()
        {
            return Succeeded ? "Success" : StageName(Stage) + " (" + ErrorKindName(ErrorKind) + ")";
        }

        // Keeps older UI call sites source-compatible while they migrate to
        // the structured result. New code should inspect Succeeded directly.
        public static implicit operator bool(ActivationResult result)
        {
            return result != null && result.Succeeded;
        }

        internal static ActivationErrorKind MapWin32Error(int nativeErrorCode)
        {
            switch (nativeErrorCode)
            {
                case 0: return ActivationErrorKind.Other;
                case 2: case 3: return ActivationErrorKind.NotFound;
                case 5: return ActivationErrorKind.PermissionDenied;
                case 87: return ActivationErrorKind.InvalidInput;
                case 183: return ActivationErrorKind.AlreadyExists;
                case 1223: return ActivationErrorKind.Cancelled;
                default: return ActivationErrorKind.Other;
            }
        }

        internal static string StageName(ActivationStage stage)
        {
            switch (stage)
            {
                case ActivationStage.None: return "None";
                case ActivationStage.OpenIFEO: return "OpenIFEO";
                case ActivationStage.CreateTarget: return "CreateTarget";
                case ActivationStage.SetDebugger: return "SetDebugger";
                case ActivationStage.DeleteDebugger: return "DeleteDebugger";
                case ActivationStage.GetLeaguePath: return "GetLeaguePath";
                case ActivationStage.CreateSymlink: return "CreateSymlink";
                case ActivationStage.DeleteSymlink: return "DeleteSymlink";
                case ActivationStage.RunElevated: return "RunElevated";
                default: return "Stage" + (byte)stage;
            }
        }

        internal static string ErrorKindName(ActivationErrorKind errorKind)
        {
            switch (errorKind)
            {
                case ActivationErrorKind.None: return "none";
                case ActivationErrorKind.NotFound: return "not_found";
                case ActivationErrorKind.PermissionDenied: return "permission_denied";
                case ActivationErrorKind.AlreadyExists: return "already_exists";
                case ActivationErrorKind.InvalidInput: return "invalid_input";
                case ActivationErrorKind.Cancelled: return "cancelled";
                case ActivationErrorKind.Other: return "other";
                default: return "error_" + (byte)errorKind;
            }
        }
    }
}
