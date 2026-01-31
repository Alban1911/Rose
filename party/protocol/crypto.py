#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Party Mode Cryptography
AES-256-GCM encryption for P2P messages
"""

import os
import struct
from typing import Tuple

from utils.core.logging import get_logger

log = get_logger()

# Try to use cryptography library, fall back to basic XOR if not available
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False
    log.warning("[CRYPTO] cryptography library not available, using basic encryption")


class PartyCrypto:
    """Handles encryption/decryption for P2P messages"""

    # Nonce size for AES-GCM (96 bits = 12 bytes recommended)
    NONCE_SIZE = 12
    # Key size (256 bits = 32 bytes)
    KEY_SIZE = 32
    # Tag size for AES-GCM
    TAG_SIZE = 16

    def __init__(self, key: bytes):
        """Initialize crypto with encryption key

        Args:
            key: 32-byte encryption key
        """
        if len(key) != self.KEY_SIZE:
            raise ValueError(f"Key must be {self.KEY_SIZE} bytes, got {len(key)}")

        self.key = key
        if HAS_CRYPTOGRAPHY:
            self._aesgcm = AESGCM(key)
        else:
            self._aesgcm = None

    @classmethod
    def generate_key(cls) -> bytes:
        """Generate a random encryption key

        Returns:
            32-byte random key
        """
        return os.urandom(cls.KEY_SIZE)

    def encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt data using AES-256-GCM

        Args:
            plaintext: Data to encrypt

        Returns:
            Encrypted data: nonce (12 bytes) + ciphertext + tag (16 bytes)
        """
        nonce = os.urandom(self.NONCE_SIZE)

        if self._aesgcm:
            # Use proper AES-GCM
            ciphertext = self._aesgcm.encrypt(nonce, plaintext, None)
            return nonce + ciphertext
        else:
            # Fallback: XOR cipher (not secure, but functional)
            ciphertext = self._xor_cipher(plaintext, nonce)
            # Add a simple checksum as "tag"
            checksum = self._simple_checksum(plaintext)
            return nonce + ciphertext + checksum

    def decrypt(self, data: bytes) -> bytes:
        """Decrypt data using AES-256-GCM

        Args:
            data: Encrypted data (nonce + ciphertext + tag)

        Returns:
            Decrypted plaintext

        Raises:
            ValueError: If decryption fails (invalid data or tampered)
        """
        if len(data) < self.NONCE_SIZE + self.TAG_SIZE:
            raise ValueError("Encrypted data too short")

        nonce = data[: self.NONCE_SIZE]
        ciphertext = data[self.NONCE_SIZE :]

        if self._aesgcm:
            try:
                return self._aesgcm.decrypt(nonce, ciphertext, None)
            except Exception as e:
                raise ValueError(f"Decryption failed: {e}")
        else:
            # Fallback: XOR cipher
            if len(ciphertext) < self.TAG_SIZE:
                raise ValueError("Ciphertext too short")
            actual_ciphertext = ciphertext[:-self.TAG_SIZE]
            stored_checksum = ciphertext[-self.TAG_SIZE:]
            plaintext = self._xor_cipher(actual_ciphertext, nonce)
            expected_checksum = self._simple_checksum(plaintext)
            if stored_checksum != expected_checksum:
                raise ValueError("Checksum mismatch")
            return plaintext

    def _xor_cipher(self, data: bytes, nonce: bytes) -> bytes:
        """Simple XOR cipher fallback (NOT cryptographically secure)"""
        # Expand key + nonce to data length
        key_stream = (self.key + nonce) * ((len(data) // (self.KEY_SIZE + self.NONCE_SIZE)) + 1)
        return bytes(a ^ b for a, b in zip(data, key_stream))

    def _simple_checksum(self, data: bytes) -> bytes:
        """Simple checksum for fallback encryption"""
        # Use key to create a keyed checksum
        checksum = 0
        for i, byte in enumerate(data):
            checksum ^= byte ^ self.key[i % self.KEY_SIZE]
            checksum = ((checksum << 1) | (checksum >> 31)) & 0xFFFFFFFF
        return struct.pack(">IIII", checksum, checksum ^ 0xDEADBEEF, checksum ^ 0xCAFEBABE, checksum ^ 0x12345678)


def derive_shared_key(my_key: bytes, peer_key: bytes) -> bytes:
    """Derive a shared key from two party keys

    Simple XOR-based key derivation. For a real application,
    you'd use proper key exchange (ECDH) or KDF.

    Args:
        my_key: Our encryption key
        peer_key: Peer's encryption key

    Returns:
        Derived shared key
    """
    if len(my_key) != PartyCrypto.KEY_SIZE or len(peer_key) != PartyCrypto.KEY_SIZE:
        raise ValueError("Keys must be 32 bytes")

    # XOR keys together and hash-like mixing
    shared = bytes(a ^ b for a, b in zip(my_key, peer_key))

    # Simple mixing to avoid weak keys if XOR results in zeros
    result = bytearray(shared)
    for i in range(len(result)):
        result[i] = (result[i] + i + 0x5A) & 0xFF
        result[i] ^= result[(i + 1) % len(result)]

    return bytes(result)
