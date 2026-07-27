using System;
using System.Linq;
using System.Threading;
using System.Windows;
using PenguLoader.Main;

namespace PenguLoader
{
    public static class Program
    {
        public static string Name => "Rose Loader";
        public static string HomepageUrl => "https://ko-fi.com/roseapp";
        public static string DiscordUrl => "https://discord.gg/roseskins";
        public static string GithubRepo => "Alban1911/Rose";
        public static string GithubUrl => $"https://github.com/{GithubRepo}";
        public static string GithubIssuesUrl => $"https://github.com/{GithubRepo}/issues";
        public const string VERSION = "2.0.0";

        private const int ATTACH_PARENT_PROCESS = -1;
        private const string GUI_MUTEX_NAME = "989d2110-46da-4c8d-84c1-c4a42e43c424";
        private static bool _consoleAttached;

        [System.Runtime.InteropServices.DllImport("kernel32.dll", SetLastError = true)]
        [return: System.Runtime.InteropServices.MarshalAs(System.Runtime.InteropServices.UnmanagedType.Bool)]
        private static extern bool AttachConsole(int processId);

        [STAThread]
        private static int Main(string[] args)
        {
            try
            {
                var dataStorePath = args.FirstOrDefault(DataStore.IsDataStore);
                if (dataStorePath != null)
                {
                    DataStore.DumpDataStore(dataStorePath);
                    return 0;
                }

                var silent = args.Any(IsSilentArgument);
                var command = args.FirstOrDefault(argument =>
                    !IsSilentArgument(argument) &&
                    (argument.StartsWith("--", StringComparison.Ordinal) ||
                     argument.StartsWith("/", StringComparison.Ordinal)));

                using (var mutex = new Mutex(true, GUI_MUTEX_NAME, out var createdNew))
                {
                    switch ((command ?? string.Empty).ToLowerInvariant())
                    {
                        case "--install":
                        case "/install":
                            return HandleInstall(createdNew, true, silent);
                        case "--uninstall":
                        case "/uninstall":
                            return HandleInstall(createdNew, false, silent);
                        case "--status":
                            return HandleStatus(silent);
                        case "--set-league-path":
                            return HandleSetLeaguePath(args, silent);
                        case "--restart-client":
                            return HandleRestartClient(silent);
                        case "--help":
                        case "-h":
                        case "/?":
                            return Notify("Rose Loader " + VERSION + "\n\nCommands: --install, --uninstall, --status, --set-league-path <path>, --restart-client", silent, MessageBoxImage.None);
                        default:
                            return RunApplication(createdNew);
                    }
                }
            }
            catch (Exception ex)
            {
                return Notify("Failed to perform the requested operation.\n\n" + ex.Message,
                    args.Any(IsSilentArgument), MessageBoxImage.Error, 1);
            }
        }

        private static int RunApplication(bool createdNew)
        {
            if (!createdNew)
            {
                Native.SetFocusToPreviousInstance();
                return 0;
            }

            if (!Environment.Is64BitOperatingSystem)
            {
                MessageBox.Show("32-BIT CLIENT DEPRECATION\n\nStarting with LoL patch 13.8, 32-bit Windows is no longer supported. Please upgrade your Windows to 64-bit.",
                    Name, MessageBoxButton.OK, MessageBoxImage.Warning);
                return 1;
            }

            App.Main();
            return 0;
        }

        private static int HandleInstall(bool createdNew, bool active, bool silent)
        {
            // Activation must not replace a module that is already loaded.
            // Deactivation is safe here: Rose removes IFEO first, then restarts
            // the League client so the loaded module is unloaded.
            if (!createdNew || (active && Module.IsLoaded))
            {
                var action = active ? "installing" : "uninstalling";
                return Notify("Please close the running League Client and Loader menu before " + action + " it.",
                    silent, MessageBoxImage.Information, -1);
            }

            if (!Module.SetActive(active))
                return Notify("Failed to " + (active ? "activate" : "deactivate") + " Rose.", silent, MessageBoxImage.Error, 1);

            return Notify("Pengu has been " + (active ? "activated" : "deactivated") + ".",
                silent, MessageBoxImage.Information);
        }

        private static int HandleStatus(bool silent)
        {
            var active = Module.IsFound && Module.IsActivated;
            Notify("Pengu is currently " + (active ? "ACTIVE" : "INACTIVE") + ".", silent,
                active ? MessageBoxImage.Information : MessageBoxImage.None);
            return active ? 0 : 1;
        }

        private static int HandleSetLeaguePath(string[] args, bool silent)
        {
            var commandIndex = Array.FindIndex(args, argument =>
                string.Equals(argument, "--set-league-path", StringComparison.OrdinalIgnoreCase));
            if (commandIndex < 0 || commandIndex + 1 >= args.Length)
                return Notify("Usage: --set-league-path <path>", silent, MessageBoxImage.Warning, 1);

            var path = args[commandIndex + 1].Trim();
            if (!LCU.IsValidDir(path))
                return Notify("'" + path + "' does not appear to be a valid League of Legends directory.",
                    silent, MessageBoxImage.Error, 1);

            Config.LeaguePath = path;
            return Notify("League of Legends path set to '" + path + "'.", silent, MessageBoxImage.Information);
        }

        private static int HandleRestartClient(bool silent)
        {
            if (!LCU.IsRunning)
                return Notify("League Client UX is not running.", silent, MessageBoxImage.Warning, 1);

            LCU.KillUxAndRestart().GetAwaiter().GetResult();
            return Notify("Requested the League Client UX to restart.", silent, MessageBoxImage.Information);
        }

        private static int Notify(string message, bool silent, MessageBoxImage image, int code = 0)
        {
            if (silent)
            {
                try
                {
                    if (!_consoleAttached)
                        _consoleAttached = AttachConsole(ATTACH_PARENT_PROCESS);
                    if (_consoleAttached)
                        Console.Out.WriteLine(message);
                }
                catch { }
                return code;
            }

            MessageBox.Show(message, Name, MessageBoxButton.OK, image);
            return code;
        }

        private static bool IsSilentArgument(string argument)
        {
            return string.Equals(argument, "--silent", StringComparison.OrdinalIgnoreCase) ||
                   string.Equals(argument, "-s", StringComparison.OrdinalIgnoreCase) ||
                   string.Equals(argument, "/silent", StringComparison.OrdinalIgnoreCase);
        }
    }
}
