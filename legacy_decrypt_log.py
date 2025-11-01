#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Legacy decryptor for pre-RSA logs (Fernet password-derived encryption).
"""

import base64
import os
import sys
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def get_encryption_key():
    """Get the encryption key from key file, environment variable, or generate from a fixed password"""
    # Priority 1: Try to get key from key file (most secure)
    key_file = Path(__file__).parent / "log_encryption_key.txt"
    if key_file.exists():
        try:
            with open(key_file, 'r') as f:
                key_str = f.read().strip()
            if key_str:
                password = key_str.encode()
            else:
                # Empty file, fall through to default
                password = None
        except Exception:
            # Could not read key file, fall through to default
            password = None
    else:
        password = None
    
    # Priority 2: Try to get key from environment variable
    if password is None:
        key_str = os.environ.get('LEAGUE_UNLOCKED_LOG_KEY')
        if key_str:
            password = key_str.encode()
    
    # Priority 3: Default key derived from a fixed password (developer only)
    if password is None:
        password = b'LeagueUnlocked2024LogEncryptionDefaultKey'
    
    # Derive a 32-byte key using PBKDF2
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'league_unlocked_logs_salt',
        iterations=100000,
        backend=default_backend()
    )
    key = kdf.derive(password)
    
    # Fernet expects a URL-safe base64-encoded 32-byte key
    return base64.urlsafe_b64encode(key)


def decrypt_log_file(input_file: Path, output_file: Path):
    """Decrypt an encrypted log file"""
    try:
        # Get encryption key and create Fernet cipher
        key = get_encryption_key()
        cipher = Fernet(key)
        
        # Read encrypted content
        with open(input_file, 'rb') as f:
            encrypted_lines = f.readlines()
        
        # Decrypt each line
        decrypted_content = []
        for encrypted_line in encrypted_lines:
            # Remove newline from encrypted line
            encrypted_line = encrypted_line.strip()
            if encrypted_line:
                try:
                    decrypted_line = cipher.decrypt(encrypted_line)
                    decrypted_content.append(decrypted_line.decode('utf-8'))
                except Exception as e:
                    print(f"Warning: Could not decrypt line: {e}")
                    decrypted_content.append(f"[DECRYPTION_ERROR: {e}]")
        
        # Write decrypted content
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(decrypted_content))
        
        print(f"Successfully decrypted {input_file.name} to {output_file.name}")
        return True
        
    except Exception as e:
        print(f"Error decrypting log file: {e}")
        return False


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("Usage: python legacy_decrypt_log.py <encrypted_log_file> [output_file]")
        sys.exit(1)
    
    input_file = Path(sys.argv[1])
    
    if not input_file.exists():
        print(f"Error: File not found: {input_file}")
        sys.exit(1)
    
    # Generate output filename if not provided
    if len(sys.argv) >= 3:
        output_file = Path(sys.argv[2])
    else:
        # Remove .enc extension
        output_file = input_file.with_suffix('').with_suffix('.log')
    
    decrypt_log_file(input_file, output_file)


if __name__ == "__main__":
    main()


