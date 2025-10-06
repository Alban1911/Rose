#!/usr/bin/env python3
"""
Test script for the pre-builder system
"""

import time
from pathlib import Path
from injection.prebuilder import ChampionPreBuilder
from utils.logging import setup_logging, get_logger

# Setup logging
setup_logging(verbose=True)
log = get_logger()

def test_prebuilder():
    """Test the pre-builder system"""
    print("=" * 60)
    print("TESTING PRE-BUILDER SYSTEM")
    print("=" * 60)
    
    # Initialize pre-builder
    prebuilder = ChampionPreBuilder()
    
    # Test champion (use a champion with few skins for faster testing)
    test_champion = "Akshan"  # Should have 3 skins
    
    print(f"\nTesting pre-build for {test_champion}...")
    
    # Test thread recommendation
    recommended_threads = prebuilder.get_recommended_threads(test_champion)
    print(f"Recommended threads for {test_champion}: {recommended_threads}")
    
    # Test finding skins
    skins = prebuilder.find_champion_skins(test_champion)
    print(f"Found {len(skins)} skins for {test_champion}:")
    for skin_name, skin_path in skins:
        print(f"  - {skin_name}: {skin_path.name}")
    
    if not skins:
        print("No skins found, trying with different champion...")
        test_champion = "Anivia"  # Fallback
        skins = prebuilder.find_champion_skins(test_champion)
        print(f"Found {len(skins)} skins for {test_champion}:")
        for skin_name, skin_path in skins:
            print(f"  - {skin_name}: {skin_path.name}")
    
    if skins:
        print(f"\nStarting pre-build for {test_champion}...")
        start_time = time.time()
        
        success = prebuilder.prebuild_champion_skins(test_champion)
        
        total_time = time.time() - start_time
        print(f"Pre-build completed in {total_time:.2f}s")
        
        if success:
            print("SUCCESS: Pre-build successful!")
            
            # Test getting pre-built overlay path
            first_skin = skins[0][0]
            overlay_path = prebuilder.get_prebuilt_overlay_path(test_champion, first_skin)
            if overlay_path and overlay_path.exists():
                print(f"SUCCESS: Pre-built overlay found: {overlay_path}")
            else:
                print(f"FAIL: Pre-built overlay not found for {first_skin}")
            
            # Test cleanup
            print(f"\nCleaning up unused overlays (keeping {first_skin})...")
            prebuilder.cleanup_unused_overlays(test_champion, first_skin)
            print("SUCCESS: Cleanup completed")
            
        else:
            print("FAIL: Pre-build failed!")
    
    print(f"\nCleaning up all overlays...")
    prebuilder.cleanup_all_overlays()
    print("SUCCESS: All overlays cleaned up")
    
    print("\n" + "=" * 60)
    print("PRE-BUILDER TEST COMPLETED")
    print("=" * 60)

if __name__ == "__main__":
    test_prebuilder()
