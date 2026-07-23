using System;
using System.ComponentModel;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using PenguLoader.Main;
using Forms = System.Windows.Forms;

namespace PenguLoader.Views
{
    public partial class MainPage : Page, INotifyPropertyChanged
    {
        public event PropertyChangedEventHandler PropertyChanged;
        void TriggerPropertyChanged(string name) => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));

        Window Owner => Window.GetWindow(this);

        public bool OptimizeClient
        {
            get => Config.OptimizeClient;
            set
            {
                Logger.Info("MainPage", $"OptimizeClient setter called: value={value}");

                if (value == true)
                {
                    var caption = App.GetTranslation("t_optimize_client");
                    var message = App.GetTranslation("t_msg_optimize_client_prompt");

                    value = MessageBox.Show(Owner, message, caption,
                        MessageBoxButton.YesNo, MessageBoxImage.Information) == MessageBoxResult.Yes;

                    Logger.Info("MainPage", $"OptimizeClient confirmation result: {value}");
                }

                Config.OptimizeClient = value;
                TriggerPropertyChanged(nameof(OptimizeClient));
                Logger.Info("MainPage", $"OptimizeClient set to: {Config.OptimizeClient}");
            }
        }

        public bool SuperLowSpecMode
        {
            get => Config.SuperLowSpecMode;
            set
            {
                Logger.Info("MainPage", $"SuperLowSpecMode setter called: value={value}");

                if (value == true)
                {
                    var caption = App.GetTranslation("t_super_potato_mode");
                    var message = App.GetTranslation("t_msg_super_potato_mode_prompt");

                    value = MessageBox.Show(Owner, message, caption,
                        MessageBoxButton.YesNo, MessageBoxImage.Information) == MessageBoxResult.Yes;

                    Logger.Info("MainPage", $"SuperLowSpecMode confirmation result: {value}");
                }

                Config.SuperLowSpecMode = value;
                TriggerPropertyChanged(nameof(SuperLowSpecMode));
                Logger.Info("MainPage", $"SuperLowSpecMode set to: {Config.SuperLowSpecMode}");
            }
        }

        public bool IsActivated
        {
            get => Module.IsFound && Module.IsActivated;
            set
            {
                Logger.Info("MainPage", $"========================================");
                Logger.Info("MainPage", $"IsActivated setter called: requested={value}");
                Logger.Info("MainPage", $"  Module.IsFound: {Module.IsFound}");
                Logger.Info("MainPage", $"  Module.IsActivated: {Module.IsActivated}");
                Logger.Info("MainPage", $"  Module.IsLoaded: {Module.IsLoaded}");
                Logger.Info("MainPage", $"  LCU.IsRunning: {LCU.IsRunning}");
                Logger.Info("MainPage", $"  Config.LeaguePath: {Config.LeaguePath}");

                if (!Module.IsFound)
                {
                    Logger.Error("MainPage", "Module not found! Showing error to user.");
                    MessageBox.Show(Owner, App.GetTranslation("t_msg_module_not_found"),
                         Program.Name, MessageBoxButton.OK, MessageBoxImage.Warning);

                    Module.SetActive(false);
                    TriggerPropertyChanged(nameof(IsActivated));
                    return;
                }

                try
                {
                    if (!LCU.IsValidDir(Config.LeaguePath))
                    {
                        Logger.Info("MainPage", "LeaguePath not valid, prompting user to select...");
                        if (!DoSelectLeaguePath())
                        {
                            Logger.Info("MainPage", "User cancelled path selection");
                            return;
                        }
                        Logger.Info("MainPage", $"User selected LeaguePath: {Config.LeaguePath}");
                    }

                    Logger.Info("MainPage", $"Calling Module.SetActive({value})...");
                    var success = Module.SetActive(value);
                    Logger.Info("MainPage", $"Module.SetActive returned: {success}");

                    if (!success)
                    {
                        Logger.Error("MainPage", $"SetActive FAILED! Requested {value} but activation state is {Module.IsActivated}");
                        MessageBox.Show(Owner,
                            $"Failed to {(value ? "activate" : "deactivate")} Rose. Check rose.log for details.",
                            Program.Name, MessageBoxButton.OK, MessageBoxImage.Warning);
                    }

                    TriggerPropertyChanged(nameof(IsActivated));
                    Logger.Info("MainPage", $"UI updated. Current IsActivated: {IsActivated}");

                    if ((value && LCU.IsRunning) || (!value && Module.IsLoaded))
                    {
                        Logger.Info("MainPage", "League client is running, prompting for restart...");
                        if (MessageBox.Show(Owner, App.GetTranslation("t_msg_restart_client"),
                            Program.Name, MessageBoxButton.YesNo, MessageBoxImage.Question) == MessageBoxResult.Yes)
                        {
                            Logger.Info("MainPage", "User chose to restart client");
                            LCU.KillUxAndRestart();
                        }
                        else
                        {
                            Logger.Info("MainPage", "User declined client restart");
                        }
                    }
                }
                catch (Exception ex)
                {
                    Logger.Error("MainPage", "Exception during activation", ex);

                    var msg = App.GetTranslation("t_msg_activation_fail");
                    msg += string.Format("\n\n[{0}] - {1}\n{2}", ex.GetType().Name, ex.Message, ex.StackTrace);

                    if (ex.InnerException != null)
                        msg += string.Format("\n\nERR2: {0}\n{1}", ex.InnerException.Message, ex.InnerException.StackTrace);

                    msg += "\n\nCheck rose.log for more details.\n\nOpen issues page?";

                    if (MessageBox.Show(Owner, msg, Program.Name, MessageBoxButton.YesNo, MessageBoxImage.Warning)
                        == MessageBoxResult.Yes)
                    {
                        Utils.OpenLink(Program.GithubIssuesUrl);
                    }
                }

                Logger.Info("MainPage", $"IsActivated setter completed");
                Logger.Info("MainPage", $"========================================");
            }
        }

        public MainPage()
        {
            Logger.Info("MainPage", "MainPage constructor called");
            InitializeComponent();

            SetLeaguePath(Config.LeaguePath);
            gLeaguePath.Visibility = Visibility.Visible;

            DataContext = this;
            Logger.Info("MainPage", "MainPage initialized");
        }

        private void DiscordButtonClick(object sender, RoutedEventArgs e)
        {
            Logger.Debug("MainPage", "Discord button clicked");
            Utils.OpenLink(Program.DiscordUrl);
        }

        private void GitHubButtonClick(object sender, RoutedEventArgs e)
        {
            Logger.Debug("MainPage", "GitHub button clicked");
            Utils.OpenLink(Program.GithubUrl);
        }

        private void HomePageButtonClick(object sender, RoutedEventArgs e)
        {
            Logger.Debug("MainPage", "HomePage button clicked");
            Utils.OpenLink(Program.HomepageUrl);
        }

        bool DoSelectLeaguePath()
        {
            Logger.Info("MainPage", "DoSelectLeaguePath called");

            // First, try to get path from Rose config.ini
            var rosePath = GetRoseConfigPath();
            if (!string.IsNullOrWhiteSpace(rosePath) && LCU.IsValidDir(rosePath))
            {
                Logger.Info("MainPage", $"Found valid path in Rose config: {rosePath}");
                Config.LeaguePath = rosePath;
                SetLeaguePath(rosePath);
                return true;
            }

            Logger.Info("MainPage", "No valid path in Rose config, showing folder picker");

            var fbd = new Ookii.Dialogs.Wpf.VistaFolderBrowserDialog();
            fbd.Description = "Select Riot Games, League of Legends or LeagueClient folder.";
            fbd.UseDescriptionForTitle = true;

            if (fbd.ShowDialog() == true && !string.IsNullOrWhiteSpace(fbd.SelectedPath))
            {
                var path = fbd.SelectedPath;
                var selected = fbd.SelectedPath;
                Logger.Info("MainPage", $"User selected folder: {selected}");

                if (LCU.IsValidDir(path))
                {
                    Logger.Info("MainPage", $"Path is valid directly: {path}");
                }
                else if (LCU.IsValidDir(path = Path.Combine(selected, "LeagueClient")))
                {
                    Logger.Info("MainPage", $"Path valid with LeagueClient subfolder: {path}");
                }
                else if (LCU.IsValidDir(path = Path.Combine(selected, "League of Legends")))
                {
                    Logger.Info("MainPage", $"Path valid with League of Legends subfolder: {path}");
                }
                else if (LCU.IsValidDir(path = Path.Combine(selected, "Riot Games", "League of Legends")))
                {
                    Logger.Info("MainPage", $"Path valid with Riot Games/League of Legends subfolder: {path}");
                }
                else
                {
                    Logger.Warn("MainPage", $"Selected path is not valid: {selected}");
                    MessageBox.Show(Owner, "Your selected folder is not valid, please make sure it contains \"LeagueClient.exe\".",
                        Program.Name, MessageBoxButton.OK, MessageBoxImage.Warning);
                    return false;
                }

                Config.LeaguePath = path;
                SetLeaguePath(path);
                Logger.Info("MainPage", $"LeaguePath set to: {path}");
                return true;
            }

            Logger.Info("MainPage", "User cancelled folder selection");
            return false;
        }

        string GetRoseConfigPath()
        {
            try
            {
                var localAppData = DesktopUser.GetLocalAppData();
                var configPath = Path.Combine(localAppData, "Rose", "config.ini");

                Logger.Debug("MainPage", $"Checking Rose config at: {configPath}");

                if (!File.Exists(configPath))
                {
                    Logger.Debug("MainPage", "Rose config.ini does not exist");
                    return string.Empty;
                }

                var lines = File.ReadAllLines(configPath);
                bool inGeneralSection = false;

                foreach (var line in lines)
                {
                    var trimmed = line.Trim();

                    if (trimmed.StartsWith("[") && trimmed.EndsWith("]"))
                    {
                        inGeneralSection = trimmed.Equals("[General]", StringComparison.OrdinalIgnoreCase);
                        continue;
                    }

                    if (inGeneralSection)
                    {
                        var parts = trimmed.Split(new[] { '=' }, 2);
                        if (parts.Length == 2)
                        {
                            var key = parts[0].Trim();
                            var value = parts[1].Trim();

                            if (key.Equals("clientpath", StringComparison.OrdinalIgnoreCase))
                            {
                                Logger.Debug("MainPage", $"Found clientpath in Rose config: {value}");

                                if (string.IsNullOrWhiteSpace(value))
                                    return string.Empty;

                                value = value.TrimEnd('\\', '/');

                                if (LCU.IsValidDir(value))
                                {
                                    Logger.Debug("MainPage", $"clientpath is valid: {value}");
                                    return value;
                                }

                                var withSubdir = value + "\\LeagueClient";
                                if (LCU.IsValidDir(withSubdir))
                                {
                                    Logger.Debug("MainPage", $"clientpath valid with LeagueClient subdir: {withSubdir}");
                                    return withSubdir;
                                }

                                Logger.Debug("MainPage", $"clientpath not valid, returning as-is: {value}");
                                return value;
                            }
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Logger.Error("MainPage", "Failed to read Rose config", ex);
            }

            return string.Empty;
        }

        void SetLeaguePath(string path)
        {
            Logger.Debug("MainPage", $"SetLeaguePath called: {path}");

            if (string.IsNullOrEmpty(path) || !LCU.IsValidDir(path))
            {
                Config.LeaguePath = string.Empty;
                tLeaguePath.Text = "[not selected]";
                Logger.Debug("MainPage", "LeaguePath cleared (invalid or empty)");
            }
            else
            {
                if (path.Length > 60)
                    path = path.Substring(0, 60) + "...";

                tLeaguePath.Text = path;
            }
        }

        void LeaguePath_MouseEnter(object s, System.Windows.Input.MouseEventArgs e)
        {
            (s as TextBlock).Background = new SolidColorBrush(Color.FromArgb(0x40, 0x80, 0x80, 0x80));
        }

        void LeaguePath_MouseLeave(object s, System.Windows.Input.MouseEventArgs e)
        {
            (s as TextBlock).Background = Brushes.Transparent;
        }

        void LeaguePath_MouseUp(object sender, System.Windows.Input.MouseButtonEventArgs e)
        {
            if (e.ChangedButton == System.Windows.Input.MouseButton.Left
                && e.LeftButton == System.Windows.Input.MouseButtonState.Released)
            {
                Logger.Info("MainPage", "User clicked to change LeaguePath");
                IsActivated = false;
                DoSelectLeaguePath();
            }
        }
    }
}
