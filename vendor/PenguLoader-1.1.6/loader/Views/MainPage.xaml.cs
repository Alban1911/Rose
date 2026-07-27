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
                if (value == true)
                {
                    var caption = App.GetTranslation("t_optimize_client");
                    var message = App.GetTranslation("t_msg_optimize_client_prompt");

                    value = MessageBox.Show(Owner, message, caption,
                        MessageBoxButton.YesNo, MessageBoxImage.Information) == MessageBoxResult.Yes;
                }

                Config.OptimizeClient = value;
                TriggerPropertyChanged(nameof(OptimizeClient));
            }
        }

        public bool SuperLowSpecMode
        {
            get => Config.SuperLowSpecMode;
            set
            {
                if (value == true)
                {
                    var caption = App.GetTranslation("t_super_potato_mode");
                    var message = App.GetTranslation("t_msg_super_potato_mode_prompt");

                    value = MessageBox.Show(Owner, message, caption,
                        MessageBoxButton.YesNo, MessageBoxImage.Information) == MessageBoxResult.Yes;
                }

                Config.SuperLowSpecMode = value;
                TriggerPropertyChanged(nameof(SuperLowSpecMode));
            }
        }

        public bool IsActivated
        {
            get => Module.IsFound && Module.IsActivated;
            set
            {
                if (!Module.IsFound)
                {
                    MessageBox.Show(Owner, App.GetTranslation("t_msg_module_not_found"),
                         Program.Name, MessageBoxButton.OK, MessageBoxImage.Warning);

                    Module.SetActive(false);
                    TriggerPropertyChanged(nameof(IsActivated));

                    return;
                }

                //if (!Utils.IsAdmin())
                //{
                //    MessageBox.Show(Owner, "Failed to perform activation, please make sure you are running Pengu Loader as Admin.",
                //        Program.Name, MessageBoxButton.OK, MessageBoxImage.Warning);

                //    return;
                //}

                try
                {
                    if (Config.UseSymlink && !LCU.IsValidDir(Config.LeaguePath))
                    {
                        if (!DoSelectLeaguePath())
                            return;
                    }

                    Module.SetActive(value);
                    TriggerPropertyChanged(nameof(IsActivated));

                    if ((value && LCU.IsRunning) || (!value && Module.IsLoaded))
                    {
                        if (MessageBox.Show(Owner, App.GetTranslation("t_msg_restart_client"),
                            Program.Name, MessageBoxButton.YesNo, MessageBoxImage.Question) == MessageBoxResult.Yes)
                        {
                            LCU.KillUxAndRestart();
                        }
                    }
                }
                catch (Exception ex)
                {
                    if (!Config.UseSymlink)
                    {
                        if (MessageBox.Show(Owner,
                            "Failed to activate the core module globally, want to use symlink mode locally?",
                            Program.Name, MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                        {
                            Config.UseSymlink = true;
                            SetLeaguePath(Config.LeaguePath);
                            gLeaguePath.Visibility = Visibility.Visible;
                            return;
                        }
                    }

                    var msg = App.GetTranslation("t_msg_activation_fail");
                    msg += string.Format("\n\n[{0}] - {1}\n{2}", ex.GetType().Name, ex.Message, ex.StackTrace);

                    if (ex.InnerException != null)
                        msg += string.Format("\n\nERR2: {0}\n{1}", ex.InnerException.Message, ex.InnerException.StackTrace);

                    msg += "\n\n";

                    if (MessageBox.Show(Owner, msg, Program.Name, MessageBoxButton.YesNo, MessageBoxImage.Warning)
                        == MessageBoxResult.Yes)
                    {
                        Utils.OpenLink(Program.GithubIssuesUrl);
                    }
                }
            }
        }

        public MainPage()
        {
            InitializeComponent();

            if (Config.UseSymlink)
            {
                SetLeaguePath(Config.LeaguePath);
                gLeaguePath.Visibility = Visibility.Visible;
            }
            else
            {
                tLeaguePath.Text = "";
                gLeaguePath.Visibility = Visibility.Collapsed;
            }

            DataContext = this;
        }

        private void DiscordButtonClick(object sender, RoutedEventArgs e)
        {
            Utils.OpenLink(Program.DiscordUrl);
        }

        private void GitHubButtonClick(object sender, RoutedEventArgs e)
        {
            Utils.OpenLink(Program.GithubUrl);
        }

        private void HomePageButtonClick(object sender, RoutedEventArgs e)
        {
            Utils.OpenLink(Program.HomepageUrl);
        }

        bool DoSelectLeaguePath()
        {
            var fbd = new Ookii.Dialogs.Wpf.VistaFolderBrowserDialog();
            fbd.Description = "Select Riot Games, League of Legends or LeagueClient folder.";
            fbd.UseDescriptionForTitle = true;

            if (fbd.ShowDialog() == true && !string.IsNullOrWhiteSpace(fbd.SelectedPath))
            {
                var path = fbd.SelectedPath;
                var selected = fbd.SelectedPath;

                if (LCU.IsValidDir(path)) { }
                else if (LCU.IsValidDir(path = Path.Combine(selected, "LeagueClient"))) { }
                else if (LCU.IsValidDir(path = Path.Combine(selected, "League of Legends"))) { }
                else if (LCU.IsValidDir(path = Path.Combine(selected, "Riot Games", "League of Legends"))) { }
                else
                {
                    MessageBox.Show(Owner, "Your selected folder is not valid, please make sure it contains \"LeagueClient.exe\".",
                        Program.Name, MessageBoxButton.OK, MessageBoxImage.Warning);
                    return false;
                }

                Config.LeaguePath = path;
                SetLeaguePath(path);
                return true;
            }

            return false;
        }

        void SetLeaguePath(string path)
        {
            if (string.IsNullOrEmpty(path) || !LCU.IsValidDir(path))
            {
                Config.LeaguePath = string.Empty;
                tLeaguePath.Text = "[not selected]";
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
                IsActivated = false;
                DoSelectLeaguePath();
            }
        }
    }
}