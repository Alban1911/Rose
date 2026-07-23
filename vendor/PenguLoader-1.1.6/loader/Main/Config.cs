using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace PenguLoader.Main
{
    static class Config
    {
        public static string ConfigPath => GetPath("config");
        public static string DataStorePath => GetPath("datastore");
        public static string PluginsDir => GetPath("plugins");

        static Dictionary<string, string> _data;
        static string _runtimeLeaguePath;

        static Config()
        {
            try
            {
                Logger.Debug("Config", "Static constructor called");
                Logger.Debug("Config", $"ConfigPath: {ConfigPath}");
                Logger.Debug("Config", $"DataStorePath: {DataStorePath}");
                Logger.Debug("Config", $"PluginsDir: {PluginsDir}");

                Utils.EnsureDirectoryExists(PluginsDir);
                Utils.EnsureFileExists(ConfigPath);
                Utils.EnsureFileExists(DataStorePath);

                _data = new Dictionary<string, string>();

                if (File.Exists(ConfigPath))
                {
                    var lines = File.ReadAllLines(ConfigPath);
                    Logger.Debug("Config", $"Loaded {lines.Length} lines from config");

                    foreach (string line in lines)
                    {
                        var parts = line.Split(new[] { '=' }, 2);

                        if (parts.Length == 2)
                        {
                            string key = parts[0].Trim();
                            string value = parts[1].Trim();

                            _data[key] = value;
                            Logger.Debug("Config", $"Loaded: {key}={value}");
                        }
                    }
                }
                else
                {
                    Logger.Debug("Config", "Config file does not exist");
                }
            }
            catch (Exception ex)
            {
                Logger.Error("Config", "Failed to initialize config", ex);
                _data = new Dictionary<string, string>();
            }
        }

        static void Save()
        {
            try
            {
                Logger.Debug("Config", "Saving config...");
                var sb = new StringBuilder();

                foreach (var kv in _data)
                {
                    var key = kv.Key;
                    var value = kv.Value.Trim();

                    var line = $"{key}={value}";
                    sb.AppendLine(line);
                }

                File.WriteAllText(ConfigPath, sb.ToString());
                Logger.Debug("Config", $"Config saved to {ConfigPath}");
            }
            catch (Exception ex)
            {
                Logger.Error("Config", "Failed to save config", ex);
            }
        }

        public static string LeaguePath
        {
            get
            {
                if (!string.IsNullOrWhiteSpace(_runtimeLeaguePath))
                {
                    Logger.Debug("Config", $"LeaguePath (runtime override): {_runtimeLeaguePath}");
                    return _runtimeLeaguePath;
                }

                // First, try to get from Rose config.ini
                var rosePath = GetRoseConfigPath();
                if (!string.IsNullOrWhiteSpace(rosePath))
                {
                    Logger.Debug("Config", $"LeaguePath (from Rose config): {rosePath}");
                    return rosePath;
                }

                // Fallback to local config
                var localPath = Get("LeaguePath");
                Logger.Debug("Config", $"LeaguePath (from local config): {localPath}");
                return localPath;
            }
            set
            {
                Logger.Info("Config", $"Setting LeaguePath to: {value}");
                Set("LeaguePath", value);
            }
        }

        static bool? _runtimeUseSymlink;

        public static bool UseSymlink
        {
            get => _runtimeUseSymlink ?? GetBool("UseSymlink", false);
            set => SetBool("UseSymlink", value);
        }

        public static void SetRuntimeUseSymlink(bool value)
        {
            _runtimeUseSymlink = value;
            Logger.Info("Config", $"Runtime UseSymlink override set to: {value}");
        }

        public static void SetRuntimeLeaguePath(string value)
        {
            _runtimeLeaguePath = string.IsNullOrWhiteSpace(value)
                ? null
                : value.TrimEnd('\\', '/');
            Logger.Info("Config", $"Runtime LeaguePath override set to: {_runtimeLeaguePath}");
        }

        public static string Language
        {
            get => Get("Language", "English");
            set => Set("Language", value);
        }

        public static bool OptimizeClient
        {
            get => GetBool("OptimizeClient", true);
            set => SetBool("OptimizeClient", value);
        }

        public static bool SuperLowSpecMode
        {
            get => GetBool("SuperLowSpecMode", false);
            set => SetBool("SuperLowSpecMode", value);
        }

        static string GetPath(string subpath)
        {
            return Path.Combine(AppDomain.CurrentDomain.BaseDirectory, subpath);
        }

        static string Get(string key, string @default = "")
        {
            if (_data.ContainsKey(key))
                return _data[key];

            return @default;
        }

        static void Set(string key, string value)
        {
            _data[key] = value;
            Save();
        }

        static bool GetBool(string key, bool @default)
        {
            var value = Get(key).ToLower();

            if (value == "true" || value == "1")
                return true;
            else if (value == "false" || value == "0")
                return false;

            return @default;
        }

        static void SetBool(string key, bool value)
        {
            Set(key, value ? "true" : "false");
        }

        static string GetRoseConfigPath()
        {
            try
            {
                var localAppData = DesktopUser.GetLocalAppData();
                var configPath = Path.Combine(localAppData, "Rose", "config.ini");

                Logger.Debug("Config", $"Checking Rose config at: {configPath}");

                if (!File.Exists(configPath))
                {
                    Logger.Debug("Config", "Rose config.ini does not exist");
                    return string.Empty;
                }

                var lines = File.ReadAllLines(configPath);
                bool inGeneralSection = false;

                foreach (var line in lines)
                {
                    var trimmed = line.Trim();

                    // Check for section headers
                    if (trimmed.StartsWith("[") && trimmed.EndsWith("]"))
                    {
                        inGeneralSection = trimmed.Equals("[General]", StringComparison.OrdinalIgnoreCase);
                        continue;
                    }

                    // Only process lines in [General] section
                    if (inGeneralSection)
                    {
                        var parts = trimmed.Split(new[] { '=' }, 2);
                        if (parts.Length == 2)
                        {
                            var key = parts[0].Trim();
                            var value = parts[1].Trim();

                            if (key.Equals("clientpath", StringComparison.OrdinalIgnoreCase))
                            {
                                Logger.Debug("Config", $"Found clientpath in Rose config: {value}");

                                if (string.IsNullOrWhiteSpace(value))
                                {
                                    Logger.Debug("Config", "clientpath is empty");
                                    return string.Empty;
                                }

                                value = value.TrimEnd('\\', '/');

                                // Use path as-is if it already contains the client executables
                                if (LCU.IsValidDir(value))
                                {
                                    Logger.Debug("Config", $"clientpath is valid: {value}");
                                    return value;
                                }

                                // Otherwise try appending \LeagueClient for older directory layouts
                                var withSubdir = value + "\\LeagueClient";
                                if (LCU.IsValidDir(withSubdir))
                                {
                                    Logger.Debug("Config", $"clientpath valid with subdir: {withSubdir}");
                                    return withSubdir;
                                }

                                Logger.Warn("Config", $"clientpath not valid, returning as-is: {value}");
                                return value;
                            }
                        }
                    }
                }

                Logger.Debug("Config", "clientpath not found in Rose config");
            }
            catch (Exception ex)
            {
                Logger.Error("Config", "Failed to read Rose config", ex);
            }

            return string.Empty;
        }
    }
}