#!/usr/bin/env python3
"""
Test script to verify injection manager initialization and pre-building trigger
"""

from injection.manager import InjectionManager
from utils.logging import setup_logging, get_logger

# Setup logging
setup_logging(verbose=True)
log = get_logger()

def test_injection_manager():
    """Test the injection manager initialization and pre-building"""
    print("=" * 60)
    print("TESTING INJECTION MANAGER")
    print("=" * 60)
    
    # Initialize injection manager
    print("Initializing InjectionManager...")
    injection_manager = InjectionManager()
    
    print(f"Injection manager initialized: {injection_manager is not None}")
    print(f"Pre-builder initialized: {injection_manager.prebuilder is not None}")
    print(f"Current champion: {injection_manager.current_champion}")
    
    # Test pre-building trigger
    print("\nTesting pre-building trigger...")
    test_champion = "Anivia"
    
    try:
        print(f"Calling on_champion_locked('{test_champion}')...")
        injection_manager.on_champion_locked(test_champion)
        print(f"Current champion after trigger: {injection_manager.current_champion}")
        print("SUCCESS: Pre-building trigger called without error")
    except Exception as e:
        print(f"ERROR: Pre-building trigger failed: {e}")
    
    print("\n" + "=" * 60)
    print("INJECTION MANAGER TEST COMPLETED")
    print("=" * 60)

if __name__ == "__main__":
    test_injection_manager()
