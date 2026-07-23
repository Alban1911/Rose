using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;

using ModernWpf;
using PenguLoader.Main;

namespace PenguLoader
{
    public partial class MainWindow : Window
    {
        public static MainWindow Instance { get; private set; }

        public MainWindow()
        {
            Instance = this;
            InitializeComponent();
            ShowInTaskbar = true;
            WindowStyle = WindowStyle.SingleBorderWindow;
            Loaded += WindowLoaded;
        }

        private void WindowLoaded(object sender, RoutedEventArgs e)
        {
            Loaded -= WindowLoaded;

            Topmost = true;
            Show();
            Topmost = false;

            GC.Collect();
            Updater.CheckUpdate();
        }

        private void ThemeButtonClick(object sender, RoutedEventArgs e)
        {
            var tm = ThemeManager.Current;
            var isLight = tm.ApplicationTheme == null
                ? tm.ActualApplicationTheme == ApplicationTheme.Light
                : tm.ApplicationTheme == ApplicationTheme.Light;

            tm.ApplicationTheme = isLight
                ? ApplicationTheme.Dark
                : ApplicationTheme.Light;
        }

        protected override void OnSourceInitialized(EventArgs e)
        {
            base.OnSourceInitialized(e);

            var hwnd = new WindowInteropHelper(this).EnsureHandle();
            var source = HwndSource.FromHwnd(hwnd);
            source.AddHook(new HwndSourceHook(WndProc));
        }

        private IntPtr WndProc(IntPtr hwnd, int msg, IntPtr wp, IntPtr lp, ref bool handled)
        {
            if (msg == Native.WM_SHOWME)
            {
                if (WindowState == WindowState.Minimized)
                    WindowState = WindowState.Normal;

                if (!IsVisible)
                    Show();

                Activate();
                handled = true;
            }

            return IntPtr.Zero;
        }

        private void MouseDragMove(object sender, System.Windows.Input.MouseButtonEventArgs e)
        {
            if (e.Source is TabControl && e.LeftButton == System.Windows.Input.MouseButtonState.Pressed)
            {
                DragMove();
            }
        }
    }
}