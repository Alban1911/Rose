using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

namespace PenguLoader.Main
{
    internal static class Symlink
    {
        public static bool Create(string linkPath, string sourcePath)
        {
            return CreateSymbolicLink(linkPath, sourcePath, 0);
        }

        public static string Resolve(string path)
        {
            if (!IsSymlink(path))
                return path;

            var h = CreateFile(path,
                FILE_READ_EA,
                FileShare.ReadWrite | FileShare.Delete,
                IntPtr.Zero,
                FileMode.Open,
                FILE_FLAG_BACKUP_SEMANTICS,
                IntPtr.Zero);

            if (h == (IntPtr)(-1))
                return null;

            try
            {
                var sb = new StringBuilder(2048);
                var res = GetFinalPathNameByHandle(h, sb, sb.Capacity, 0);
                if (res == 0)
                    return null;

                return sb.ToString().Replace("\\\\?\\", "");
            }
            finally
            {
                CloseHandle(h);
            }
        }

        public static bool IsSymlink(string path)
        {
            if (!File.Exists(path))
                return false;

            var pathInfo = new FileInfo(path);
            return pathInfo.Attributes.HasFlag(FileAttributes.ReparsePoint);
        }

        private const uint FILE_READ_EA = 0x0008;
        private const uint FILE_FLAG_BACKUP_SEMANTICS = 0x2000000;

        [DllImport("kernel32.dll", EntryPoint = "GetFinalPathNameByHandleW", CharSet = CharSet.Unicode)]
        private static extern uint GetFinalPathNameByHandle(IntPtr hFile,
            [MarshalAs(UnmanagedType.LPWStr)] StringBuilder lpszFilePath, int cchFilePath, uint dwFlags);

        [DllImport("kernel32.dll", EntryPoint = "CloseHandle")]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool CloseHandle(IntPtr hObject);

        [DllImport("kernel32.dll", EntryPoint = "CreateFileW", CharSet = CharSet.Unicode)]
        private static extern IntPtr CreateFile(
                [MarshalAs(UnmanagedType.LPWStr)] string filename,
                [MarshalAs(UnmanagedType.U4)] uint access,
                [MarshalAs(UnmanagedType.U4)] FileShare share,
                IntPtr securityAttributes, // optional SECURITY_ATTRIBUTES struct or IntPtr.Zero
                [MarshalAs(UnmanagedType.U4)] FileMode creationDisposition,
                [MarshalAs(UnmanagedType.U4)] uint flagsAndAttributes,
                IntPtr templateFile);

        [DllImport("kernel32.dll", EntryPoint = "CreateSymbolicLinkW", CharSet = CharSet.Unicode)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool CreateSymbolicLink(string lpSymlinkFileName, string lpTargetFileName, uint dwFlags);
    }
}