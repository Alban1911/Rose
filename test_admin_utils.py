#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script for admin utils functionality
Run this to verify admin rights and auto-start features
"""

from utils.admin_utils import (
    is_admin,
    is_registered_for_autostart,
    register_autostart,
    unregister_autostart
)


def print_separator():
    print("\n" + "=" * 70 + "\n")


def test_admin_check():
    """Test admin rights check"""
    print("Testing Admin Rights Check...")
    print("-" * 70)
    
    if is_admin():
        print("✅ Running with Administrator privileges")
    else:
        print("❌ NOT running with Administrator privileges")
        print("\n⚠️ This script must be run as Administrator to test auto-start features")
        print("   Right-click this script and select 'Run as Administrator'")
    
    return is_admin()


def test_autostart_status():
    """Test auto-start registration status"""
    print("\nTesting Auto-Start Status...")
    print("-" * 70)
    
    if is_registered_for_autostart():
        print("✅ SkinCloner IS registered for auto-start")
        print("   Task Name: SkinCloner")
        print("   Location: Task Scheduler Library")
    else:
        print("❌ SkinCloner is NOT registered for auto-start")
        print("   You can enable it via the system tray menu")


def test_register_autostart():
    """Test registering auto-start"""
    if not is_admin():
        print("\n⚠️ Skipping auto-start registration test (requires admin)")
        return
    
    print("\nTesting Auto-Start Registration...")
    print("-" * 70)
    
    # Check if already registered
    if is_registered_for_autostart():
        print("ℹ️ Auto-start already registered, skipping registration test")
        return
    
    print("Attempting to register auto-start...")
    success, message = register_autostart()
    
    if success:
        print(f"✅ {message}")
    else:
        print(f"❌ {message}")


def test_unregister_autostart():
    """Test unregistering auto-start"""
    if not is_admin():
        print("\n⚠️ Skipping auto-start unregistration test (requires admin)")
        return
    
    print("\nTesting Auto-Start Unregistration...")
    print("-" * 70)
    
    # Check if registered
    if not is_registered_for_autostart():
        print("ℹ️ Auto-start not registered, skipping unregistration test")
        return
    
    print("Attempting to unregister auto-start...")
    success, message = unregister_autostart()
    
    if success:
        print(f"✅ {message}")
    else:
        print(f"❌ {message}")


def interactive_menu():
    """Interactive menu for testing"""
    while True:
        print_separator()
        print("SkinCloner - Admin Utils Test Menu")
        print("-" * 70)
        print("1. Check Admin Rights")
        print("2. Check Auto-Start Status")
        print("3. Register Auto-Start")
        print("4. Unregister Auto-Start")
        print("5. Run All Tests")
        print("6. Exit")
        print("-" * 70)
        
        try:
            choice = input("\nEnter your choice (1-6): ").strip()
            
            if choice == "1":
                print_separator()
                test_admin_check()
            elif choice == "2":
                print_separator()
                test_autostart_status()
            elif choice == "3":
                print_separator()
                test_register_autostart()
                test_autostart_status()  # Show updated status
            elif choice == "4":
                print_separator()
                test_unregister_autostart()
                test_autostart_status()  # Show updated status
            elif choice == "5":
                print_separator()
                is_admin_result = test_admin_check()
                test_autostart_status()
                if is_admin_result:
                    # Only test registration/unregistration if admin
                    print("\n\n")
                    print("=" * 70)
                    print("INTERACTIVE TESTS (requires user confirmation)")
                    print("=" * 70)
                    
                    if is_registered_for_autostart():
                        resp = input("\nWould you like to test UNREGISTER auto-start? (y/n): ").lower()
                        if resp == 'y':
                            test_unregister_autostart()
                            test_autostart_status()
                    else:
                        resp = input("\nWould you like to test REGISTER auto-start? (y/n): ").lower()
                        if resp == 'y':
                            test_register_autostart()
                            test_autostart_status()
            elif choice == "6":
                print("\n👋 Goodbye!")
                break
            else:
                print("\n❌ Invalid choice. Please enter 1-6.")
        
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")


def main():
    """Main entry point"""
    print_separator()
    print("SkinCloner - Admin Utils Test Suite")
    print_separator()
    
    print("This script tests the admin rights and auto-start functionality.")
    print()
    print("Features tested:")
    print("  ✓ Admin rights detection")
    print("  ✓ Auto-start registration status")
    print("  ✓ Task Scheduler integration")
    print()
    print("Note: Auto-start registration/unregistration requires admin rights.")
    
    # Run interactive menu
    interactive_menu()


if __name__ == "__main__":
    main()

