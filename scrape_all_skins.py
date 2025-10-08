#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script to scrape all skins from League of Legends using the LCU API
"""

import os
import json
import sys
import time
import requests
from typing import Optional, Dict, List, Any
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def find_lockfile() -> Optional[str]:
    """Find League Client lockfile"""
    # Check common locations
    if os.name == "nt":
        possible_paths = [
            r"C:\Riot Games\League of Legends\lockfile",
            r"C:\Program Files\Riot Games\League of Legends\lockfile",
            r"C:\Program Files (x86)\Riot Games\League of Legends\lockfile"
        ]
    else:
        possible_paths = [
            "/Applications/League of Legends.app/Contents/LoL/lockfile",
            os.path.expanduser("~/.local/share/League of Legends/lockfile")
        ]
    
    for path in possible_paths:
        if os.path.isfile(path):
            return path
    
    # Try to find via running process
    try:
        import psutil
        for proc in psutil.process_iter(attrs=["name", "exe"]):
            nm = (proc.info.get("name") or "").lower()
            if "leagueclient" in nm:
                exe = proc.info.get("exe") or ""
                for d in (os.path.dirname(exe), os.path.dirname(os.path.dirname(exe))):
                    p = os.path.join(d, "lockfile")
                    if os.path.isfile(p):
                        return p
    except Exception:
        pass
    
    return None


class LCUClient:
    """Simple LCU API client"""
    
    def __init__(self):
        self.base_url = None
        self.session = requests.Session()
        self.session.verify = False
        self._connect()
    
    def _connect(self):
        """Connect to LCU"""
        lockfile_path = find_lockfile()
        if not lockfile_path:
            raise Exception("League Client lockfile not found. Please make sure League Client is running.")
        
        with open(lockfile_path, 'r', encoding='utf-8') as f:
            data = f.read().split(':')
            name, pid, port, password, protocol = data[:5]
        
        self.base_url = f"https://127.0.0.1:{port}"
        self.session.auth = ('riot', password)
        self.session.headers.update({"Content-Type": "application/json"})
        
        print(f"✓ Connected to LCU on port {port}")
    
    def get(self, endpoint: str, timeout: float = 10.0, silent: bool = False) -> Optional[Any]:
        """Make GET request to LCU API"""
        try:
            url = self.base_url + endpoint
            response = self.session.get(url, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            if not silent:
                print(f"Error on GET {endpoint}: {e}")
            return None
    
    def get_all_champions(self) -> Optional[List[Dict]]:
        """Get all champions from game data"""
        print("Fetching all champions...")
        
        # Try multiple endpoints
        endpoints = [
            "/lol-champions/v1/owned-champions-minimal",
            "/lol-game-data/assets/v1/champion-summary.json",
            "/lol-champions/v1/inventories/scouting/champions"
        ]
        
        for endpoint in endpoints:
            print(f"  Trying {endpoint}...", end=' ')
            data = self.get(endpoint)
            if data:
                if isinstance(data, list) and len(data) > 0:
                    print("✓")
                    return data
                elif isinstance(data, dict):
                    # If it's a dict, try to extract champion list
                    if 'champions' in data:
                        print("✓")
                        return data['champions']
                    # Or convert dict values to list
                    champs = [v for k, v in data.items() if isinstance(v, dict) and 'id' in v]
                    if champs:
                        print("✓")
                        return champs
            print("✗")
        
        return None
    
    def get_champion_skins(self, champion_id: int) -> Optional[Dict]:
        """Get all skins for a specific champion"""
        # Try multiple endpoints (silently, we have fallbacks)
        endpoints = [
            f"/lol-champions/v1/inventories/scouting/champions/{champion_id}",
            f"/lol-game-data/assets/v1/champions/{champion_id}.json",
            f"/lol-champions/v1/inventories/{champion_id}/skins"
        ]
        
        for endpoint in endpoints:
            skin_data = self.get(endpoint, silent=True)
            if skin_data and isinstance(skin_data, dict):
                if 'skins' in skin_data:
                    return skin_data
        
        return None
    
    def get_all_skins_catalog(self) -> Optional[Any]:
        """Try to get all skins in one request"""
        endpoints = [
            "/lol-catalog/v1/items/CHAMPION_SKIN",
            "/lol-store/v1/catalog",
            "/lol-store/v1/skins"
        ]
        
        for endpoint in endpoints:
            data = self.get(endpoint)
            if data:
                return data
        
        return None
    
    def get_current_summoner(self) -> Optional[Dict]:
        """Get current summoner info"""
        return self.get("/lol-summoner/v1/current-summoner")


def scrape_all_skins():
    """Main function to scrape all skins"""
    start_time = time.time()
    
    print("=" * 60)
    print("League of Legends - All Skins Scraper")
    print("=" * 60)
    print()
    
    # Connect to LCU
    try:
        client = LCUClient()
    except Exception as e:
        print(f"❌ Failed to connect to LCU: {e}")
        return
    
    # Get summoner info
    summoner = client.get_current_summoner()
    if summoner:
        print(f"✓ Logged in as: {summoner.get('displayName', 'Unknown')}")
    print()
    
    # Get all champions
    champions = client.get_all_champions()
    if not champions:
        print("❌ Failed to fetch champions")
        return
    
    print(f"✓ Found {len(champions)} champions")
    print()
    
    # Collect all skins data
    all_skins_data = []
    champions_data = []
    
    # Function to scrape a single champion
    def scrape_champion(champ_info):
        champ_id = champ_info.get('id')
        champ_name = champ_info.get('name', 'Unknown')
        
        # Skip invalid entries
        if not champ_id or champ_id == -1:
            return None
        
        # Get detailed champion info with skins
        champ_details = client.get_champion_skins(champ_id)
        
        skins = None
        if champ_details:
            # Handle different response formats
            if 'skins' in champ_details:
                skins = champ_details['skins']
            elif isinstance(champ_details, dict):
                # Check if it's directly a champion object with skins array
                if 'id' in champ_details and isinstance(champ_details.get('skins'), list):
                    skins = champ_details['skins']
        
        if not skins:
            return None
        
        # Prepare champion data
        champ_data = {
            'championId': champ_id,
            'championName': champ_name,
            'alias': champ_info.get('alias', ''),
            'squarePortraitPath': champ_info.get('squarePortraitPath', ''),
            'skinCount': len(skins)
        }
        
        # Prepare skins data
        skins_data = []
        for skin in skins:
            skin_data = {
                'skinId': skin.get('id'),
                'championId': champ_id,
                'championName': champ_name,
                'skinName': skin.get('name', ''),
                'splashPath': skin.get('splashPath', ''),
                'tilePath': skin.get('tilePath', ''),
                'loadScreenPath': skin.get('loadScreenPath', ''),
                'chromas': len(skin.get('chromas', [])),
                'chromaPath': skin.get('chromaPath', ''),
                'ownership': skin.get('ownership', {})
            }
            skins_data.append(skin_data)
        
        return {
            'champion': champ_data,
            'skins': skins_data,
            'name': champ_name,
            'count': len(skins)
        }
    
    print("Scraping skins for each champion (parallel)...")
    print("-" * 60)
    
    # Use ThreadPoolExecutor to scrape champions in parallel
    completed = 0
    with ThreadPoolExecutor(max_workers=20) as executor:
        # Submit all tasks
        future_to_champ = {executor.submit(scrape_champion, champ): champ for champ in champions}
        
        # Process results as they complete
        for future in as_completed(future_to_champ):
            completed += 1
            result = future.result()
            
            if result:
                champions_data.append(result['champion'])
                all_skins_data.extend(result['skins'])
                print(f"[{completed}/{len(champions)}] {result['name']} - ✓ {result['count']} skins")
            else:
                print(f"[{completed}/{len(champions)}] ⚠ Failed")
    
    print()
    print("-" * 60)
    print(f"✓ Total skins scraped: {len(all_skins_data)}")
    print()
    
    # Sort by skinId
    all_skins_data.sort(key=lambda x: x['skinId'])
    
    # Create output directory
    output_dir = "skin_database"
    os.makedirs(output_dir, exist_ok=True)
    
    # Create CSV file only
    csv_file = os.path.join(output_dir, "skins_database.csv")
    with open(csv_file, 'w', encoding='utf-8', newline='') as f:
        f.write("skinId,championId,championName,skinName,chromas\n")
        for skin in all_skins_data:
            f.write(f"{skin['skinId']},{skin['championId']},\"{skin['championName']}\",\"{skin['skinName']}\",{skin['chromas']}\n")
    print(f"✓ Saved CSV database to: {csv_file}")
    
    print()
    print("=" * 60)
    print("✓ Scraping completed successfully!")
    print(f"  Champions: {len(champions_data)}")
    print(f"  Total skins: {len(all_skins_data)}")
    print(f"  Output file: {csv_file}")
    
    # Calculate and display elapsed time
    elapsed_time = time.time() - start_time
    minutes = int(elapsed_time // 60)
    seconds = elapsed_time % 60
    
    if minutes > 0:
        print(f"  Time taken: {minutes}m {seconds:.2f}s")
    else:
        print(f"  Time taken: {seconds:.2f}s")
    
    print("=" * 60)


if __name__ == "__main__":
    try:
        scrape_all_skins()
    except KeyboardInterrupt:
        print("\n\n⚠ Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

