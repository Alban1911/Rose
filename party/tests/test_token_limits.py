import base64
import os
import struct
import time
import tracemalloc
import unittest
import zlib

from party.protocol.token_codec import PartyToken, create_token

# Longest token text Rose accepts (token_codec.MAX_TOKEN_LENGTH)
MAX_TOKEN_LENGTH = 160


def encode_payload(payload: bytes, level: int = 9, prefix: str = "ROSE:", trailing: bytes = b"") -> str:
    compressed = zlib.compress(payload, level) + trailing
    return prefix + base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")


def v1_payload(summoner_id: int, key: bytes, timestamp: int) -> bytes:
    # version, timestamp, summoner, external/internal port, external/internal IPv4, key
    return struct.pack(">BIQHH", 1, timestamp, summoner_id, 5000, 5001) + bytes([1, 2, 3, 4, 10, 0, 0, 2]) + key


def v2_payload(summoner_id: int, key: bytes, timestamp: int, version: int = 2) -> bytes:
    return struct.pack(">BIQ", version, timestamp, summoner_id) + key


class ValidTokenTests(unittest.TestCase):
    def test_v2_tokens_round_trip_with_or_without_prefix_and_padding(self):
        token = create_token(summoner_id=2**63 + 5, encryption_key=os.urandom(32))
        encoded = token.encode()
        self.assertLessEqual(len(encoded), MAX_TOKEN_LENGTH)

        bare = encoded[len("ROSE:"):]
        padded = bare + "=" * (-len(bare) % 4)
        for text in (encoded, bare, padded):
            decoded = PartyToken.decode(text)
            self.assertEqual(decoded.summoner_id, token.summoner_id)
            self.assertEqual(decoded.encryption_key, token.encryption_key)
            self.assertEqual(decoded.version, 2)

    def test_legacy_v1_tokens_are_still_read(self):
        key = os.urandom(32)
        now = int(time.time())
        for level in (0, 9):  # stored (largest possible) and the encoder's own level
            encoded = encode_payload(v1_payload(77, key, now), level=level)
            self.assertLessEqual(len(encoded), MAX_TOKEN_LENGTH)
            decoded = PartyToken.decode(encoded)
            self.assertEqual((decoded.version, decoded.summoner_id, decoded.encryption_key), (1, 77, key))

    def test_old_tokens_decode_and_keep_their_expiry(self):
        encoded = encode_payload(v2_payload(9, b"k" * 32, int(time.time()) - 7 * 24 * 3600))
        decoded = PartyToken.decode(encoded)
        self.assertTrue(decoded.is_expired())
        self.assertLess(decoded.time_until_expiry(), 0)


class RejectedTokenTests(unittest.TestCase):
    def assertRejected(self, text):
        with self.assertRaises(ValueError):
            PartyToken.decode(text)

    def test_a_small_token_that_inflates_far_past_a_payload_is_refused_without_inflating_it(self):
        payload = v2_payload(1, b"k" * 32, int(time.time())) + bytes(72 * 1024)
        encoded = encode_payload(payload)
        self.assertLessEqual(len(encoded), MAX_TOKEN_LENGTH)  # passes the length check

        tracemalloc.start()
        try:
            self.assertRejected(encoded)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 60 * 1024)

    def test_overlong_text_is_refused_before_decoding(self):
        encoded = create_token(summoner_id=3, encryption_key=b"k" * 32).encode()
        self.assertRejected(encoded + "A" * (MAX_TOKEN_LENGTH - len(encoded) + 1))

    def test_payloads_of_the_wrong_size_are_refused(self):
        now = int(time.time())
        self.assertRejected(encode_payload(v2_payload(1, b"k" * 32, now) + b"x"))
        self.assertRejected(encode_payload(v2_payload(1, b"k" * 31, now)))
        self.assertRejected(encode_payload(v1_payload(1, b"k" * 32, now) + b"x"))
        self.assertRejected(encode_payload(b""))

    def test_unknown_versions_are_refused(self):
        self.assertRejected(encode_payload(v2_payload(1, b"k" * 32, int(time.time()), version=3)))

    def test_truncated_and_trailing_streams_are_refused(self):
        valid = zlib.compress(v2_payload(1, b"k" * 32, int(time.time())), 9)
        for compressed in (valid[:-4], valid + b"\x00junk"):
            text = "ROSE:" + base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")
            self.assertRejected(text)

    def test_text_that_is_not_base64_zlib_is_refused(self):
        for text in ("ROSE:", "ROSE:!!!!", "not a token", "ROSE:é"):
            self.assertRejected(text)


if __name__ == "__main__":
    unittest.main()
