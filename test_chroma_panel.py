#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script for Chroma Wheel - Mythmaker Garen
Demonstrates the chroma selection UI and button interaction
"""

import sys
import signal
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QPixmap
from utils.chroma_wheel import ChromaWheelWidget, OpeningButton
from utils.chroma_preview_manager import get_preview_manager
from utils.logging import setup_logging, get_logger

# Setup logging
setup_logging(verbose=True)
log = get_logger()


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


def main():
    """Main test function"""
    print("\n" + "="*60)
    print("CHROMA WHEEL TEST - MYTHMAKER GAREN")
    print("="*60)
    print("\nThis test demonstrates the chroma wheel UI:")
    print("  - Base skin (red X in center)")
    print("  - 10 chroma variants in a horizontal row")
    print("  - Hover over circles to preview")
    print("  - Click to select a chroma")
    print("  - Press ESC to cancel (select base)")
    print("  - Press ENTER to confirm current selection")
    print("  - Press CTRL+C to exit test")
    print("\n" + "="*60 + "\n")
    
    # Create Qt application
    app = QApplication(sys.argv)
    
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
    timer = QTimer()
    timer.timeout.connect(lambda: None)  # Do nothing, just let Python process signals
    timer.start(100)  # Check every 100ms
    
    # Create chroma wheel widget
    wheel = ChromaWheelWidget(on_chroma_selected=on_chroma_selected)
    
    # Get Mythmaker Garen chromas with real IDs
    test_chromas = create_mythmaker_garen_chromas()
    
    # Load preview images from cache using the same logic as main app
    log.info("Loading preview images from cache...")
    preview_manager = get_preview_manager()
    
    loaded_count = 0
    for chroma in test_chromas:
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
    
    log.info(f"Loaded {loaded_count}/{len(test_chromas)} preview images from cache")
    
    # Set chromas on the wheel
    wheel.set_chromas(
        skin_name="Mythmaker Garen",
        chromas=test_chromas,
        champion_name="Garen",
        selected_chroma_id=None  # Start with no chroma selected (base skin)
    )
    
    # Manually set the preview images on the circles (loaded from cache)
    for i, chroma in enumerate(test_chromas):
        if i < len(wheel.circles) - 1:  # Skip base (index 0)
            circle_index = i + 1  # Offset by 1 because base is index 0
            if circle_index < len(wheel.circles) and 'preview_pixmap' in chroma:
                wheel.circles[circle_index].preview_image = chroma['preview_pixmap']
    
    log.info("Preview images attached to wheel circles")
    
    # Create the reopen button
    def on_button_click():
        """Toggle the wheel visibility"""
        if wheel.isVisible():
            log.info("Closing chroma wheel")
            wheel.hide()
            button.set_wheel_open(False)
        else:
            log.info("Opening chroma wheel")
            # Position wheel above button
            button_pos = button.pos()
            wheel.show_wheel(button_pos=button_pos)
            button.set_wheel_open(True)
    
    button = OpeningButton(on_click=on_button_click)
    wheel.set_button_reference(button)
    
    # Show the button and open the wheel initially
    button.show()
    button.raise_()
    
    # Open the wheel after a short delay to ensure button is fully initialized
    def open_wheel_delayed():
        button_pos = button.pos()
        wheel.show_wheel(button_pos=button_pos)
        button.set_wheel_open(True)
        log.info("Chroma wheel opened - hover over circles to preview, click to select")
    
    QTimer.singleShot(100, open_wheel_delayed)
    
    print("Test started - interact with the UI")
    print("    Button: Click to toggle wheel open/closed")
    print("    Wheel: Hover to preview, click to select")
    print("    Keyboard: ESC=cancel, ENTER=confirm\n")
    
    # Start the application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

