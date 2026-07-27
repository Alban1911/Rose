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
            var name = ClientUxProcessName.Replace(".exe", "");
            return Process.GetProcessesByName("LeagueClientUx");
        }

        public static bool IsRunning => GetUxProcesses().Length > 0;

        public static string GetDir()
        {
            var procs = GetUxProcesses();
            if (procs.Length == 0)
                return string.Empty;

            var found = procs[0];
            return Directory.GetParent(found.MainModule.FileName).FullName;
        }

        public static async Task<string> Request(string api, string method, string body = null)
        {
            var lcPath = GetDir();

            if (string.IsNullOrEmpty(lcPath) || !GetCredentials(lcPath, out var port, out var pass))
                return null;

            var uri = $"https://127.0.0.1:{port}{api}";
            var authToken = Encoding.ASCII.GetBytes("riot:" + pass);
            var authorization = "Basic " + Convert.ToBase64String(authToken);

            try
            {
                using (var req = new HttpRequestMessage(new HttpMethod(method), uri))
                {
                    req.Headers.Add("Authorization", authorization);

                    if (!string.IsNullOrEmpty(body))
                        req.Content = new StringContent(body, Encoding.UTF8, "application/json");

                    using (var res = await Http.SendAsync(req))
                    {
                        return await res.Content.ReadAsStringAsync();
                    }
                }
            }
            catch
            {
                return null;
            }
        }

        public static Task KillUxAndRestart() => Request("/riotclient/kill-and-restart-ux", "POST");

        private static bool GetCredentials(string lcPath, out string port, out string pass)
        {
            try
            {
                var lockfilePath = Path.Combine(lcPath, "lockfile");

                using (var fileStream = new FileStream(lockfilePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                {
                    using (var reader = new StreamReader(fileStream))
                    {
                        var content = reader.ReadToEnd();

                        if (!string.IsNullOrEmpty(content))
                        {
                            var tokens = content.Split(':');
                            port = tokens[2];
                            pass = tokens[3];
                            return true;
                        }
                    }
                }

                // Server disabled lockfile, use wmic instead
                string commandLine = GetCommandlineFromProcess("LeagueClientUx.exe");
                if (!string.IsNullOrEmpty(commandLine))
                {
                    port = ExtractValueFromCommandLine(commandLine, "--app-port=");
                    pass = ExtractValueFromCommandLine(commandLine, "--remoting-auth-token=");
                    return true;
                }
            }
            catch
            {
            }

            port = pass = string.Empty;
            return false;
        }

        private static string GetCommandlineFromProcess(string process)
        {
            using (var searcher = new ManagementObjectSearcher($"SELECT CommandLine FROM Win32_Process WHERE Name = '{process}'"))
            {
                foreach (ManagementObject obj in searcher.Get())
                {
                    return obj["CommandLine"]?.ToString();
                }
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
            return !string.IsNullOrEmpty(path)
                && Directory.Exists(path)
                && File.Exists(Path.Combine(path, ClientProcessName))
                && File.Exists(Path.Combine(path, ClientUxProcessName));
        }
    }
}