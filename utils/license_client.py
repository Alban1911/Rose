"""
License Client - Example code for LeagueUnlocked app
Integrate this into your application to handle license validation
"""

# Standard library imports
import base64
import hashlib
import json
import os
import platform
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

# Third-party imports
import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

class LicenseClient:
    def __init__(self, server_url: str, license_file: str = "license.dat", public_key_pem: str = None):
        """
        Initialize the license client
        
        Args:
            server_url: URL of your license server (e.g., "https://api.leagueunlocked.net")
            license_file: Path to store license data locally
            public_key_pem: RSA public key in PEM format for verifying signatures.
                           This should be embedded in your app. Safe to distribute!
        """
        self.server_url = server_url.rstrip('/')

        # Resolve license file path to be anchored to the executable directory when frozen.
        # This ensures the same location regardless of the current working directory.
        try:
            if getattr(sys, "frozen", False):
                base_dir = Path(sys.executable).resolve().parent
            else:
                # When running from source, anchor to project root (file two levels up)
                base_dir = Path(__file__).resolve().parent.parent

            lic_path = Path(license_file)
            if not lic_path.is_absolute():
                lic_path = base_dir / lic_path
            self.license_file = str(lic_path)
        except Exception:
            # Fallback to original behavior if path resolution fails for any reason
            self.license_file = license_file
        
        # Load public key for signature verification
        if public_key_pem:
            try:
                self.public_key = serialization.load_pem_public_key(
                    public_key_pem.encode('utf-8'),
                    backend=default_backend()
                )
            except Exception as e:
                print(f"Warning: Could not load public key: {e}")
                self.public_key = None
        else:
            print("Warning: No public key provided - signature verification disabled")
            self.public_key = None
    
    def get_machine_id(self) -> str:
        """
        Generate a unique machine identifier
        This helps prevent the same key from being used on multiple machines
        """
        # Prefer a stable OS-guided identifier on Windows
        if sys.platform == "win32":
            machine_guid = self._get_windows_machine_guid()
            if machine_guid:
                return hashlib.sha256(machine_guid.encode("utf-8")).hexdigest()[:32]

        # Cross-platform fallback: use a combination that is relatively stable
        # Avoid hostname alone (can change). Include MAC and architecture.
        mac_address = uuid.getnode()
        arch = platform.machine() or ""
        system = platform.system() or ""
        canonical = f"{system}|{arch}|{mac_address}"
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]

    def _get_windows_machine_guid(self) -> Optional[str]:
        """
        Retrieve the Windows MachineGuid from the registry, which is stable for the OS install.
        Returns None if unavailable.
        """
        try:
            import winreg  # type: ignore
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
                value, _ = winreg.QueryValueEx(key, "MachineGuid")
                # Normalize formatting
                if isinstance(value, str):
                    return value.strip().lower()
                return None
        except Exception:
            return None
    
    def _verify_license_signature(self, license_data: dict) -> bool:
        """
        Verify RSA signature to ensure license data hasn't been tampered with
        
        Args:
            license_data: License data dictionary with 'signature' field
            
        Returns:
            True if signature is valid, False otherwise
        """
        if 'signature' not in license_data:
            return False
        
        if self.public_key is None:
            print("Warning: Cannot verify signature - no public key loaded")
            return False
        
        try:
            # Create canonical string from license data
            canonical_string = f"{license_data['key']}|{license_data['machine_id']}|{license_data['activated_at']}|{license_data['expires_at']}"
            
            # Decode signature from base64
            signature_bytes = base64.b64decode(license_data['signature'])
            
            # Verify signature using public key
            self.public_key.verify(
                signature_bytes,
                canonical_string.encode('utf-8'),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            
            return True
            
        except InvalidSignature:
            return False
        except Exception as e:
            print(f"Error verifying signature: {e}")
            return False
    
    def activate_license(self, license_key: str) -> tuple[bool, str]:
        """
        Activate a license key with the server
        
        Args:
            license_key: The license key entered by the user
            
        Returns:
            (success: bool, message: str)
        """
        try:
            machine_id = self.get_machine_id()
            
            response = requests.post(
                f"{self.server_url}/activate",
                json={
                    "key": license_key,
                    "machine_id": machine_id
                },
                timeout=10
            )
            
            data = response.json()
            
            if data.get("success"):
                # Save license info locally with signature from server
                license_data = {
                    "key": license_key,
                    "machine_id": machine_id,
                    "activated_at": data["activated_at"],
                    "expires_at": data["expires_at"],
                    "signature": data.get("signature", "")  # Server-provided signature
                }
                
                # Verify the signature before saving
                if license_data["signature"] and not self._verify_license_signature(license_data):
                    return False, "Server provided invalid signature - possible security issue"
                
                with open(self.license_file, 'w') as f:
                    json.dump(license_data, f)
                
                return True, data["message"]
            else:
                return False, data["message"]
                
        except requests.exceptions.RequestException as e:
            return False, f"Cannot connect to license server: {str(e)}"
        except Exception as e:
            return False, f"Error activating license: {str(e)}"
    
    def is_license_valid(self, check_online: bool = False) -> tuple[bool, str]:
        """
        Check if the current license is valid
        
        Args:
            check_online: If True, verify with server (slower but more secure)
                         If False, only check locally (faster)
        
        Returns:
            (valid: bool, message: str)
        """
        # Check if license file exists
        if not Path(self.license_file).exists():
            return False, "No license found. Please activate your license."
        
        try:
            with open(self.license_file, 'r') as f:
                license_data = json.load(f)
            
            # IMPORTANT: Verify signature first (prevents tampering)
            if not self._verify_license_signature(license_data):
                return False, "License file has been tampered with."
            
            # Check if machine_id matches (prevent copying license file)
            if license_data.get("machine_id") != self.get_machine_id():
                return False, "License is not valid for this machine."
            
            # Parse expiration date
            expires_at = datetime.fromisoformat(license_data["expires_at"].replace('Z', '+00:00'))
            now = datetime.utcnow()
            
            # Check expiration locally
            if now > expires_at:
                return False, "Your license has expired."
            
            days_remaining = (expires_at - now).days
            
            # Optional: Verify with server
            if check_online:
                try:
                    response = requests.post(
                        f"{self.server_url}/validate",
                        json={
                            "key": license_data["key"],
                            "machine_id": license_data["machine_id"]
                        },
                        timeout=5
                    )
                    
                    data = response.json()
                    
                    if not data.get("valid"):
                        return False, data.get("message", "License validation failed.")
                    
                except requests.exceptions.RequestException:
                    # If server is down, rely on local validation
                    pass
            
            return True, f"License valid. {days_remaining} days remaining."
            
        except Exception as e:
            return False, f"Error reading license: {str(e)}"
    
    def get_license_info(self) -> dict:
        """
        Get detailed license information
        
        Returns:
            Dictionary with license details or None if no license
        """
        if not Path(self.license_file).exists():
            return None
        
        try:
            with open(self.license_file, 'r') as f:
                license_data = json.load(f)
            
            expires_at = datetime.fromisoformat(license_data["expires_at"].replace('Z', '+00:00'))
            now = datetime.utcnow()
            days_remaining = max(0, (expires_at - now).days)
            
            return {
                "activated_at": license_data["activated_at"],
                "expires_at": license_data["expires_at"],
                "days_remaining": days_remaining,
                "is_expired": now > expires_at
            }
        except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError) as e:
            log.debug(f"Error reading license file: {e}")
            return None
        except Exception as e:
            log.debug(f"Unexpected error processing license: {e}")
            return None