#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script to count chromas across all skins and find the maximum
Scans all README.md files in the skins folder to find which skin has the most chromas
"""

import re
from pathlib import Path
from utils.paths import get_skins_dir


def count_chromas_in_readme(readme_path: Path):
    """Count the number of chromas in a README file"""
    try:
        content = readme_path.read_text(encoding='utf-8')
        
        # Pattern to match chroma entries: ![chromaId](url)
        pattern = r'!\[(\d+)\]\(https?://[^\)]+\)'
        matches = re.findall(pattern, content, re.IGNORECASE)
        
        return len(matches), [int(m) for m in matches]
    except Exception as e:
        print(f"   Error reading {readme_path}: {e}")
        return 0, []


def main():
    """Scan all skins and find maximum chroma count"""
    print("=" * 80)
    print("🎨 Maximum Chroma Count Finder")
    print("=" * 80)
    print()
    
    skins_dir = get_skins_dir()
    
    if not skins_dir.exists():
        print(f"❌ Skins directory not found: {skins_dir}")
        print("   Run: python main.py --download-skins")
        return
    
    print(f"📁 Scanning: {skins_dir}")
    print()
    
    # Scan all champions
    all_skins = []
    total_chromas = 0
    
    for champion_dir in sorted(skins_dir.iterdir()):
        if not champion_dir.is_dir():
            continue
        
        chromas_dir = champion_dir / "chromas"
        if not chromas_dir.exists():
            continue
        
        champion_name = champion_dir.name
        champion_total = 0
        
        # Scan all skin folders in this champion
        for skin_dir in sorted(chromas_dir.iterdir()):
            if not skin_dir.is_dir():
                continue
            
            readme_path = skin_dir / "README.md"
            if not readme_path.exists():
                continue
            
            skin_name = skin_dir.name
            count, chroma_ids = count_chromas_in_readme(readme_path)
            
            if count > 0:
                all_skins.append({
                    'champion': champion_name,
                    'skin': skin_name,
                    'count': count,
                    'ids': chroma_ids,
                    'path': readme_path
                })
                champion_total += count
                total_chromas += count
        
        if champion_total > 0:
            print(f"✓ {champion_name}: {champion_total} chromas")
    
    print()
    print("=" * 80)
    print(f"📊 STATISTICS")
    print("=" * 80)
    print()
    
    if not all_skins:
        print("❌ No chromas found!")
        print("   Make sure skins are downloaded with chromas folder")
        return
    
    # Sort by chroma count
    all_skins.sort(key=lambda x: x['count'], reverse=True)
    
    # Show total stats
    print(f"Total champions scanned: {len(set(s['champion'] for s in all_skins))}")
    print(f"Total skins with chromas: {len(all_skins)}")
    print(f"Total chromas across all skins: {total_chromas}")
    print()
    
    # Show top 10 skins with most chromas
    print("🏆 TOP 10 SKINS WITH MOST CHROMAS:")
    print("-" * 80)
    print(f"{'Rank':<6} {'Count':<8} {'Champion':<25} {'Skin'}")
    print("-" * 80)
    
    for i, skin_info in enumerate(all_skins[:10], 1):
        champion = skin_info['champion']
        skin = skin_info['skin']
        count = skin_info['count']
        
        # Truncate long names
        if len(champion) > 24:
            champion = champion[:21] + "..."
        if len(skin) > 30:
            skin = skin[:27] + "..."
        
        print(f"#{i:<5} {count:<8} {champion:<25} {skin}")
    
    print("-" * 80)
    print()
    
    # Show the maximum
    max_skin = all_skins[0]
    print("🎯 MAXIMUM CHROMAS ON A SINGLE SKIN:")
    print(f"   Champion: {max_skin['champion']}")
    print(f"   Skin: {max_skin['skin']}")
    print(f"   Chroma Count: {max_skin['count']}")
    print(f"   Chroma IDs: {max_skin['ids'][:5]}{'...' if len(max_skin['ids']) > 5 else ''}")
    print(f"   Path: {max_skin['path'].parent.name}")
    print()
    
    # Show distribution
    print("📈 CHROMA COUNT DISTRIBUTION:")
    from collections import Counter
    distribution = Counter(s['count'] for s in all_skins)
    for count in sorted(distribution.keys(), reverse=True)[:15]:
        bar = "█" * min(distribution[count], 50)
        print(f"   {count:2} chromas: {bar} ({distribution[count]} skins)")
    
    print()
    print("=" * 80)
    print(f"✅ Maximum chroma count: {max_skin['count']}")
    print("=" * 80)
    
    return max_skin['count']


if __name__ == "__main__":
    try:
        max_count = main()
    except KeyboardInterrupt:
        print("\n\n✓ Cancelled by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

