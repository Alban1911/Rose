#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Decrypt RSA-hybrid encrypted log files from LeagueUnlocked.

Format written by the app in production mode:
  1st line: {"v":"rsa1","ek":"<b64_rsa_oaep_encrypted_fernet_key>"}
  next lines: Fernet tokens (base64 ASCII)

Private key source:
  - private_key.pem next to this script (repo root)

Use legacy_decrypt_log.py for legacy (pre-RSA) logs.
"""

import base64
import json
import sys
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


def _load_private_key_from_file(private_key_path: Path):
    with open(private_key_path, 'rb') as f:
        pem_data = f.read()
    try:
        return serialization.load_pem_private_key(pem_data, password=None, backend=default_backend())
    except TypeError:
        try:
            print("Enter private key passphrase:", end=" ", flush=True)
            passphrase = sys.stdin.readline().rstrip("\n").encode('utf-8')
            return serialization.load_pem_private_key(pem_data, password=passphrase, backend=default_backend())
        except Exception as e:
            raise RuntimeError(f"Failed to load password-protected private key: {e}")

def decrypt_log_file(input_file: Path, output_file: Path):
    """Decrypt an RSA-hybrid encrypted log file using the provided RSA private key."""
    with open(input_file, 'rb') as f:
        lines = [ln.rstrip(b"\n") for ln in f.readlines()]

    if not lines:
        raise RuntimeError("Log file is empty")

    # Parse header
    try:
        header_obj = json.loads(lines[0].decode('utf-8'))
    except Exception:
        raise RuntimeError(
            "Unrecognized log format: missing RSA header. Use legacy_decrypt_log.py for legacy logs."
        )

    if not isinstance(header_obj, dict) or header_obj.get("v") != "rsa1" or "ek" not in header_obj:
        raise RuntimeError(
            "Unsupported header format. Expected RSA-hybrid header with v='rsa1' and 'ek'."
        )

    # Load RSA private key from ./private_key.pem only
    default_key_path = Path(__file__).resolve().parent / "private_key.pem"
    if not default_key_path.exists():
        raise RuntimeError("private_key.pem not found next to decrypt_log.py")
    private_key = _load_private_key_from_file(default_key_path)

    # Decrypt Fernet key
    ek_bytes = base64.urlsafe_b64decode(header_obj["ek"].encode('ascii'))
    fernet_key = private_key.decrypt(
        ek_bytes,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    cipher = Fernet(fernet_key)

    # Decrypt remaining lines
    decrypted_lines: list[str] = []
    for token_line in lines[1:]:
        if not token_line:
            decrypted_lines.append("")
            continue
        try:
            if token_line.startswith(b"{"):
                obj = json.loads(token_line.decode('utf-8'))
                token_b64 = obj.get("ct", "")
                token_bytes = token_b64.encode('ascii')
            else:
                token_bytes = token_line
            plaintext = cipher.decrypt(token_bytes).decode('utf-8')
            decrypted_lines.append(plaintext)
        except Exception as e:
            decrypted_lines.append(f"[DECRYPTION_ERROR: {e}]")

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("\n".join(decrypted_lines))

    print(f"Successfully decrypted {input_file.name} to {output_file.name}")
    return True


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("Usage: python decrypt_log.py <encrypted_log_file> [output_file]")
        print("       Looks for ./private_key.pem automatically")
        sys.exit(1)
    
    input_file = Path(sys.argv[1])
    output_file: Path | None = None

    if not input_file.exists():
        print(f"Error: File not found: {input_file}")
        sys.exit(1)

    # Optional output path
    if len(sys.argv) >= 3:
        output_file = Path(sys.argv[2])

    if output_file is None:
        output_file = input_file.with_suffix('').with_suffix('.log')
    
    decrypt_log_file(input_file, output_file)


if __name__ == "__main__":
    main()


