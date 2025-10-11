#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script for Chroma Panel - Mythmaker Garen
Demonstrates the chroma selection UI and button interaction
Includes HOT-RELOAD: automatically rebuilds UI when config.py changes!
"""

import sys
import signal
import os
import importlib
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QPixmap
from utils.chroma_panel_widget import ChromaPanelWidget
from utils.chroma_button import OpeningButton
from utils.chroma_preview_manager import get_preview_manager
from utils.logging import setup_logging, get_logger

# Setup logging
setup_logging(verbose=True)
log = get_logger()

# Global state for hot reload
_widgets = {'panel': None, 'button': None}
_test_chromas = None
_app = None
_selected_chroma_id = None  # Track currently selected chroma across rebuilds


def create_mythmaker_garen_chromas():
    """
    Create test data for Mythmaker Garen chromas using REAL chroma IDs
    
    Mythmaker Garen chromas (IDs from preview cache):
    86045-86054 appear to be the Mythmaker Garen skin chromas
    """
    # Real Mythmaker Garen chroma IDs (based on preview cache files)
    # These are actual IDs from League of Legends
    chroma_ids = [86045, 86047, 86048, 86049, 86050, 86051, 86052, 86053, 86054]
    
    # Color mapping based on typical Mythmaker chromas
    chroma_data = [
        (86045, 'Amethyst', '9b59b6'),
        (86047, 'Catseye', '9acd32'),
        (86048, 'Emerald', '2ecc71'),
        (86049, 'Gilded', 'ffd700'),
        (86050, 'Paragon', 'c0c0c0'),
        (86051, 'Pearl', 'f0f8ff'),
        (86052, 'Rose Quartz', 'ff69b4'),
        (86053, 'Ruby', 'e74c3c'),
        (86054, 'Sapphire', '3498db'),
    ]
    
    chromas = []
    for chroma_id, name, color in chroma_data:
        chromas.append({
            'id': chroma_id,
            'name': f'Mythmaker Garen {name}',
            'colors': [color]
        })
    
    return chromas


def on_chroma_selected(chroma_id: int, chroma_name: str):
    """Callback when a chroma is selected"""
    global _selected_chroma_id
    
    # Update selected chroma ID (0 means base skin)
    _selected_chroma_id = chroma_id if chroma_id != 0 else None
    
    if chroma_id == 0:
        log.info("Base skin selected (no chroma)")
        print("\n" + "="*60)
        print("SELECTED: Base Mythmaker Garen (No Chroma)")
        print("="*60 + "\n")
    else:
        log.info(f"Chroma selected: {chroma_name} (ID: {chroma_id})")
        print("\n" + "="*60)
        print(f"SELECTED: {chroma_name}")
        print(f"   Chroma ID: {chroma_id}")
        print("="*60 + "\n")


def reload_config_module():
    """Force reload of config module to get fresh values in ALL modules"""
    try:
        # Reload config module
        import config
        importlib.reload(config)
        
        # Reload all modules that import config to pick up new values
        from utils import chroma_scaling, chroma_base, chroma_panel_widget, chroma_button
        importlib.reload(chroma_scaling)
        importlib.reload(chroma_base)
        importlib.reload(chroma_panel_widget)
        importlib.reload(chroma_button)
        
        log.info("✅ Config and all dependent modules reloaded successfully")
    except Exception as e:
        log.error(f"❌ Error reloading config: {e}")
        import traceback
        log.error(traceback.format_exc())


def create_widgets():
    """Create or recreate the panel and button widgets"""
    global _widgets, _test_chromas, _selected_chroma_id
    
    # Save visibility state if widgets exist
    panel_was_visible = False
    button_was_visible = False
    
    if _widgets['panel']:
        panel_was_visible = _widgets['panel'].isVisible()
    if _widgets['button']:
        button_was_visible = _widgets['button'].isVisible()
    
    # Destroy existing widgets
    if _widgets['panel']:
        try:
            _widgets['panel'].hide()
            _widgets['panel'].deleteLater()
        except:
            pass
    if _widgets['button']:
        try:
            _widgets['button'].hide()
            _widgets['button'].deleteLater()
        except:
            pass
    
    # Process pending deletions
    QApplication.processEvents()
    
    # Create new panel widget
    panel = ChromaPanelWidget(on_chroma_selected=on_chroma_selected, manager=None)
    
    # Set chromas on the panel, preserving the selected chroma
    log.info(f"Creating panel with selected chroma ID: {_selected_chroma_id}")
    panel.set_chromas(
        skin_name="Mythmaker Garen",
        chromas=_test_chromas,
        champion_name="Garen",
        selected_chroma_id=_selected_chroma_id  # Use tracked selection
    )
    
    # Manually set the preview images on the circles
    for i, chroma in enumerate(_test_chromas):
        if i < len(panel.circles) - 1:
            circle_index = i + 1
            if circle_index < len(panel.circles) and 'preview_pixmap' in chroma:
                panel.circles[circle_index].preview_image = chroma['preview_pixmap']
    
    # Create the reopen button
    def on_button_click():
        """Toggle the panel visibility"""
        if panel.isVisible():
            log.info("Closing chroma panel")
            panel.hide()
            button.set_wheel_open(False)
        else:
            log.info("Opening chroma panel")
            button_pos = button.pos()
            panel.show_wheel(button_pos=button_pos)
            button.set_wheel_open(True)
    
    button = OpeningButton(on_click=on_button_click, manager=None)
    panel.set_button_reference(button)
    
    # Store new widgets
    _widgets['panel'] = panel
    _widgets['button'] = button
    
    # Restore visibility state
    if button_was_visible:
        button.show()
        button.raise_()
    if panel_was_visible:
        button_pos = button.pos()
        panel.show_wheel(button_pos=button_pos)
        button.set_wheel_open(True)
    
    return panel, button


def setup_config_watcher():
    """Setup file watcher for config.py to enable hot-reload"""
    config_path = Path(__file__).parent / "config.py"
    last_mtime = os.path.getmtime(config_path) if config_path.exists() else 0
    
    def check_config_changes():
        nonlocal last_mtime
        try:
            current_mtime = os.path.getmtime(config_path)
            if current_mtime != last_mtime:
                last_mtime = current_mtime
                print("\n" + "🔄 " + "="*58)
                print("   CONFIG.PY CHANGED - REBUILDING UI...")
                print("="*60 + "\n")
                log.info("config.py modified - triggering hot reload")
                
                # Reload config module
                reload_config_module()
                
                # Rebuild widgets with new config
                create_widgets()
                
                # Show the button (preserve panel visibility state)
                _widgets['button'].show()
                _widgets['button'].raise_()
                
                # Only reopen panel if it was visible before rebuild
                if _widgets['panel'] and _widgets['panel'].isVisible():
                    def reopen_panel():
                        button_pos = _widgets['button'].pos()
                        _widgets['panel'].show_wheel(button_pos=button_pos)
                        _widgets['button'].set_wheel_open(True)
                    
                    QTimer.singleShot(100, reopen_panel)
                
                print("✅ UI Rebuilt with new config values!\n")
        except Exception as e:
            log.error(f"Error checking config changes: {e}")
    
    # Check for config changes every 500ms
    timer = QTimer()
    timer.timeout.connect(check_config_changes)
    timer.start(500)
    
    return timer


def setup_resolution_watcher():
    """Setup watcher for League resolution changes to trigger rebuild"""
    from utils.window_utils import get_league_window_client_size
    
    last_resolution = get_league_window_client_size()
    
    def check_resolution_changes():
        nonlocal last_resolution
        try:
            current_resolution = get_league_window_client_size()
            
            # Check if resolution changed
            if current_resolution and current_resolution != last_resolution:
                old_res = last_resolution if last_resolution else "None"
                last_resolution = current_resolution
                
                width, height = current_resolution
                print("\n" + "🔄 " + "="*58)
                print(f"   RESOLUTION CHANGED: {old_res} → {width}x{height}")
                print("   REBUILDING UI WITH NEW DIMENSIONS...")
                print("="*60 + "\n")
                log.info(f"Resolution changed from {old_res} to {current_resolution} - rebuilding widgets")
                
                # Reload scaling module to recalculate dimensions
                from utils import chroma_scaling
                importlib.reload(chroma_scaling)
                
                # Rebuild widgets with new dimensions
                create_widgets()
                
                # Show the button (preserve panel visibility state)
                _widgets['button'].show()
                _widgets['button'].raise_()
                
                # Only reopen panel if it was visible before rebuild
                if _widgets['panel'] and _widgets['panel'].isVisible():
                    def reopen_panel():
                        button_pos = _widgets['button'].pos()
                        _widgets['panel'].show_wheel(button_pos=button_pos)
                        _widgets['button'].set_wheel_open(True)
                    
                    QTimer.singleShot(100, reopen_panel)
                
                print(f"✅ UI Rebuilt for {width}x{height} resolution!\n")
        except Exception as e:
            log.error(f"Error checking resolution changes: {e}")
    
    # Check for resolution changes every 1 second
    timer = QTimer()
    timer.timeout.connect(check_resolution_changes)
    timer.start(1000)
    
    return timer


def check_league_window():
    """Check if League of Legends window is found - REQUIRED for UI to work"""
    from utils.window_utils import get_league_window_handle, get_league_window_client_size
    import sys
    
    hwnd = get_league_window_handle()
    if not hwnd:
        print("\n" + "❌ " + "="*58)
        print("   ERROR: League of Legends window not found!")
        print("   The ChromaUI requires League to be running.")
        print("   Please:")
        print("     1. Start League of Legends")
        print("     2. Enter Champion Select (or Practice Tool)")
        print("     3. Run this test again")
        print("="*60 + "\n")
        sys.exit(1)  # Exit - UI cannot work without League
    
    size = get_league_window_client_size()
    if size:
        width, height = size
        print(f"✅ League window found: {width}x{height}")
        return True
    
    print("\n" + "❌ ERROR: Could not get League window size")
    sys.exit(1)


def main():
    """Main test function"""
    global _app, _test_chromas
    
    print("\n" + "="*60)
    print("CHROMA PANEL TEST - MYTHMAKER GAREN")
    print("="*60)
    print("\nThis test demonstrates the chroma panel UI:")
    print("  - Base skin (red X in center)")
    print("  - 10 chroma variants in a horizontal row")
    print("  - Hover over circles to preview")
    print("  - Click to select a chroma")
    print("  - Press ESC to cancel (select base)")
    print("  - Press ENTER to confirm current selection")
    print("  - Press CTRL+C to exit test")
    print("\n🔥 HOT-RELOAD ENABLED:")
    print("  - Edit config.py values (e.g., CHROMA_UI_PANEL_OFFSET_Y_BASE_RATIO)")
    print("  - Save the file")
    print("  - UI will automatically rebuild with new values!")
    print("\n📍 POSITIONING:")
    print("  - UI will position relative to League window if found")
    print("  - Make sure League is running in Champion Select!")
    print("\n🔄 AUTO-REBUILD:")
    print("  - Change League resolution (1024x576, 1280x720, 1600x900)")
    print("  - UI will automatically rebuild with correct dimensions!")
    print("\n" + "="*60 + "\n")
    
    # Check for League window
    check_league_window()
    
    # Create Qt application
    app = QApplication(sys.argv)
    _app = app
    
    # Setup signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        """Handle CTRL+C gracefully"""
        print("\n\n" + "="*60)
        print("CTRL+C detected - shutting down test...")
        print("="*60 + "\n")
        log.info("Test interrupted by user (CTRL+C)")
        app.quit()
        sys.exit(0)
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Create a timer to allow Python to process signals periodically
    # This is needed because Qt's event loop blocks signal handling
    signal_timer = QTimer()
    signal_timer.timeout.connect(lambda: None)
    signal_timer.start(100)
    
    # Get Mythmaker Garen chromas with real IDs
    _test_chromas = create_mythmaker_garen_chromas()
    
    # Load preview images from cache using the same logic as main app
    log.info("Loading preview images from cache...")
    preview_manager = get_preview_manager()
    
    loaded_count = 0
    for chroma in _test_chromas:
        chroma_id = chroma['id']
        preview_path = preview_manager.get_preview_path(chroma_id)
        
        if preview_path:
            pixmap = QPixmap(str(preview_path))
            chroma['preview_pixmap'] = pixmap
            loaded_count += 1
            log.debug(f"Loaded preview for chroma {chroma_id}: {chroma['name']}")
        else:
            chroma['preview_pixmap'] = None
            log.warning(f"No preview found for chroma {chroma_id}: {chroma['name']}")
    
    log.info(f"Loaded {loaded_count}/{len(_test_chromas)} preview images from cache")
    
    # Create initial widgets
    panel, button = create_widgets()
    
    # Setup config file watcher for hot-reload
    config_watcher = setup_config_watcher()
    
    # Setup resolution watcher for automatic rebuild on resolution change
    resolution_watcher = setup_resolution_watcher()
    
    # Show only the button initially (panel closed, like main app)
    button.show()
    button.raise_()
    
    print("Test started - interact with the UI")
    print("    🎯 Click the button to open the chroma panel")
    print("    Panel: Hover to preview, click to select")
    print("    Keyboard: ESC=cancel, ENTER=confirm")
    print("    🔥 Edit config.py and save to see changes instantly!\n")
    
    # Start the application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

