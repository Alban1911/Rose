#!/usr/bin/env python3
"""
Test script to verify the complete pre-building and injection flow
"""

import time
from injection.manager import InjectionManager
from utils.logging import setup_logging, get_logger

# Setup logging
setup_logging(verbose=True)
log = get_logger()

def test_complete_flow():
    """Test the complete pre-building and injection flow"""
    print("=" * 60)
    print("TESTING COMPLETE PRE-BUILDING AND INJECTION FLOW")
    print("=" * 60)
    
    # Initialize injection manager
    print("Initializing InjectionManager...")
    injection_manager = InjectionManager()
    
    # Test champion
    test_champion = "Akshan"
    test_skin = "Crystal Rose Akshan"
    
    print(f"\n1. Testing pre-building trigger for {test_champion}...")
    injection_manager.on_champion_locked(test_champion)
    
    # Wait a bit for pre-building to start
    time.sleep(1.0)
    
    print(f"\n2. Checking pre-build status...")
    in_progress = injection_manager.is_prebuild_in_progress(test_champion)
    print(f"Pre-build in progress: {in_progress}")
    
    # Wait for pre-building to complete
    print(f"\n3. Waiting for pre-building to complete...")
    if injection_manager.prebuilder.wait_for_prebuild_completion(test_champion, timeout=10.0):
        print("SUCCESS: Pre-building completed")
        
        # Test pre-built overlay availability
        print(f"\n4. Testing pre-built overlay availability...")
        overlay_path = injection_manager.prebuilder.get_prebuilt_overlay_path(test_champion, test_skin)
        if overlay_path and overlay_path.exists():
            print(f"SUCCESS: Pre-built overlay found: {overlay_path}")
            
            # Test pre-built injection
            print(f"\n5. Testing pre-built injection...")
            success = injection_manager.inject_prebuilt_skin(test_champion, test_skin)
            if success:
                print("SUCCESS: Pre-built injection successful")
            else:
                print("FAIL: Pre-built injection failed")
        else:
            print(f"FAIL: Pre-built overlay not found for {test_skin}")
    else:
        print("FAIL: Pre-building did not complete within timeout")
    
    print(f"\n6. Testing cleanup...")
    injection_manager.cleanup_prebuilt_overlays()
    print("SUCCESS: Cleanup completed")
    
    print("\n" + "=" * 60)
    print("COMPLETE FLOW TEST COMPLETED")
    print("=" * 60)

if __name__ == "__main__":
    test_complete_flow()
