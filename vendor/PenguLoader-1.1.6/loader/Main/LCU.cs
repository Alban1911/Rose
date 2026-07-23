using System;
using System.Diagnostics;
using System.IO;
using System.Management;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;

namespace PenguLoader.Main
{
    internal static class LCU
    {
        public static string ClientProcessName => "LeagueClient.exe";
        public static string ClientUxProcessName => "LeagueClientUx.exe";

        private static readonly HttpClient Http;

        static LCU()
        {
            Http = new HttpClient();
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls11 | SecurityProtocolType.Tls12;
            ServicePointManager.ServerCertificateValidationCallback += (a, b, c, d) => true;
        }

        private static Process[] GetUxProcesses()
        {
            try
            {
                var procs = Process.GetProcessesByName("LeagueClientUx");
                Logger.Debug("LCU", $"GetUxProcesses: found {procs.Length} LeagueClientUx processes");
                return procs;
            }
            catch (Exception ex)
            {
                Logger.Error("LCU", "GetUxProcesses failed", ex);
                return new Process[0];
            }
        }

        public static bool IsRunning
        {
            get
            {
                var running = GetUxProcesses().Length > 0;
                Logger.Debug("LCU", $"IsRunning: {running}");
                return running;
            }
        }

        public static string GetDir()
        {
            try
            {
                var procs = GetUxProcesses();
                if (procs.Length == 0)
                {
                    Logger.Debug("LCU", "GetDir: no LeagueClientUx process found");
                    return string.Empty;
                }

                var found = procs[0];
                var dir = Directory.GetParent(found.MainModule.FileName).FullName;
                Logger.Debug("LCU", $"GetDir: {dir}");
                return dir;
            }
            catch (Exception ex)
            {
                Logger.Error("LCU", "GetDir failed", ex);
                return string.Empty;
            }
        }

        public static async Task<string> Request(string api, string method, string body = null)
        {
            Logger.Debug("LCU", $"Request: {method} {api}");

            var lcPath = GetDir();

            if (string.IsNullOrEmpty(lcPath))
            {
                Logger.Warn("LCU", "Request failed: lcPath is empty");
                return null;
            }

            if (!GetCredentials(lcPath, out var port, out var pass))
            {
                Logger.Warn("LCU", "Request failed: couldn't get credentials");
                return null;
            }

            var uri = $"https://127.0.0.1:{port}{api}";
            var authToken = Encoding.ASCII.GetBytes("riot:" + pass);
            var authorization = "Basic " + Convert.ToBase64String(authToken);

            try
            {
                Logger.Debug("LCU", $"Sending request to {uri}");

                using (var req = new HttpRequestMessage(new HttpMethod(method), uri))
                {
                    req.Headers.Add("Authorization", authorization);

                    if (!string.IsNullOrEmpty(body))
                        req.Content = new StringContent(body, Encoding.UTF8, "application/json");

                    using (var res = await Http.SendAsync(req))
                    {
                        var responseBody = await res.Content.ReadAsStringAsync();
                        Logger.Debug("LCU", $"Response status: {res.StatusCode}");
                        return responseBody;
                    }
                }
            }
            catch (Exception ex)
            {
                Logger.Error("LCU", $"Request to {api} failed", ex);
                return null;
            }
        }

        public static Task KillUxAndRestart()
        {
            Logger.Info("LCU", "KillUxAndRestart called");
            return Request("/riotclient/kill-and-restart-ux", "POST");
        }

        private static bool GetCredentials(string lcPath, out string port, out string pass)
        {
            Logger.Debug("LCU", $"GetCredentials for path: {lcPath}");

            try
            {
                var lockfilePath = Path.Combine(lcPath, "lockfile");
                Logger.Debug("LCU", $"Checking lockfile: {lockfilePath}");

                if (File.Exists(lockfilePath))
                {
                    using (var fileStream = new FileStream(lockfilePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                    {
                        using (var reader = new StreamReader(fileStream))
                        {
                            var content = reader.ReadToEnd();

                            if (!string.IsNullOrEmpty(content))
                            {
                                var tokens = content.Split(':');
                                if (tokens.Length >= 4)
                                {
                                    port = tokens[2];
                                    pass = tokens[3];
                                    Logger.Debug("LCU", $"Got credentials from lockfile (port={port})");
                                    return true;
                                }
                                else
                                {
                                    Logger.Warn("LCU", $"Lockfile format invalid, tokens={tokens.Length}");
                                }
                            }
                            else
                            {
                                Logger.Warn("LCU", "Lockfile is empty");
                            }
                        }
                    }
                }
                else
                {
                    Logger.Debug("LCU", "Lockfile does not exist");
                }

                // Server disabled lockfile, use wmic instead
                Logger.Debug("LCU", "Trying to get credentials from process command line");
                string commandLine = GetCommandlineFromProcess("LeagueClientUx.exe");
                if (!string.IsNullOrEmpty(commandLine))
                {
                    port = ExtractValueFromCommandLine(commandLine, "--app-port=");
                    pass = ExtractValueFromCommandLine(commandLine, "--remoting-auth-token=");

                    if (!string.IsNullOrEmpty(port) && !string.IsNullOrEmpty(pass))
                    {
                        Logger.Debug("LCU", $"Got credentials from command line (port={port})");
                        return true;
                    }
                    else
                    {
                        Logger.Warn("LCU", "Failed to extract port/pass from command line");
                    }
                }
                else
                {
                    Logger.Warn("LCU", "Command line is empty or not found");
                }
            }
            catch (Exception ex)
            {
                Logger.Error("LCU", "GetCredentials failed", ex);
            }

            port = pass = string.Empty;
            return false;
        }

        private static string GetCommandlineFromProcess(string process)
        {
            try
            {
                using (var searcher = new ManagementObjectSearcher($"SELECT CommandLine FROM Win32_Process WHERE Name = '{process}'"))
                {
                    foreach (ManagementObject obj in searcher.Get())
                    {
                        var cmdLine = obj["CommandLine"]?.ToString();
                        if (!string.IsNullOrEmpty(cmdLine))
                        {
                            Logger.Debug("LCU", $"Got command line for {process} (length={cmdLine.Length})");
                            return cmdLine;
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Logger.Error("LCU", $"GetCommandlineFromProcess failed for {process}", ex);
            }
            return null;
        }

        private static string ExtractValueFromCommandLine(string cmdline, string parameter)
        {
            int index = cmdline.IndexOf(parameter);
            if (index >= 0)
            {
                index += parameter.Length;
                int endIndex = cmdline.IndexOf("\"", index);
                if (endIndex > index)
                {
                    return cmdline.Substring(index, endIndex - index);
                }
            }
            return null;
        }

        public static bool IsValidDir(string path)
        {
            if (string.IsNullOrEmpty(path))
            {
                Logger.Debug("LCU", "IsValidDir: path is null or empty");
                return false;
            }

            var dirExists = Directory.Exists(path);
            var clientExists = File.Exists(Path.Combine(path, ClientProcessName));
            var uxExists = File.Exists(Path.Combine(path, ClientUxProcessName));

            var valid = dirExists && clientExists && uxExists;

            if (!valid)
            {
                Logger.Debug("LCU", $"IsValidDir: {path}");
                Logger.Debug("LCU", $"  Directory exists: {dirExists}");
                Logger.Debug("LCU", $"  {ClientProcessName} exists: {clientExists}");
                Logger.Debug("LCU", $"  {ClientUxProcessName} exists: {uxExists}");
            }

            return valid;
        }
    }
}
