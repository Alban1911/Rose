using System;
using System.ComponentModel;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using PenguLoader.Main;

namespace PenguLoader.Views
{
    public partial class PluginsPage : Page, INotifyPropertyChanged
    {
        public event PropertyChangedEventHandler PropertyChanged;
        void OnPropertyChanged(string name) => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));

        bool _loading = false;
        public bool IsDone => !_loading;
        public bool IsLoading
        {
            get => _loading;
            set
            {
                _loading = value;
                OnPropertyChanged(nameof(IsLoading));
                OnPropertyChanged(nameof(IsDone));
            }
        }

        public PluginsPage()
        {
            InitializeComponent();
            Loaded += RefreshPluginsClick;
            DataContext = this;
        }

        private void ShowFolderClick(object sender, RoutedEventArgs e)
        {
            Utils.OpenFolder(Config.PluginsDir);
        }

        private async void RefreshPluginsClick(object sender, RoutedEventArgs e)
        {
            if (IsLoading) return;

            IsLoading = true;
            _plugins.Items.Clear();

            var plugins = Plugins.All();
            _count.Text = plugins.Count.ToString();

            await Task.Delay(500);

            foreach (var plugin in plugins)
            {
                var item = new PluginItem(plugin);
                _plugins.Items.Add(item);
            }

            IsLoading = false;
        }
    }
}