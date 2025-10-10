#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script to download Garen's chroma preview images
Run this before test_show_button.py to ensure preview images are available
"""

import sys
from utils.chroma_preview_manager import ChromaPreviewManager
from utils.logging import setup_logging, get_logger

def main():
    """Download Garen's chroma previews"""
    print("=" * 70)
    print("🎨 Garen Chroma Preview Downloader")
    print("=" * 70)
    
    # Setup logging
    setup_logging(verbose=True)
    log = get_logger()
    
    # Create preview manager
    manager = ChromaPreviewManager()
    
    print()
    print("Champion: Garen")
    print("This will download preview images for all Garen chromas")
    print("Images will be cached in:", manager.cache_dir)
    print()
    
    # Check if already complete
    if manager.is_champion_complete("Garen"):
        print("✓ Garen previews already downloaded!")
        print()
        
        # Show cache directory info
        cache_files = list(manager.cache_dir.glob("*.png"))
        print(f"Found {len(cache_files)} preview images in cache")
        print()
        
        response = input("Download again anyway? (y/N): ").strip().lower()
        if response != 'y':
            print("Skipping download.")
            return
        
        # Clear the completion marker to force re-download
        manager.completed_champions.discard("Garen")
        print()
    
    print("Starting download...")
    print("-" * 70)
    
    # Download previews
    success = manager.download_champion_previews("Garen")
    
    print("-" * 70)
    print()
    
    if success:
        print("✅ SUCCESS! Garen chroma previews downloaded")
        
        # Show some stats
        cache_files = list(manager.cache_dir.glob("*.png"))
        print(f"📁 Total preview images in cache: {len(cache_files)}")
        print(f"📂 Cache location: {manager.cache_dir}")
        print()
        print("You can now run test_show_button.py to see the wheel with previews!")
    else:
        print("❌ FAILED to download Garen previews")
        print()
        print("Possible reasons:")
        print("  - Garen skins haven't been downloaded yet (run: python main.py --download-skins)")
        print("  - No chromas folder exists for Garen")
        print("  - Network issues")
        print()
        print("Try running the full app first to download skins:")
        print("  python main.py --download-skins")
    
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n✓ Cancelled by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)

