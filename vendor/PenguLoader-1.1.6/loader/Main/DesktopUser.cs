using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

namespace PenguLoader.Main
{
    /// <summary>
    /// Detects the desktop user (the user logged into the Windows session)
    /// by finding explorer.exe and extracting the user's profile path.
    /// This handles the case where Rose/Loader runs elevated as Admin
    /// but League runs as the regular desktop user.
    /// </summary>
    static class DesktopUser
    {
        // Cache the result since it won't change during execution
        private static string _cachedLocalAppData;
        private static string _cachedUsername;
        private static bool _initialized;
        private static bool _hasMismatch;

        #region Windows API

        [DllImport("advapi32.dll", SetLastError = true)]
        private static extern bool OpenProcessToken(IntPtr ProcessHandle, uint DesiredAccess, out IntPtr TokenHandle);

        [DllImport("advapi32.dll", SetLastError = true)]
        private static extern bool GetTokenInformation(IntPtr TokenHandle, int TokenInformationClass, IntPtr TokenInformation, uint TokenInformationLength, out uint ReturnLength);

        [DllImport("advapi32.dll", CharSet = CharSet.Auto, SetLastError = true)]
        private static extern bool LookupAccountSid(string lpSystemName, IntPtr Sid, StringBuilder lpName, ref uint cchName, StringBuilder lpReferencedDomainName, ref uint cchReferencedDomainName, out int peUse);

        [DllImport("userenv.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool GetUserProfileDirectory(IntPtr hToken, StringBuilder lpProfileDir, ref uint lpcchSize);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CloseHandle(IntPtr hObject);

        private const uint TOKEN_QUERY = 0x0008;
        private const int TokenUser = 1;

        [StructLayout(LayoutKind.Sequential)]
        private struct TOKEN_USER
        {
            public SID_AND_ATTRIBUTES User;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct SID_AND_ATTRIBUTES
        {
            public IntPtr Sid;
            public uint Attributes;
        }

        #endregion

        /// <summary>
        /// Initialize desktop user detection. Call this early in startup.
        /// </summary>
        public static void Initialize()
        {
            if (_initialized) return;
            _initialized = true;

            try
            {
                var currentUser = Environment.UserName;
                var desktopInfo = GetDesktopUserInfo();

                if (desktopInfo.HasValue)
                {
                    _cachedUsername = desktopInfo.Value.Username;
                    _cachedLocalAppData = Path.Combine(desktopInfo.Value.ProfilePath, "AppData", "Local");

                    // Check if there's a mismatch
                    if (!string.Equals(currentUser, _cachedUsername, StringComparison.OrdinalIgnoreCase))
                    {
                        _hasMismatch = true;
                        Logger.Warn("DesktopUser", $"User mismatch detected: Running as '{currentUser}', using '{_cachedUsername}' data directory");
                        Logger.Info("DesktopUser", $"Desktop user LocalAppData: {_cachedLocalAppData}");
                    }
                    else
                    {
                        Logger.Debug("DesktopUser", $"No user mismatch. Current user: {currentUser}");
                    }
                }
                else
                {
                    Logger.Debug("DesktopUser", "Could not detect desktop user, using current process user");
                }
            }
            catch (Exception ex)
            {
                Logger.Error("DesktopUser", "Failed to initialize desktop user detection", ex);
            }
        }

        /// <summary>
        /// Gets the LocalAppData path for the desktop user.
        /// If running as a different user (e.g., Admin), returns the desktop user's AppData.
        /// </summary>
        public static string GetLocalAppData()
        {
            if (!_initialized)
                Initialize();

            if (!string.IsNullOrEmpty(_cachedLocalAppData) && Directory.Exists(_cachedLocalAppData))
            {
                return _cachedLocalAppData;
            }

            // Fallback to current process user
            return Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        }

        /// <summary>
        /// Gets whether there is a user mismatch (running as different user than desktop).
        /// </summary>
        public static bool HasUserMismatch => _hasMismatch;

        /// <summary>
        /// Gets the detected desktop username, or null if not detected.
        /// </summary>
        public static string DesktopUsername => _cachedUsername;

        /// <summary>
        /// Gets info about the desktop user by finding explorer.exe.
        /// Explorer.exe always runs as the logged-in desktop user.
        /// </summary>
        private static (string Username, string ProfilePath)? GetDesktopUserInfo()
        {
            try
            {
                // Find explorer.exe - it always runs as the desktop user
                var explorerProcesses = Process.GetProcessesByName("explorer");

                if (explorerProcesses.Length == 0)
                {
                    Logger.Debug("DesktopUser", "No explorer.exe process found");
                    return null;
                }

                foreach (var explorer in explorerProcesses)
                {
                    try
                    {
                        var info = GetProcessUserInfo(explorer);
                        if (info.HasValue)
                        {
                            Logger.Debug("DesktopUser", $"Found desktop user: {info.Value.Username}, Profile: {info.Value.ProfilePath}");
                            return info;
                        }
                    }
                    catch (Exception ex)
                    {
                        Logger.Debug("DesktopUser", $"Failed to get info from explorer process {explorer.Id}: {ex.Message}");
                    }
                    finally
                    {
                        explorer.Dispose();
                    }
                }
            }
            catch (Exception ex)
            {
                Logger.Error("DesktopUser", "Failed to find desktop user", ex);
            }

            return null;
        }

        /// <summary>
        /// Gets the username and profile path for a given process.
        /// </summary>
        private static (string Username, string ProfilePath)? GetProcessUserInfo(Process process)
        {
            IntPtr tokenHandle = IntPtr.Zero;

            try
            {
                // Open the process token
                if (!OpenProcessToken(process.Handle, TOKEN_QUERY, out tokenHandle))
                {
                    var error = Marshal.GetLastWin32Error();
                    Logger.Debug("DesktopUser", $"OpenProcessToken failed with error {error}");
                    return null;
                }

                // Get the username from the token
                string username = GetTokenUsername(tokenHandle);
                if (string.IsNullOrEmpty(username))
                {
                    Logger.Debug("DesktopUser", "Failed to get username from token");
                    return null;
                }

                // Get the profile directory
                uint profileDirSize = 260;
                var profileDir = new StringBuilder((int)profileDirSize);

                if (!GetUserProfileDirectory(tokenHandle, profileDir, ref profileDirSize))
                {
                    // Try again with larger buffer
                    profileDir = new StringBuilder((int)profileDirSize);
                    if (!GetUserProfileDirectory(tokenHandle, profileDir, ref profileDirSize))
                    {
                        var error = Marshal.GetLastWin32Error();
                        Logger.Debug("DesktopUser", $"GetUserProfileDirectory failed with error {error}");
                        return null;
                    }
                }

                return (username, profileDir.ToString());
            }
            finally
            {
                if (tokenHandle != IntPtr.Zero)
                    CloseHandle(tokenHandle);
            }
        }

        /// <summary>
        /// Gets the username from a token handle.
        /// </summary>
        private static string GetTokenUsername(IntPtr tokenHandle)
        {
            uint tokenInfoLength = 0;

            // First call to get required buffer size
            GetTokenInformation(tokenHandle, TokenUser, IntPtr.Zero, 0, out tokenInfoLength);

            if (tokenInfoLength == 0)
                return null;

            IntPtr tokenInfo = Marshal.AllocHGlobal((int)tokenInfoLength);
            try
            {
                if (!GetTokenInformation(tokenHandle, TokenUser, tokenInfo, tokenInfoLength, out tokenInfoLength))
                    return null;

                var tokenUser = Marshal.PtrToStructure<TOKEN_USER>(tokenInfo);

                uint nameSize = 256;
                uint domainSize = 256;
                var name = new StringBuilder((int)nameSize);
                var domain = new StringBuilder((int)domainSize);

                if (!LookupAccountSid(null, tokenUser.User.Sid, name, ref nameSize, domain, ref domainSize, out _))
                    return null;

                return name.ToString();
            }
            finally
            {
                Marshal.FreeHGlobal(tokenInfo);
            }
        }
    }
}
