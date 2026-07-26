using System;
using System.Runtime.InteropServices;
using System.Text;

namespace PenguLoader.Main
{
    internal interface IRegistryHandle : IDisposable
    {
        IntPtr NativeHandle { get; }
    }

    internal interface IRegistryApi
    {
        int OpenLocalMachine(
            string path,
            uint desiredAccess,
            out IRegistryHandle handle);

        int CreateSubKey(
            IRegistryHandle parent,
            string name,
            uint desiredAccess,
            out IRegistryHandle handle,
            out uint disposition);

        int QueryString(
            IRegistryHandle key,
            string valueName,
            out string value);

        int SetString(
            IRegistryHandle key,
            string valueName,
            string value);

        int DeleteValue(
            IRegistryHandle key,
            string valueName);

        int DeleteSubKey(
            IRegistryHandle parent,
            string name);
    }

    internal static class Win32Registry
    {
        internal static readonly UIntPtr HKEY_LOCAL_MACHINE =
            new UIntPtr(0x80000002u);

        internal const int ERROR_SUCCESS = 0;
        internal const int ERROR_FILE_NOT_FOUND = 2;
        internal const int ERROR_PATH_NOT_FOUND = 3;
        internal const int ERROR_INVALID_DATA = 13;

        internal const uint KEY_QUERY_VALUE = 0x0001;
        internal const uint KEY_SET_VALUE = 0x0002;
        internal const uint KEY_CREATE_SUB_KEY = 0x0004;
        internal const uint KEY_WRITE = 0x20006;

        internal const uint REG_OPTION_NON_VOLATILE = 0x00000000;
        internal const uint REG_SZ = 1;

        internal const uint REG_CREATED_NEW_KEY = 1;
        internal const uint REG_OPENED_EXISTING_KEY = 2;
    }

    internal sealed class Win32RegistryApi : IRegistryApi
    {
        public int OpenLocalMachine(
            string path,
            uint desiredAccess,
            out IRegistryHandle handle)
        {
            IntPtr nativeHandle;
            var result = RegOpenKeyExW(
                Win32Registry.HKEY_LOCAL_MACHINE,
                path,
                0,
                desiredAccess,
                out nativeHandle);

            handle = result == Win32Registry.ERROR_SUCCESS
                ? new Win32RegistryHandle(nativeHandle)
                : null;
            return result;
        }

        public int CreateSubKey(
            IRegistryHandle parent,
            string name,
            uint desiredAccess,
            out IRegistryHandle handle,
            out uint disposition)
        {
            IntPtr nativeHandle;
            var result = RegCreateKeyExW(
                parent.NativeHandle,
                name,
                0,
                null,
                Win32Registry.REG_OPTION_NON_VOLATILE,
                desiredAccess,
                IntPtr.Zero,
                out nativeHandle,
                out disposition);

            handle = result == Win32Registry.ERROR_SUCCESS
                ? new Win32RegistryHandle(nativeHandle)
                : null;
            return result;
        }

        public int QueryString(
            IRegistryHandle key,
            string valueName,
            out string value)
        {
            value = null;
            uint type;
            uint dataSize = 0;
            var result = RegQueryValueExW(
                key.NativeHandle,
                valueName,
                IntPtr.Zero,
                out type,
                IntPtr.Zero,
                ref dataSize);

            if (result != Win32Registry.ERROR_SUCCESS)
                return result;

            if (type != Win32Registry.REG_SZ)
                return Win32Registry.ERROR_INVALID_DATA;

            if (dataSize == 0)
            {
                value = string.Empty;
                return Win32Registry.ERROR_SUCCESS;
            }

            var buffer = Marshal.AllocHGlobal((int)dataSize);
            try
            {
                result = RegQueryValueExW(
                    key.NativeHandle,
                    valueName,
                    IntPtr.Zero,
                    out type,
                    buffer,
                    ref dataSize);
                if (result != Win32Registry.ERROR_SUCCESS)
                    return result;

                if (type != Win32Registry.REG_SZ)
                    return Win32Registry.ERROR_INVALID_DATA;

                var bytes = new byte[dataSize];
                Marshal.Copy(buffer, bytes, 0, (int)dataSize);
                value = Encoding.Unicode.GetString(bytes).TrimEnd('\0');
                return Win32Registry.ERROR_SUCCESS;
            }
            finally
            {
                Marshal.FreeHGlobal(buffer);
            }
        }

        public int SetString(
            IRegistryHandle key,
            string valueName,
            string value)
        {
            var bytes = Encoding.Unicode.GetBytes((value ?? string.Empty) + "\0");
            return RegSetValueExW(
                key.NativeHandle,
                valueName,
                0,
                Win32Registry.REG_SZ,
                bytes,
                (uint)bytes.Length);
        }

        public int DeleteValue(
            IRegistryHandle key,
            string valueName)
        {
            return RegDeleteValueW(key.NativeHandle, valueName);
        }

        public int DeleteSubKey(
            IRegistryHandle parent,
            string name)
        {
            return RegDeleteKeyW(parent.NativeHandle, name);
        }

        [DllImport("advapi32.dll", EntryPoint = "RegOpenKeyExW", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern int RegOpenKeyExW(
            UIntPtr hKey,
            string lpSubKey,
            uint ulOptions,
            uint samDesired,
            out IntPtr phkResult);

        [DllImport("advapi32.dll", EntryPoint = "RegCreateKeyExW", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern int RegCreateKeyExW(
            IntPtr hKey,
            string lpSubKey,
            uint reserved,
            string lpClass,
            uint dwOptions,
            uint samDesired,
            IntPtr lpSecurityAttributes,
            out IntPtr phkResult,
            out uint lpdwDisposition);

        [DllImport("advapi32.dll", EntryPoint = "RegQueryValueExW", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern int RegQueryValueExW(
            IntPtr hKey,
            string lpValueName,
            IntPtr lpReserved,
            out uint lpType,
            IntPtr lpData,
            ref uint lpcbData);

        [DllImport("advapi32.dll", EntryPoint = "RegSetValueExW", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern int RegSetValueExW(
            IntPtr hKey,
            string lpValueName,
            uint reserved,
            uint dwType,
            [MarshalAs(UnmanagedType.LPArray, SizeParamIndex = 5)] byte[] lpData,
            uint cbData);

        [DllImport("advapi32.dll", EntryPoint = "RegDeleteValueW", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern int RegDeleteValueW(
            IntPtr hKey,
            string lpValueName);

        [DllImport("advapi32.dll", EntryPoint = "RegDeleteKeyW", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern int RegDeleteKeyW(
            IntPtr hKey,
            string lpSubKey);

        [DllImport("advapi32.dll", EntryPoint = "RegCloseKey", SetLastError = true)]
        private static extern int RegCloseKey(IntPtr hKey);

        private sealed class Win32RegistryHandle : IRegistryHandle
        {
            private IntPtr _handle;

            public Win32RegistryHandle(IntPtr handle)
            {
                _handle = handle;
            }

            public IntPtr NativeHandle => _handle;

            public void Dispose()
            {
                if (_handle == IntPtr.Zero)
                    return;

                RegCloseKey(_handle);
                _handle = IntPtr.Zero;
            }
        }
    }
}
