using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
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
        private const string OPERATION_MUTEX_NAME = @"Local\Rose.Pengu.Operation";
        private static bool _consoleAttached;

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool AttachConsole(int dwProcessId);

        private static string CrashLogPath => Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "crash.log");

        private static void LogFailure(string context, string details = null, Exception ex = null)
        {
            try
            {
                var sb = new StringBuilder();
                sb.AppendLine($"[{DateTime.Now}] {context}");
                sb.AppendLine($"  Version:   {VERSION}");
                sb.AppendLine($"  BaseDir:   {AppDomain.CurrentDomain.BaseDirectory}");
                sb.AppendLine($"  OS:        {Environment.OSVersion}");
                if (details != null)
                    sb.AppendLine($"  Details:   {details}");
                if (ex != null)
                {
                    sb.AppendLine($"  Exception: {ex.GetType().Name}: {ex.Message}");
                    sb.AppendLine($"  Stack:     {ex.StackTrace}");
                }
                sb.AppendLine();
                File.AppendAllText(CrashLogPath, sb.ToString());
            }
            catch { }
        }

        [STAThread]
        private static int Main(string[] args)
        {
            try
            {
                Logger.Initialize();
                DesktopUser.Initialize();
                   Logger.LogSystemInfo();
                return MainInner(args);
            }
            catch (Exception ex)
            {
                Logger.Error("Program", "Unhandled exception in Main", ex);
                LogFailure($"Unhandled (args: {string.Join(" ", args)})", ex: ex);
                return -99;
            }
        }

        private static int MainInner(string[] args)
        {
            Logger.Info("Program", $"MainInner called with args: [{string.Join(", ", args)}]");

            var dataStorePath = args.FirstOrDefault(DataStore.IsDataStore);
            if (dataStorePath != null)
            {
                Logger.Info("Program", $"DataStore path detected: {dataStorePath}");
                DataStore.DumpDataStore(dataStorePath);
                return 0;
            }

            var silent = args.Any(IsSilentArgument);
            var commandArgs = ExtractCommandArgs(args);

            Logger.Info("Program", $"Silent mode: {silent}, Command args: [{string.Join(", ", commandArgs)}]");

            if (commandArgs.Count == 0)
            {
                Logger.Info("Program", "No command args, launching the Pengu graphical interface");
                return RunApplication();
            }

            var commandKey = commandArgs[0].ToLowerInvariant();
            Logger.Info("Program", $"Command: {commandKey}");

            switch (commandKey)
            {
                case "--install":
                case "/install":
                case "--activate":
                    return HandleInstall(true, silent);
                case "--uninstall":
                case "/uninstall":
                case "--deactivate":
                    return HandleInstall(false, silent);
                case "--status":
                    return HandleStatus(silent);
                case "--list-plugins":
                    return HandleListPlugins(silent);
                case "--toggle-plugin":
                    return HandlePluginCommand(commandArgs, null, silent);
                case "--enable-plugin":
                    return HandlePluginCommand(commandArgs, true, silent);
                case "--disable-plugin":
                    return HandlePluginCommand(commandArgs, false, silent);
                case "--set-league-path":
                    return HandleSetLeaguePath(commandArgs, silent);
                case "--get-league-path":
                    return HandleGetLeaguePath(silent);
                case "--set-option":
                    return HandleSetOption(commandArgs, silent);
                case "--restart-client":
                    return HandleRestartClient(silent);
                case "--ui":
                case "/ui":
                case "--show-ui":
                    return RunApplication();
                case "--help":
                case "-h":
                case "/?":
                    return ShowHelp(silent);
                default:
                    return NotifyResult(
                        $"Unknown command '{commandArgs[0]}'. Use --help to see available commands.",
                        silent, MessageBoxImage.Warning, -10);
            }
        }

        private static int RunApplication()
        {
            using (var mutex = new Mutex(true, GUI_MUTEX_NAME, out var createdNew))
            {
                Logger.Info("Program", $"RunApplication called, createdNew={createdNew}");

                if (!createdNew)
                {
                    Logger.Info("Program", "Another instance is running, focusing previous instance");
                    Native.SetFocusToPreviousInstance();
                    return 0;
                }

                if (!Environment.Is64BitOperatingSystem)
                {
                    Logger.Warn("Program", "32-bit OS detected, showing deprecation warning");
                    MessageBox.Show("32-BIT CLIENT DEPRECATION\n\nStarting with LoL patch 13.8, 32-bit Windows is no longer supported. Please upgrade your Windows to 64-bit.",
                        Name, MessageBoxButton.OK, MessageBoxImage.Warning);
                    return 1;
                }

                Logger.Info("Program", "Starting WPF application");
                App.Main();
                Logger.Info("Program", "WPF application closed");
                return 0;
            }
        }

        private static int HandleInstall(bool active, bool silent)
        {
            using (var operationMutex = new Mutex(true, OPERATION_MUTEX_NAME, out var createdNew))
            {
                if (!createdNew)
                {
                    return NotifyResult("Another Pengu activation operation is already in progress.",
                        silent, MessageBoxImage.Warning, -1);
                }

                return HandleInstallCore(active, silent);
            }
        }

        private static int HandleInstallCore(bool active, bool silent)
        {
            var action = active ? "activate" : "deactivate";
            Logger.Info("Program", $"HandleInstall called: action={action}, silent={silent}");

            if (!Module.IsFound)
            {
                Logger.Error("Program", "Module (core.dll) not found");
                return NotifyResult($"Unable to {action} Pengu because `core.dll` was not found next to the loader.", silent, MessageBoxImage.Error, -2);
            }

            // Deactivation only removes the IFEO registration and disables the
            // loader configuration; it is safe while the client still has the
            // native module loaded. Activation still requires a closed client.
            if (active && Module.IsLoaded)
            {
                Logger.Warn("Program", $"Cannot activate: IsLoaded={Module.IsLoaded}");
                return NotifyResult($"Please close the running League Client and Loader menu before you {action} it.",
                    silent, MessageBoxImage.Warning, -1);
            }

            if (!active && Module.IsLoaded)
                Logger.Info("Program", "Deactivating while the League client is running; the client will be restarted by Rose.");

            if (!LCU.IsValidDir(Config.LeaguePath))
            {
                Logger.Error("Program", $"League path invalid: {Config.LeaguePath}");
                return NotifyResult($"Unable to {action} Pengu: League path is not set or invalid. Use --set-league-path to configure it.",
                    silent, MessageBoxImage.Error, -5);
            }

            try
            {
                Logger.Info("Program", $"Calling Module.SetActive({active})");
                if (!Module.SetActive(active))
                {
                    Logger.Error("Program", $"SetActive returned false! IsActivated={Module.IsActivated}, IsLoaded={Module.IsLoaded}");
                    LogFailure($"HandleInstall SetActive returned false ({action})",
                        $"IsActivated={Module.IsActivated}, IsLoaded={Module.IsLoaded}");
                    return NotifyResult($"Failed to {action} Pengu. Make sure League is closed and try again.",
                        silent, MessageBoxImage.Error, -3);
                }
                Logger.Info("Program", "SetActive succeeded");
            }
            catch (Exception ex)
            {
                Logger.Error("Program", $"Exception in HandleInstall ({action})", ex);
                LogFailure($"HandleInstall ({action})", ex: ex);
                return NotifyResult($"Failed to {action} Pengu: {ex.Message}",
                    silent, MessageBoxImage.Error, -3);
            }

            Logger.Info("Program", $"HandleInstall completed successfully: {action}");
            NotifyResult($"Pengu has been {(active ? "activated" : "deactivated")}.", silent, MessageBoxImage.Information);
            return 0;
        }

        private static int HandleStatus(bool silent)
        {
            if (!Module.IsFound)
            {
                return NotifyResult("Pengu core module (`core.dll`) could not be found.", silent, MessageBoxImage.Warning, -2);
            }

            var active = Module.IsActivated;
            NotifyResult($"Pengu is currently {(active ? "ACTIVE" : "INACTIVE")}.", silent,
                active ? MessageBoxImage.Information : MessageBoxImage.None);
            return active ? 0 : 1;
        }

        private static int ShowHelp(bool silent)
        {
            var messageBuilder = new StringBuilder();

            messageBuilder
                .AppendLine($"{Name} {VERSION}")
                .AppendLine("Usage:")
                .AppendLine("  Pengu Loader.exe [command] [--silent]")
                .AppendLine()
                .AppendLine("Commands:")
                .AppendLine("  --install, --activate          Activate Pengu")
                .AppendLine("  --uninstall, --deactivate      Deactivate Pengu")
                .AppendLine("  --status                       Print the current activation status")
                .AppendLine("  --list-plugins                 List available plugins and their status")
                .AppendLine("  --enable-plugin <name>         Enable a plugin by name or path segment")
                .AppendLine("  --disable-plugin <name>        Disable a plugin by name or path segment")
                .AppendLine("  --toggle-plugin <name>         Toggle a plugin")
                .AppendLine("  --set-league-path <path>       Set the League of Legends installation path")
                .AppendLine("  --get-league-path              Show the configured League of Legends path")
                .AppendLine("  --set-option <key> <value>     Update loader options")
                .AppendLine("                                  keys: optimize-client, super-low-spec, language")
                .AppendLine("  --restart-client               Ask the League Client UX to restart")
                .AppendLine("  --ui                           Launch the legacy graphical interface")
                .AppendLine("  --help                         Show this message")
                .AppendLine()
                .AppendLine("Options:")
                .AppendLine("  --silent                       Suppress message boxes, write to console if available");

            var message = messageBuilder.ToString();

            return NotifyResult(message, silent, MessageBoxImage.None);
        }

        private static int NotifyResult(string message, bool silent, MessageBoxImage image, int code = 0)
        {
            if (silent)
            {
                WriteConsole(message);
            }
            else if (image == MessageBoxImage.None)
            {
                MessageBox.Show(message, Name, MessageBoxButton.OK);
            }
            else
            {
                MessageBox.Show(message, Name, MessageBoxButton.OK, image);
            }

            return code;
        }

        private static void WriteConsole(string message)
        {
            try
            {
                if (!_consoleAttached)
                {
                    _consoleAttached = AttachConsole(ATTACH_PARENT_PROCESS);
                }

                if (_consoleAttached)
                {
                    Console.Out.WriteLine(message);
                }
            }
            catch
            {
                // ignored
            }
        }

        private static bool IsSilentArgument(string argument)
        {
            if (argument == null)
                return false;

            switch (argument.ToLowerInvariant())
            {
                case "--silent":
                case "-s":
                case "/silent":
                    return true;
                default:
                    return false;
            }
        }

        //static Program()
        //{
        //    CosturaUtility.Initialize();
        //}

        private static List<string> ExtractCommandArgs(string[] args)
        {
            var commandArgs = new List<string>();

            foreach (var argument in args)
            {
                if (IsSilentArgument(argument) || DataStore.IsDataStore(argument) || argument == null)
                {
                    continue;
                }

                var value = argument.Trim();
                if (value.Length == 0)
                    continue;

                var separatorIndex = value.IndexOf('=');
                if (separatorIndex > 0)
                {
                    var commandPart = value.Substring(0, separatorIndex);
                    if (!string.IsNullOrEmpty(commandPart))
                        commandArgs.Add(commandPart);

                    if (separatorIndex < value.Length - 1)
                    {
                        var valuePart = value.Substring(separatorIndex + 1);
                        if (!string.IsNullOrEmpty(valuePart))
                            commandArgs.Add(valuePart);
                    }
                }
                else
                {
                    commandArgs.Add(value);
                }
            }

            return commandArgs;
        }

        private static int HandleListPlugins(bool silent)
        {
            var plugins = Plugins.All();

            if (plugins.Count == 0)
            {
                return NotifyResult("No plugins were found in the plugins directory.", silent, MessageBoxImage.Information);
            }

            var builder = new StringBuilder();
            builder.AppendLine("Installed plugins:");

            foreach (var plugin in plugins.OrderBy(p => p.Name, StringComparer.OrdinalIgnoreCase))
            {
                builder.Append("  ");
                builder.Append(plugin.Enabled ? "[x] " : "[ ] ");
                builder.Append(plugin.Name);

                if (!string.IsNullOrWhiteSpace(plugin.Author))
                {
                    builder.Append(" (");
                    builder.Append(plugin.Author);
                    builder.Append(')');
                }

                if (!string.IsNullOrWhiteSpace(plugin.Link))
                {
                    builder.Append(" ");
                    builder.Append(plugin.Link);
                }

                builder.AppendLine();
            }

            var message = builder.ToString().TrimEnd();

            return NotifyResult(message, true, MessageBoxImage.None);
        }

        private static int HandlePluginCommand(List<string> commandArgs, bool? targetState, bool silent)
        {
            if (commandArgs.Count < 2)
            {
                var usage = targetState == null
                    ? "Usage: --toggle-plugin <plugin-name>"
                    : targetState.Value
                        ? "Usage: --enable-plugin <plugin-name>"
                        : "Usage: --disable-plugin <plugin-name>";

                return NotifyResult(usage, silent, MessageBoxImage.Warning, -11);
            }

            var pluginIdentifier = string.Join(" ", commandArgs.Skip(1)).Trim();

            if (string.IsNullOrEmpty(pluginIdentifier))
            {
                return NotifyResult("Plugin name cannot be empty.", silent, MessageBoxImage.Warning, -11);
            }

            var plugin = FindPlugin(pluginIdentifier);

            if (plugin == null)
            {
                return NotifyResult($"Plugin '{pluginIdentifier}' was not found.", silent, MessageBoxImage.Error, -12);
            }

            var desiredState = targetState ?? !plugin.Enabled;

            if (plugin.Enabled == desiredState)
            {
                return NotifyResult(
                    $"Plugin '{plugin.Name}' is already {(plugin.Enabled ? "enabled" : "disabled")}.",
                    silent, MessageBoxImage.Information);
            }

            Plugins.Toggle(plugin);

            return NotifyResult($"Plugin '{plugin.Name}' is now {(plugin.Enabled ? "enabled" : "disabled")}.",
                silent, MessageBoxImage.Information);
        }

        private static int HandleSetLeaguePath(List<string> commandArgs, bool silent)
        {
            if (commandArgs.Count < 2)
            {
                return NotifyResult("Usage: --set-league-path <path>", silent, MessageBoxImage.Warning, -13);
            }

            var path = string.Join(" ", commandArgs.Skip(1)).Trim();

            if (string.IsNullOrWhiteSpace(path))
            {
                Config.LeaguePath = string.Empty;
                return NotifyResult("League of Legends path cleared.", silent, MessageBoxImage.Information);
            }

            if (!LCU.IsValidDir(path))
            {
                return NotifyResult($"'{path}' does not appear to be a valid League of Legends directory.",
                    silent, MessageBoxImage.Error, -14);
            }

            Config.LeaguePath = path;
            return NotifyResult($"League of Legends path set to '{path}'.", silent, MessageBoxImage.Information);
        }

        private static int HandleGetLeaguePath(bool silent)
        {
            var path = Config.LeaguePath;
            path = string.IsNullOrWhiteSpace(path) ? "[not set]" : path;
            return NotifyResult($"League of Legends path: {path}", silent, MessageBoxImage.None);
        }

        private static int HandleSetOption(List<string> commandArgs, bool silent)
        {
            if (commandArgs.Count < 3)
            {
                return NotifyResult("Usage: --set-option <key> <value>", silent, MessageBoxImage.Warning, -15);
            }

            var key = commandArgs[1].ToLowerInvariant();
            var value = string.Join(" ", commandArgs.Skip(2)).Trim();

            switch (key)
            {
                case "optimize-client":
                    if (!TryParseBool(value, out var optimizeValue))
                        return NotifyResult("Value for optimize-client must be true/false.", silent, MessageBoxImage.Warning, -16);

                    Config.OptimizeClient = optimizeValue;
                    return NotifyResult($"optimize-client set to {Config.OptimizeClient}.", silent, MessageBoxImage.Information);

                case "super-low-spec":
                    if (!TryParseBool(value, out var lowSpecValue))
                        return NotifyResult("Value for super-low-spec must be true/false.", silent, MessageBoxImage.Warning, -16);

                    Config.SuperLowSpecMode = lowSpecValue;
                    return NotifyResult($"super-low-spec set to {Config.SuperLowSpecMode}.", silent, MessageBoxImage.Information);

                case "language":
                    if (string.IsNullOrWhiteSpace(value))
                        return NotifyResult("Value for language cannot be empty.", silent, MessageBoxImage.Warning, -16);
                    Config.Language = value;
                    return NotifyResult($"language set to '{Config.Language}'.", silent, MessageBoxImage.Information);

                default:
                    return NotifyResult($"Unknown option '{key}'.", silent, MessageBoxImage.Warning, -17);
            }
        }

        private static int HandleRestartClient(bool silent)
        {
            try
            {
                if (!LCU.IsRunning)
                {
                    return NotifyResult("League Client UX is not running.", silent, MessageBoxImage.Warning, -18);
                }

                LCU.KillUxAndRestart().GetAwaiter().GetResult();
                return NotifyResult("Requested the League Client UX to restart.", silent, MessageBoxImage.Information);
            }
            catch (Exception ex)
            {
                return NotifyResult($"Failed to restart the League Client UX: {ex.Message}", silent,
                    MessageBoxImage.Error, -19);
            }
        }

        private static bool TryParseBool(string value, out bool result)
        {
            switch (value?.Trim().ToLowerInvariant())
            {
                case "1":
                case "true":
                case "yes":
                case "on":
                    result = true;
                    return true;
                case "0":
                case "false":
                case "no":
                case "off":
                    result = false;
                    return true;
                default:
                    result = false;
                    return false;
            }
        }

        private static Plugins.PluginInfo FindPlugin(string identifier)
        {
            if (string.IsNullOrWhiteSpace(identifier))
                return null;

            var normalizedTarget = NormalizePluginName(identifier);
            var plugins = Plugins.All();

            Plugins.PluginInfo Match(Func<Plugins.PluginInfo, bool> predicate)
            {
                return plugins.FirstOrDefault(predicate);
            }

            return
                Match(p => string.Equals(NormalizePluginName(p.Name), normalizedTarget, StringComparison.OrdinalIgnoreCase)) ??
                Match(p => string.Equals(Path.GetFileName(NormalizePluginName(p.Name)), normalizedTarget,
                    StringComparison.OrdinalIgnoreCase)) ??
                Match(p => string.Equals(Path.GetFileNameWithoutExtension(NormalizePluginName(p.Name)), normalizedTarget,
                    StringComparison.OrdinalIgnoreCase)) ??
                Match(p => NormalizePluginName(p.Name).EndsWith(normalizedTarget, StringComparison.OrdinalIgnoreCase));
        }

        private static string NormalizePluginName(string name)
        {
            if (string.IsNullOrWhiteSpace(name))
                return string.Empty;

            var normalized = name.Replace('\\', '/').Trim();

            if (normalized.EndsWith(".js_", StringComparison.OrdinalIgnoreCase))
                normalized = normalized.Substring(0, normalized.Length - 1);

            if (normalized.EndsWith(".js", StringComparison.OrdinalIgnoreCase))
                normalized = normalized.Substring(0, normalized.Length - 3);

            if (normalized.EndsWith("/index", StringComparison.OrdinalIgnoreCase))
                normalized = normalized.Substring(0, normalized.Length - "/index".Length);

            return normalized;
        }
    }
}
