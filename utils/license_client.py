"""
License Client - Example code for LeagueUnlocked app
Integrate this into your application to handle license validation
"""

import requests
import json
import os
from datetime import datetime
from pathlib import Path
import platform
import uuid
import hashlib
import base64
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidSignature

class LicenseClient:
    def __init__(self, server_url: str, license_file: str = "license.dat", public_key_pem: str = None):
        """
        Initialize the license client
        
        Args:
            server_url: URL of your license server (e.g., "https://yourserver.com")
            license_file: Path to store license data locally
            public_key_pem: RSA public key in PEM format for verifying signatures.
                           This should be embedded in your app. Safe to distribute!
        """
        self.server_url = server_url.rstrip('/')
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
        # Combine system info to create a unique ID
        machine_info = f"{platform.node()}-{platform.machine()}-{uuid.getnode()}"
        # Hash it to make it consistent and not expose system details
        return hashlib.sha256(machine_info.encode()).hexdigest()[:32]
    
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
        if not os.path.exists(self.license_file):
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
        if not os.path.exists(self.license_file):
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
        except:
            return None


# Example usage in your LeagueUnlocked app
if __name__ == "__main__":
    # Public key for signature verification
    # Get this by running: python admin/generate_rsa_keys.py
    # This key is SAFE to embed in your application
    PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
REPLACE_WITH_YOUR_PUBLIC_KEY
-----END PUBLIC KEY-----"""
    
    # Initialize the client with your server URL
    client = LicenseClient(
        server_url="http://localhost:8000",  # Change to your actual server URL
        license_file="license.dat",
        public_key_pem=PUBLIC_KEY  # Public key for verification - safe to distribute!
    )
    
    print("=== License System Demo ===\n")
    
    # Example 1: Check existing license
    valid, message = client.is_license_valid(check_online=False)
    print(f"Current license status: {message}")
    
    if valid:
        info = client.get_license_info()
        print(f"Days remaining: {info['days_remaining']}")
        print(f"Expires at: {info['expires_at']}")
    else:
        # Example 2: Activate a new license
        print("\nNo valid license found. Please enter your license key:")
        license_key = input("License key: ").strip()
        
        if license_key:
            success, msg = client.activate_license(license_key)
            print(f"\nActivation result: {msg}")
            
            if success:
                info = client.get_license_info()
                print(f"License activated! Valid for {info['days_remaining']} days.")

