#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Admin rights utilities for Windows
Handles elevation and Task Scheduler registration for auto-start

Security Notes:
    - subprocess calls use only trusted, hardcoded commands (schtasks)
    - sys.executable is used for elevation - points to current Python/frozen executable
    - No user input is passed directly to subprocess commands
    - All subprocess calls use CREATE_NO_WINDOW to prevent console flashing
"""

import sys
import ctypes
import subprocess
from pathlib import Path
from utils.core.logging import get_logger

log = get_logger()


def is_admin():
    """Check if the current process has administrator privileges"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except (OSError, AttributeError) as e:
        log.debug(f"Failed to check admin status: {e}")
        return False


def request_admin_elevation():
    """
    Request administrator privileges by re-launching the application with elevation.
    This will show the UAC prompt.
    
    Returns:
        bool: True if elevation was attempted (process will exit), False if already admin
    """
    if is_admin():
        return False
    
    # Get the path to the current executable or script
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        exe_path = sys.executable
    else:
        # Running as Python script
        exe_path = sys.executable
        script_path = Path(sys.argv[0]).resolve()
    
    # Build the command line arguments
    params = ' '.join([f'"{arg}"' if ' ' in arg else arg for arg in sys.argv[1:]])
    
    try:
        # Request elevation via ShellExecute with 'runas' verb
        if getattr(sys, 'frozen', False):
            # For compiled executable
            ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                exe_path,
                params,
                None,
                1  # SW_SHOWNORMAL
            )
        else:
            # For Python script
            ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                exe_path,
                f'"{script_path}" {params}',
                None,
                1  # SW_SHOWNORMAL
            )
        
        # Exit the current non-elevated process
        sys.exit(0)
    except Exception as e:
        log.error(f"Failed to request elevation: {e}")
        return False
    
    return True


def is_registered_for_autostart():
    """
    Check if the application is registered in Task Scheduler for auto-start
    
    Returns:
        bool: True if registered, False otherwise
    """
    try:
        result = subprocess.run(
            ['schtasks', '/Query', '/TN', 'Rose'],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, OSError) as e:
        log.debug(f"Failed to check autostart registration: {e}")
        return False


def register_autostart():
    """
    Register the application in Windows Task Scheduler to auto-start at logon with admin rights.
    This avoids UAC prompts on every startup.
    
    Returns:
        tuple: (success: bool, message: str)
    """
    if not is_admin():
        return False, "Administrator privileges required to register auto-start"
    
    # Get the path to the executable
    if getattr(sys, 'frozen', False):
        exe_path = sys.executable
    else:
        exe_path = Path(sys.argv[0]).resolve()
    
    exe_dir = Path(exe_path).parent
    
    # Check if already registered
    if is_registered_for_autostart():
        return True, "Already registered for auto-start"
    
    try:
        # Create a scheduled task that runs at logon with highest privileges
        cmd = [
            'schtasks',
            '/Create',
            '/TN', 'Rose',  # Task name
            '/TR', f'"{exe_path}"',  # Task to run
            '/SC', 'ONLOGON',  # Trigger: On user logon
            '/RL', 'HIGHEST',  # Run with highest privileges (admin)
            '/F'  # Force create (overwrite if exists)
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        
        if result.returncode == 0:
            return True, "Successfully registered for auto-start with admin rights"
        else:
            return False, f"Failed to register: {result.stderr}"
    
    except Exception as e:
        return False, f"Failed to register auto-start: {e}"


def unregister_autostart():
    """
    Remove the application from Windows Task Scheduler auto-start.
    
    Returns:
        tuple: (success: bool, message: str)
    """
    if not is_admin():
        return False, "Administrator privileges required to unregister auto-start"
    
    # Check if registered
    if not is_registered_for_autostart():
        return True, "Not registered for auto-start"
    
    try:
        # Delete the scheduled task
        cmd = [
            'schtasks',
            '/Delete',
            '/TN', 'Rose',  # Task name
            '/F'  # Force delete without confirmation
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        
        if result.returncode == 0:
            return True, "Successfully unregistered from auto-start"
        else:
            return False, f"Failed to unregister: {result.stderr}"
    
    except Exception as e:
        return False, f"Failed to unregister auto-start: {e}"


def show_message_box_threaded(message: str, title: str, flags: int = 0x40):
    """
    Show a Windows MessageBox in a separate thread to ensure responsiveness.
    
    Args:
        message: The message text to display
        title: The title of the message box
        flags: MessageBox flags (default: MB_ICONINFORMATION)
    """
    import threading
    
    def show_dialog():
        """Show the dialog in a separate thread with proper message handling"""
        try:
            # Always add MB_SETFOREGROUND | MB_TOPMOST | MB_TASKMODAL for proper focus
            final_flags = flags | 0x10000 | 0x40000 | 0x2000
            ctypes.windll.user32.MessageBoxW(
                None,  # Use None for hwndOwner to create a top-level window
                message,
                title,
                final_flags
            )
        except Exception as e:
            log.error(f"Error showing message box '{title}': {e}")
    
    # Run the dialog in a separate daemon thread to avoid blocking
    dialog_thread = threading.Thread(target=show_dialog, daemon=True)
    dialog_thread.start()


def show_admin_required_dialog():
    """Show a dialog box explaining that admin rights are required"""
    show_message_box_threaded(
        "Rose requires Administrator privileges to function properly.\n\n"
        "The application will now request elevation.\n\n"
        "Click 'Yes' on the UAC prompt to continue.",
        "Administrator Rights Required",
        0x30  # MB_ICONWARNING
    )


def show_autostart_success_dialog():
    """Show a dialog box confirming auto-start registration"""
    show_message_box_threaded(
        "Rose will now start automatically when turn on your computer.",
        "Auto-Start Enabled",
        0x40  # MB_ICONINFORMATION
    )


def show_autostart_removed_dialog():
    """Show a dialog box confirming auto-start removal"""
    show_message_box_threaded(
        "Rose has been removed from auto-start.\n\n"
        "The application will no longer start automatically with Windows.\n\n"
        "You can re-enable auto-start from the settings menu.",
        "Auto-Start Removed",
        0x40  # MB_ICONINFORMATION
    )


def ensure_admin_rights():
    """
    Ensure the application is running with admin rights.
    If not, request elevation and exit.
    
    This should be called at the very start of the application.
    """
    if not is_admin():
        show_admin_required_dialog()
        request_admin_elevation()
        # If we reach here, elevation failed or was cancelled
        sys.exit(1)
