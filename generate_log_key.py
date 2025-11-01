#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate a custom encryption key for log files
"""

import secrets
import string
from pathlib import Path


def generate_secure_password(length=64):
    """Generate a secure random password"""
    alphabet = string.ascii_letters + string.digits + string.punctuation
    password = ''.join(secrets.choice(alphabet) for _ in range(length))
    return password


def main():
    """Generate and save a log encryption key"""
    key_file = Path(__file__).parent / "log_encryption_key.txt"
    
    # Check if key file already exists
    if key_file.exists():
        print(f"Warning: Key file already exists at {key_file}")
        response = input("Do you want to overwrite it? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            print("Cancelled. No changes made.")
            return
    
    # Generate a secure random password
    password = generate_secure_password(64)
    
    # Save to file
    try:
        with open(key_file, 'w') as f:
            f.write(password)
        
        print("[SUCCESS] Generated encryption key successfully!")
        print(f"Key saved to: {key_file}")
        print(f"\nYour encryption key (keep this secure):")
        print(f"{password}")
        print(f"\nIMPORTANT:")
        print(f"   1. Keep this key safe and secure")
        print(f"   2. Add 'log_encryption_key.txt' to .gitignore")
        print(f"   3. Store a backup of this key separately")
        print(f"\nThe key file will be automatically used by:")
        print(f"   - LeagueUnlocked (for encrypting logs)")
        print(f"   - decrypt_log.py (for decrypting logs)")
        
    except Exception as e:
        print(f"Error saving key file: {e}")


if __name__ == "__main__":
    main()

