"""
Test script to verify license dialog works in windowed mode
Run this to test the license dialog before rebuilding the full app
"""

import sys
import ctypes

def test_license_dialog():
    """Test the license dialog functionality"""
    print("Testing license dialog...")
    
    # Test 1: Import tkinter
    try:
        import tkinter as tk
        from tkinter import messagebox, simpledialog
        print("✓ Tkinter imported successfully")
    except ImportError as e:
        print(f"✗ FAILED: Tkinter import error: {e}")
        return False
    
    # Test 2: Create root window
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        root.lift()
        root.focus_force()
        print("✓ Root window created successfully")
    except Exception as e:
        print(f"✗ FAILED: Root window creation error: {e}")
        return False
    
    # Test 3: Show error message
    try:
        messagebox.showerror(
            "Test Dialog",
            "This is a test error message.\n\nClick OK to continue to the input dialog."
        )
        print("✓ Error message shown successfully")
    except Exception as e:
        print(f"✗ FAILED: Error message error: {e}")
        root.destroy()
        return False
    
    # Test 4: Show input dialog
    try:
        license_key = simpledialog.askstring(
            "Test Input",
            "Enter any text to test input dialog:",
            parent=root
        )
        print(f"✓ Input dialog shown successfully")
        print(f"  User entered: {repr(license_key)}")
    except Exception as e:
        print(f"✗ FAILED: Input dialog error: {e}")
        root.destroy()
        return False
    
    # Test 5: Clean up
    try:
        root.destroy()
        print("✓ Root window destroyed successfully")
    except Exception as e:
        print(f"⚠ Warning: Root window destruction error: {e}")
    
    print("\n✓ All tests passed!")
    return True

if __name__ == "__main__":
    print("=" * 60)
    print("LeagueUnlocked - License Dialog Test")
    print("=" * 60)
    print()
    
    success = test_license_dialog()
    
    print()
    if success:
        print("✓ License dialog is working correctly!")
        print("  You can now rebuild your PyInstaller app.")
    else:
        print("✗ License dialog test failed!")
        print("  Please fix the issues before rebuilding.")
    
    print()
    input("Press Enter to exit...")

