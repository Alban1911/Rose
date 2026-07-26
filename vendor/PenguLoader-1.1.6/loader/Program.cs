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
        internal interface IOperationMutex : IDisposable
        {
            bool CreatedNew { get; }
        }

        private sealed class NamedOperationMutex : IOperationMutex
        {
            private readonly Mutex _mutex;
            public bool CreatedNew { get; }

            public NamedOperationMutex(string name)
            {
                _mutex = new Mutex(true, name, out var createdNew);
                CreatedNew = createdNew;
            }

            public void Dispose()
            {
                _mutex.Dispose();
            }
        }

        private static IOperationMutex CreateOperationMutex()
        {
            return new NamedOperationMutex(OPERATION_MUTEX_NAME);
        }

        internal static Func<IOperationMutex> OperationMutexFactory { get; set; } = CreateOperationMutex;
        internal static Func<bool, ActivationResult> InstallCoreOverride { get; set; }

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool AttachConsole(int dwProcessId);

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
                Logger.Error("Program", "Unhandled exception in Main. Args: [" + string.Join(", ", args) + "]", ex);
                return -99;
            }
        }

        private static int MainInner(string[] args)
        {
            Logger.Info("Program", "MainInner called with args: [" + string.Join(", ", args) + "]");
            var dataStorePath = args.FirstOrDefault(DataStore.IsDataStore);
            if (dataStorePath != null)
            {
                Logger.Info("Program", "DataStore path detected: " + dataStorePath);
                DataStore.DumpDataStore(dataStorePath);
                return 0;
            }

            var silent = args.Any(IsSilentArgument);
            var commandArgs = ExtractCommandArgs(args);
            Logger.Info("Program", "Silent mode: " + silent + ", Command args: [" + string.Join(", ", commandArgs) + "]");
            if (commandArgs.Count == 0)
                return RunApplication();

            var commandKey = commandArgs[0].ToLowerInvariant();
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
                case "--status": return HandleStatus(silent);
                case "--list-plugins": return HandleListPlugins(silent);
                case "--toggle-plugin": return HandlePluginCommand(commandArgs, null, silent);
                case "--enable-plugin": return HandlePluginCommand(commandArgs, true, silent);
                case "--disable-plugin": return HandlePluginCommand(commandArgs, false, silent);
                case "--set-league-path": return HandleSetLeaguePath(commandArgs, silent);
                case "--get-league-path": return HandleGetLeaguePath(silent);
                case "--set-option": return HandleSetOption(commandArgs, silent);
                case "--restart-client": return HandleRestartClient(silent);
                case "--ui":
                case "/ui":
                case "--show-ui": return RunApplication();
                case "--help":
                case "-h":
                case "/?": return ShowHelp(silent);
                default:
                    return NotifyResult("Unknown command '" + commandArgs[0] + "'. Use --help to see available commands.",
                        silent, MessageBoxImage.Warning, -10);
            }
        }

        private static int RunApplication()
        {
            using (var mutex = new Mutex(true, GUI_MUTEX_NAME, out var createdNew))
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
        }

        private static int HandleInstall(bool active, bool silent)
        {
            var result = ExecuteInstall(active, silent);
            var action = active ? "activate" : "deactivate";
            if (result.Succeeded)
            {
                NotifyResult("Pengu has been " + (active ? "activated" : "deactivated") + ".",
                    silent, MessageBoxImage.Information);
                return 0;
            }

            var message = "Failed to " + action + " Pengu: " + result.ToOfficialStyleString();
            if (!string.IsNullOrEmpty(result.NativeErrorMessage))
                message += "\n" + result.NativeErrorMessage;
            return NotifyResult(message, silent, MessageBoxImage.Error, result.EncodeExitCode());
        }

        internal static ActivationResult RequestActivation(bool active)
        {
            return ExecuteInstall(active, false);
        }

        private static ActivationResult ExecuteInstall(bool active, bool silent)
        {
            Logger.Info(
                "Activation",
                "Request active=" + active.ToString().ToLowerInvariant() +
                " silent=" + silent.ToString().ToLowerInvariant() +
                " elevated=" + Elevation.IsElevated().ToString().ToLowerInvariant() +
                " pid=" + System.Diagnostics.Process.GetCurrentProcess().Id);

            ActivationResult result;
            if (!Elevation.IsElevated())
            {
                // The unelevated parent deliberately does not acquire the
                // operation mutex while waiting for its runas child.
                result = Elevation.RunElevated(active, silent);
            }
            else
            {
                try
                {
                    using (var operationMutex = OperationMutexFactory())
                    {
                        if (!operationMutex.CreatedNew)
                        {
                            result = ActivationResult.Failure(
                                ActivationStage.None,
                                ActivationErrorKind.Other,
                                0,
                                "Another Pengu activation operation is already in progress.");
                        }
                        else
                        {
                            result = RunInstallCore(active);
                        }
                    }
                }
                catch (Exception ex)
                {
                    Logger.Error("Program", "Exception in elevated activation operation", ex);
                    result = ActivationResult.Failure(
                        ActivationStage.None,
                        ActivationErrorKind.Other,
                        0,
                        ex.Message);
                }
            }

            var completedMessage = "active=" + active.ToString().ToLowerInvariant() +
                " success=" + result.Succeeded.ToString().ToLowerInvariant();
            if (result.Succeeded)
                Logger.Info("Activation", "Completed " + completedMessage);
            else
                Logger.Error(
                    "Activation",
                    "Completed " + completedMessage +
                    " stage=" + ActivationResult.StageName(result.Stage) +
                    " kind=" + ActivationResult.ErrorKindName(result.ErrorKind) +
                    " partialState=" + result.PartialState);
            return result;
        }

        private static ActivationResult RunInstallCore(bool active)
        {
            var overrideHandler = InstallCoreOverride;
            return overrideHandler == null ? HandleInstallCore(active) : overrideHandler(active);
        }
        private static ActivationResult HandleInstallCore(bool active)
        {
            var action = active ? "activate" : "deactivate";
            Logger.Info("Program", "HandleInstallCore called: action=" + action);
            if (!Module.IsFound)
                return ActivationResult.Failure(ActivationStage.None, ActivationErrorKind.NotFound, 2,
                    "core.dll was not found next to the loader.");

            if (active && Module.IsLoaded)
                return ActivationResult.Failure(ActivationStage.None, ActivationErrorKind.InvalidInput, 0,
                    "The League Client and Loader menu must be closed before activation.");

            if (!active && Module.IsLoaded)
                Logger.Info("Program", "Deactivating while the League client is running; Rose will restart it.");

            if (!LCU.IsValidDir(Config.LeaguePath))
                return ActivationResult.Failure(ActivationStage.GetLeaguePath, ActivationErrorKind.InvalidInput, 0,
                    "League path is not set or invalid. Use --set-league-path to configure it.");

            try
            {
                var result = Module.SetActive(active);
                Logger.Info("Program", "Module.SetActive returned: " + result.ToOfficialStyleString());
                return result;
            }
            catch (Exception ex)
            {
                Logger.Error("Program", "Exception in HandleInstallCore (" + action + ")", ex);
                return ActivationResult.Failure(
                    active ? ActivationStage.SetDebugger : ActivationStage.DeleteDebugger,
                    ActivationErrorKind.Other,
                    0,
                    ex.Message);
            }
        }

        private static int HandleStatus(bool silent)
        {
            if (!Module.IsFound)
                return NotifyResult("Pengu core module (`core.dll`) could not be found.", silent, MessageBoxImage.Warning, -2);

            var active = Module.IsActivated;
            NotifyResult("Pengu is currently " + (active ? "ACTIVE" : "INACTIVE") + ".", silent,
                active ? MessageBoxImage.Information : MessageBoxImage.None);
            return active ? 0 : 1;
        }

        private static int ShowHelp(bool silent)
        {
            var message = new StringBuilder()
                .AppendLine(Name + " " + VERSION)
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
                .AppendLine("  --restart-client               Ask the League Client UX to restart")
                .AppendLine("  --ui                           Launch the graphical interface")
                .AppendLine("  --help                         Show this message")
                .AppendLine()
                .AppendLine("Options:")
                .AppendLine("  --silent                       Suppress message boxes, write to console if available")
                .ToString();
            return NotifyResult(message, silent, MessageBoxImage.None);
        }

        private static int NotifyResult(string message, bool silent, MessageBoxImage image, int code = 0)
        {
            if (code != 0 || image == MessageBoxImage.Error)
                Logger.Error("CLI", "Result code=" + code + ": " + message);
            else if (image == MessageBoxImage.Warning)
                Logger.Warn("CLI", "Result code=" + code + ": " + message);
            else
                Logger.Info("CLI", "Result code=" + code + ": " + message);

            if (silent)
                WriteConsole(message);
            else if (image == MessageBoxImage.None)
                MessageBox.Show(message, Name, MessageBoxButton.OK);
            else
                MessageBox.Show(message, Name, MessageBoxButton.OK, image);
            return code;
        }

        private static void WriteConsole(string message)
        {
            try
            {
                if (!_consoleAttached)
                    _consoleAttached = AttachConsole(ATTACH_PARENT_PROCESS);
                if (_consoleAttached)
                    Console.Out.WriteLine(message);
            }
            catch { }
        }

        private static bool IsSilentArgument(string argument)
        {
            if (argument == null) return false;
            switch (argument.ToLowerInvariant())
            {
                case "--silent":
                case "-s":
                case "/silent": return true;
                default: return false;
            }
        }

        private static List<string> ExtractCommandArgs(string[] args)
        {
            var commandArgs = new List<string>();
            foreach (var argument in args)
            {
                if (IsSilentArgument(argument) || DataStore.IsDataStore(argument) || argument == null)
                    continue;
                var value = argument.Trim();
                if (value.Length == 0) continue;
                var separatorIndex = value.IndexOf('=');
                if (separatorIndex > 0)
                {
                    commandArgs.Add(value.Substring(0, separatorIndex));
                    if (separatorIndex < value.Length - 1)
                        commandArgs.Add(value.Substring(separatorIndex + 1));
                }
                else commandArgs.Add(value);
            }
            return commandArgs;
        }

        private static int HandleListPlugins(bool silent)
        {
            var plugins = Plugins.All();
            if (plugins.Count == 0)
                return NotifyResult("No plugins were found in the plugins directory.", silent, MessageBoxImage.Information);
            var builder = new StringBuilder().AppendLine("Installed plugins:");
            foreach (var plugin in plugins.OrderBy(p => p.Name, StringComparer.OrdinalIgnoreCase))
            {
                builder.Append("  ").Append(plugin.Enabled ? "[x] " : "[ ] ").Append(plugin.Name);
                if (!string.IsNullOrWhiteSpace(plugin.Author)) builder.Append(" (").Append(plugin.Author).Append(')');
                if (!string.IsNullOrWhiteSpace(plugin.Link)) builder.Append(' ').Append(plugin.Link);
                builder.AppendLine();
            }
            return NotifyResult(builder.ToString().TrimEnd(), true, MessageBoxImage.None);
        }

        private static int HandlePluginCommand(List<string> commandArgs, bool? targetState, bool silent)
        {
            if (commandArgs.Count < 2)
            {
                var usage = targetState == null ? "Usage: --toggle-plugin <plugin-name>" :
                    (targetState.Value ? "Usage: --enable-plugin <plugin-name>" : "Usage: --disable-plugin <plugin-name>");
                return NotifyResult(usage, silent, MessageBoxImage.Warning, -11);
            }
            var pluginIdentifier = string.Join(" ", commandArgs.Skip(1)).Trim();
            if (string.IsNullOrEmpty(pluginIdentifier))
                return NotifyResult("Plugin name cannot be empty.", silent, MessageBoxImage.Warning, -11);
            var plugin = FindPlugin(pluginIdentifier);
            if (plugin == null)
                return NotifyResult("Plugin '" + pluginIdentifier + "' was not found.", silent, MessageBoxImage.Error, -12);
            var desiredState = targetState ?? !plugin.Enabled;
            if (plugin.Enabled == desiredState)
                return NotifyResult("Plugin '" + plugin.Name + "' is already " + (plugin.Enabled ? "enabled" : "disabled") + ".", silent, MessageBoxImage.Information);
            Plugins.Toggle(plugin);
            return NotifyResult("Plugin '" + plugin.Name + "' is now " + (plugin.Enabled ? "enabled" : "disabled") + ".", silent, MessageBoxImage.Information);
        }

        private static int HandleSetLeaguePath(List<string> commandArgs, bool silent)
        {
            if (commandArgs.Count < 2)
                return NotifyResult("Usage: --set-league-path <path>", silent, MessageBoxImage.Warning, -13);
            var path = string.Join(" ", commandArgs.Skip(1)).Trim();
            if (string.IsNullOrWhiteSpace(path))
            {
                Config.LeaguePath = string.Empty;
                return NotifyResult("League of Legends path cleared.", silent, MessageBoxImage.Information);
            }
            if (!LCU.IsValidDir(path))
                return NotifyResult("'" + path + "' does not appear to be a valid League of Legends directory.", silent, MessageBoxImage.Error, -14);
            Config.LeaguePath = path;
            return NotifyResult("League of Legends path set to '" + path + "'.", silent, MessageBoxImage.Information);
        }

        private static int HandleGetLeaguePath(bool silent)
        {
            var path = Config.LeaguePath;
            return NotifyResult("League of Legends path: " + (string.IsNullOrWhiteSpace(path) ? "[not set]" : path), silent, MessageBoxImage.None);
        }

        private static int HandleSetOption(List<string> commandArgs, bool silent)
        {
            if (commandArgs.Count < 3)
                return NotifyResult("Usage: --set-option <key> <value>", silent, MessageBoxImage.Warning, -15);
            var key = commandArgs[1].ToLowerInvariant();
            var value = string.Join(" ", commandArgs.Skip(2)).Trim();
            switch (key)
            {
                case "optimize-client":
                    if (!TryParseBool(value, out var optimizeValue)) return NotifyResult("Value for optimize-client must be true/false.", silent, MessageBoxImage.Warning, -16);
                    Config.OptimizeClient = optimizeValue;
                    return NotifyResult("optimize-client set to " + Config.OptimizeClient + ".", silent, MessageBoxImage.Information);
                case "super-low-spec":
                    if (!TryParseBool(value, out var lowSpecValue)) return NotifyResult("Value for super-low-spec must be true/false.", silent, MessageBoxImage.Warning, -16);
                    Config.SuperLowSpecMode = lowSpecValue;
                    return NotifyResult("super-low-spec set to " + Config.SuperLowSpecMode + ".", silent, MessageBoxImage.Information);
                case "language":
                    if (string.IsNullOrWhiteSpace(value)) return NotifyResult("Value for language cannot be empty.", silent, MessageBoxImage.Warning, -16);
                    Config.Language = value;
                    return NotifyResult("language set to '" + Config.Language + "'.", silent, MessageBoxImage.Information);
                default: return NotifyResult("Unknown option '" + key + "'.", silent, MessageBoxImage.Warning, -17);
            }
        }

        private static int HandleRestartClient(bool silent)
        {
            try
            {
                if (!LCU.IsRunning)
                    return NotifyResult("League Client UX is not running.", silent, MessageBoxImage.Warning, -18);
                LCU.KillUxAndRestart().GetAwaiter().GetResult();
                return NotifyResult("Requested the League Client UX to restart.", silent, MessageBoxImage.Information);
            }
            catch (Exception ex)
            {
                Logger.Error("Program", "Failed to restart the League Client UX", ex);
                return NotifyResult("Failed to restart the League Client UX: " + ex.Message, silent, MessageBoxImage.Error, -19);
            }
        }

        private static bool TryParseBool(string value, out bool result)
        {
            switch (value == null ? string.Empty : value.Trim().ToLowerInvariant())
            {
                case "1": case "true": case "yes": case "on": result = true; return true;
                case "0": case "false": case "no": case "off": result = false; return true;
                default: result = false; return false;
            }
        }

        private static Plugins.PluginInfo FindPlugin(string identifier)
        {
            if (string.IsNullOrWhiteSpace(identifier)) return null;
            var normalizedTarget = NormalizePluginName(identifier);
            var plugins = Plugins.All();
            Plugins.PluginInfo Match(Func<Plugins.PluginInfo, bool> predicate) { return plugins.FirstOrDefault(predicate); }
            return Match(p => string.Equals(NormalizePluginName(p.Name), normalizedTarget, StringComparison.OrdinalIgnoreCase)) ??
                Match(p => string.Equals(Path.GetFileName(NormalizePluginName(p.Name)), normalizedTarget, StringComparison.OrdinalIgnoreCase)) ??
                Match(p => string.Equals(Path.GetFileNameWithoutExtension(NormalizePluginName(p.Name)), normalizedTarget, StringComparison.OrdinalIgnoreCase)) ??
                Match(p => NormalizePluginName(p.Name).EndsWith(normalizedTarget, StringComparison.OrdinalIgnoreCase));
        }

        private static string NormalizePluginName(string name)
        {
            if (string.IsNullOrWhiteSpace(name)) return string.Empty;
            var normalized = name.Replace('\\', '/').Trim();
            if (normalized.EndsWith(".js_", StringComparison.OrdinalIgnoreCase)) normalized = normalized.Substring(0, normalized.Length - 1);
            if (normalized.EndsWith(".js", StringComparison.OrdinalIgnoreCase)) normalized = normalized.Substring(0, normalized.Length - 3);
            if (normalized.EndsWith("/index", StringComparison.OrdinalIgnoreCase)) normalized = normalized.Substring(0, normalized.Length - "/index".Length);
            return normalized;
        }
    }
}
