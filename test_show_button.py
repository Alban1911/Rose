#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simple test script to display the chroma button and wheel for Mythmaker Garen
Run this to preview the wheel and button with your current constants.py settings
"""

import sys
import signal
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

# Import the chroma wheel components
from utils.chroma_wheel import ChromaWheelWidget, ReopenButton


class TestManager:
    """Manages the button and wheel for testing"""
    
    def __init__(self):
        self.wheel = None
        self.button = None
        self.wheel_opened = False  # Track wheel open/closed state
        # Real Mythmaker Garen chroma IDs from README.md
        self.chromas = [
            {'id': 86034, 'name': 'Mythmaker Garen', 'colors': ['#FFD700', '#FF8C00']},
            {'id': 86035, 'name': 'Mythmaker Garen', 'colors': ['#FFA500', '#FF6347']},
            {'id': 86036, 'name': 'Mythmaker Garen', 'colors': ['#32CD32', '#00FA9A']},
            {'id': 86037, 'name': 'Mythmaker Garen', 'colors': ['#2F4F4F', '#1C1C1C']},
            {'id': 86038, 'name': 'Mythmaker Garen', 'colors': ['#F0F8FF', '#E6E6FA']},
            {'id': 86039, 'name': 'Mythmaker Garen', 'colors': ['#FFB6C1', '#FF69B4']},
            {'id': 86040, 'name': 'Mythmaker Garen', 'colors': ['#DC143C', '#B22222']},
            {'id': 86041, 'name': 'Mythmaker Garen', 'colors': ['#4169E1', '#1E90FF']},
            {'id': 86042, 'name': 'Mythmaker Garen', 'colors': ['#9370DB', '#8A2BE2']},
            {'id': 86045, 'name': 'Mythmaker Garen', 'colors': ['#40E0D0', '#00CED1']},
        ]
    
    def on_button_clicked(self):
        """Called when button is clicked - toggle wheel open/closed"""
        # Prevent button from hiding
        if self.button:
            self.button.is_hiding = False
        
        if self.wheel_opened:
            # Wheel is open, close it
            print("✓ Button clicked! Closing wheel...")
            self.wheel_opened = False
            if self.wheel:
                self.wheel.hide()
        else:
            # Wheel is closed, open it
            print("✓ Button clicked! Opening wheel...")
            self.wheel_opened = True
            if self.wheel:
                self.wheel.show_wheel()
                self.wheel.setVisible(True)
                self.wheel.raise_()
        
        # Force button to stay visible and on top after any operation
        if self.button:
            self.button.is_hiding = False
            self.button.setVisible(True)
            self.button.show()
            self.button.raise_()
            self.button.activateWindow()
            self.button.update()  # Force repaint
    
    def on_chroma_selected(self, chroma_id: int, chroma_name: str):
        """Called when a chroma is selected in the wheel"""
        if chroma_id == 0:
            print(f"✓ Selected: Base Mythmaker Garen (no chroma)")
        else:
            print(f"✓ Selected: {chroma_name} chroma (ID: {chroma_id})")
        
        # Close the wheel after selection (button remains visible)
        self.wheel_opened = False
        if self.wheel:
            self.wheel.hide()
        
        # Ensure button stays visible and on top
        if self.button:
            self.button.show()
            self.button.raise_()
            self.button.activateWindow()
    
    def start(self):
        """Initialize and show the button"""
        # Check if previews are available
        from utils.chroma_preview_manager import get_preview_manager
        preview_manager = get_preview_manager()
        
        missing_previews = []
        for chroma in self.chromas:
            if not preview_manager.get_preview_path(chroma['id']):
                missing_previews.append(chroma['id'])
        
        if missing_previews:
            print()
            print("⚠️  WARNING: Chroma previews not found!")
            print(f"   Missing preview IDs: {missing_previews}")
            print()
            print("   To download previews, run:")
            print("   python test_download_garen_previews.py")
            print()
            print("   Continuing anyway (will show colored circles instead)...")
            print()
        
        # Create the chroma wheel widget (hidden initially)
        self.wheel = ChromaWheelWidget(on_chroma_selected=self.on_chroma_selected)
        self.wheel.set_chromas("Mythmaker Garen", self.chromas, "Garen")
        self.wheel.hide()  # Keep it hidden until button is clicked
        
        # Create and show the button
        self.button = ReopenButton(on_click=self.on_button_clicked)
        # Force the button to stay visible by overriding its hiding behavior
        self.button.is_hiding = False  # Prevent hide flag from being set
        self.button.setVisible(True)
        self.button.show()
        self.button.raise_()
        self.button.activateWindow()


def main():
    """Main test function"""
    print("=" * 70)
    print("🎨 Mythmaker Garen Chroma Button & Wheel Test")
    print("=" * 70)
    from constants import (
        CHROMA_WHEEL_GOLD_BORDER_PX,
        CHROMA_WHEEL_DARK_BORDER_PX,
        CHROMA_WHEEL_GRADIENT_RING_PX,
        CHROMA_WHEEL_INNER_DISK_RADIUS_PX,
        CHROMA_WHEEL_BUTTON_SIZE
    )
    print(f"Button size: {CHROMA_WHEEL_BUTTON_SIZE}px")
    print(f"Gold border: {CHROMA_WHEEL_GOLD_BORDER_PX}px")
    print(f"Dark border: {CHROMA_WHEEL_DARK_BORDER_PX}px")
    print(f"Gradient ring: {CHROMA_WHEEL_GRADIENT_RING_PX}px")
    print(f"Inner disk radius: {CHROMA_WHEEL_INNER_DISK_RADIUS_PX}px")
    print()
    print("✓ Button appears in the CENTER of your screen (stays visible)")
    print("✓ CLICK the button to TOGGLE the chroma wheel (open/close)")
    print("✓ Select a chroma to close wheel and apply selection")
    print("✓ Button remains visible - click again to reopen wheel")
    print("✓ Press Ctrl+C or close the button window to exit")
    print("=" * 70)
    
    # Create Qt application
    app = QApplication(sys.argv)
    
    # Setup signal handlers for clean exit on Ctrl+C
    def signal_handler(signum, frame):
        """Handle Ctrl+C gracefully"""
        print("\n✓ Ctrl+C received - exiting...")
        app.quit()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Setup a timer to process Python signals (allows Ctrl+C to work)
    timer = QTimer()
    timer.start(500)  # Check for signals every 500ms
    timer.timeout.connect(lambda: None)  # Wake up Python interpreter
    
    # Create and start test manager
    manager = TestManager()
    manager.start()
    
    # Run application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
