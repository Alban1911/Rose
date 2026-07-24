using System;
using System.Diagnostics;
using System.IO;
using System.Text;

namespace PenguLoader.Main
{
    internal static class Logger
    {
        private static readonly object _lock = new object();
        private static string _logPath;
        private static bool _initialized;

        private static string LogPath
        {
            get
            {
                if (_logPath == null)
                    _logPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "pengu.log");
                return _logPath;
            }
        }

        public static void Initialize()
        {
            if (_initialized)
                return;

            _initialized = true;

            try
            {
                // Rotate log if it's too large (> 1MB)
                if (File.Exists(LogPath))
                {
                    var info = new FileInfo(LogPath);
                    if (info.Length > 1024 * 1024)
                    {
                        var oldLog = LogPath + ".old";
                        if (File.Exists(oldLog))
                            File.Delete(oldLog);
                        File.Move(LogPath, oldLog);
                    }
                }
            }
            catch { }

            Info("Logger", "============================================================");
            Info("Logger", "Pengu Loader invocation");
            Info("Logger", $"Timestamp: {DateTime.Now:O}");
            Info("Logger", $"Version: {Program.VERSION}");
            Info("Logger", $"PID: {Process.GetCurrentProcess().Id}");
            Info("Logger", $"BaseDir: {AppDomain.CurrentDomain.BaseDirectory}");
            Info("Logger", $"CommandLine: {Environment.CommandLine}");
            Info("Logger", $"OS: {Environment.OSVersion}");
            Info("Logger", $"64-bit OS: {Environment.Is64BitOperatingSystem}");
            Info("Logger", $"64-bit Process: {Environment.Is64BitProcess}");
            Info("Logger", "============================================================");
        }

        public static void Info(string source, string message)
        {
            Write("INFO", source, message);
        }

        public static void Warn(string source, string message)
        {
            Write("WARN", source, message);
        }

        public static void Error(string source, string message)
        {
            Write("ERROR", source, message);
        }

        public static void Error(string source, string message, Exception ex)
        {
            var sb = new StringBuilder();
            sb.AppendLine(message);
            AppendException(sb, ex, "Exception");
            Write("ERROR", source, sb.ToString());
        }

        private static void AppendException(StringBuilder sb, Exception ex, string label)
        {
            if (ex == null)
                return;

            sb.AppendLine($"  {label}: {ex.GetType().FullName}");
            sb.AppendLine($"  {label}Message: {ex.Message}");
            sb.AppendLine($"  {label}StackTrace: {ex.StackTrace}");

            if (ex.InnerException != null)
                AppendException(sb, ex.InnerException, label + "Inner");
        }

        public static void Debug(string source, string message)
        {
            Write("DEBUG", source, message);
        }

        private static void Write(string level, string source, string message)
        {
            try
            {
                var timestamp = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff");
                var line = $"[{timestamp}] [{level}] [{source}] {message}";

                lock (_lock)
                {
                    File.AppendAllText(LogPath, line + Environment.NewLine);
                }
            }
            catch
            {
                // Can't log if logging fails
            }
        }

        public static void LogSystemInfo()
        {
            try
            {
                Info("System", $"CLR Version: {Environment.Version}");
                Info("System", $"ProcessorCount: {Environment.ProcessorCount}");
            }
            catch (Exception ex)
            {
                Error("System", "Failed to log system info", ex);
            }
        }

        public static void LogFileInfo(string path, string label)
        {
            try
            {
                if (File.Exists(path))
                {
                    var info = new FileInfo(path);
                    Info("FileInfo", $"{label}: {path}");
                    Info("FileInfo", $"  Exists: true, Size: {info.Length} bytes, LastWrite: {info.LastWriteTime}");
                }
                else
                {
                    Info("FileInfo", $"{label}: {path}");
                    Info("FileInfo", $"  Exists: false");
                }
            }
            catch (Exception ex)
            {
                Error("FileInfo", $"Failed to get info for {label}: {path}", ex);
            }
        }

        public static void LogDirectoryInfo(string path, string label)
        {
            try
            {
                if (Directory.Exists(path))
                {
                    Info("DirInfo", $"{label}: {path}");
                    Info("DirInfo", $"  Exists: true");

                    try
                    {
                        var files = Directory.GetFiles(path);
                        Info("DirInfo", $"  FileCount: {files.Length}");
                    }
                    catch
                    {
                        Info("DirInfo", $"  FileCount: (access denied)");
                    }
                }
                else
                {
                    Info("DirInfo", $"{label}: {path}");
                    Info("DirInfo", $"  Exists: false");
                }
            }
            catch (Exception ex)
            {
                Error("DirInfo", $"Failed to get info for {label}: {path}", ex);
            }
        }
    }
}
