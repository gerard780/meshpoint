"""Tests for lorawan_crypto.py.

Round-trip/internal-consistency tests only -- there's no verified
official LoRaWAN test vector in this codebase (see the module's own
docstring for why). These catch offset/byte-order bugs in this code's
own encrypt<->decrypt symmetry, not a shared spec misreading.
"""

from __future__ import annotations

import unittest

from Crypto.Cipher import AES

from src.decode.lorawan_crypto import (
    decrypt_frm_payload,
    decrypt_join_accept,
    derive_app_skey,
)

NWK_KEY = bytes(range(16))
APP_KEY = bytes(range(16, 32))
APP_SKEY = bytes(range(32, 48))


def _fake_join_accept_ciphertext(plaintext: bytes, nwk_key: bytes = NWK_KEY) -> bytes:
    """What the network server would actually transmit: plaintext run
    through AES128-ECB *decrypt* with NwkKey (spec 6.2.4) -- the inverse
    of what decrypt_join_accept() does to recover it."""
    return AES.new(nwk_key, AES.MODE_ECB).decrypt(plaintext)


class TestDecryptJoinAccept(unittest.TestCase):

    def test_round_trip_without_cflist(self):
        join_nonce = bytes([0x01, 0x02, 0x03])
        net_id = bytes([0xAA, 0xBB, 0xCC])
        dev_addr = 0x260BA627
        dl_settings = 0x30
        rx_delay = 0x05
        mic = bytes([0xDE, 0xAD, 0xBE, 0xEF])

        plaintext = (
            join_nonce + net_id
            + dev_addr.to_bytes(4, "little")
            + bytes([dl_settings, rx_delay])
            + mic
        )
        self.assertEqual(len(plaintext), 16)

        fields = decrypt_join_accept(NWK_KEY, _fake_join_accept_ciphertext(plaintext))

        self.assertIsNotNone(fields)
        self.assertEqual(fields["join_nonce"], join_nonce)
        self.assertEqual(fields["net_id"], net_id)
        self.assertEqual(fields["dev_addr"], dev_addr)
        self.assertEqual(fields["dl_settings"], dl_settings)
        self.assertEqual(fields["rx_delay"], rx_delay)
        self.assertIsNone(fields["cflist"])
        self.assertEqual(fields["mic"], mic)

    def test_round_trip_with_cflist(self):
        join_nonce = bytes([0x10, 0x20, 0x30])
        net_id = bytes([0x01, 0x02, 0x03])
        dev_addr = 0x0F0E0D0C
        dl_settings = 0x00
        rx_delay = 0x01
        cflist = bytes(range(16))
        mic = bytes([0x11, 0x22, 0x33, 0x44])

        plaintext = (
            join_nonce + net_id
            + dev_addr.to_bytes(4, "little")
            + bytes([dl_settings, rx_delay])
            + cflist
            + mic
        )
        self.assertEqual(len(plaintext), 32)

        fields = decrypt_join_accept(NWK_KEY, _fake_join_accept_ciphertext(plaintext))

        self.assertEqual(fields["cflist"], cflist)
        self.assertEqual(fields["dev_addr"], dev_addr)
        self.assertEqual(fields["mic"], mic)

    def test_wrong_length_rejected(self):
        self.assertIsNone(decrypt_join_accept(NWK_KEY, bytes(20)))


class TestDeriveAppSKey(unittest.TestCase):

    def test_deterministic_and_correct_length(self):
        join_nonce = bytes([0x01, 0x02, 0x03])
        join_eui = bytes.fromhex("aae46192ab514f93")
        dev_nonce = 1

        key1 = derive_app_skey(APP_KEY, join_nonce, join_eui, dev_nonce)
        key2 = derive_app_skey(APP_KEY, join_nonce, join_eui, dev_nonce)

        self.assertEqual(len(key1), 16)
        self.assertEqual(key1, key2)

    def test_matches_manual_block_construction(self):
        """Directly checks the 0x02 | JoinNonce | JoinEUI | DevNonce | pad
        block assembly against an independently-built block, not just
        that the function is internally consistent with itself."""
        join_nonce = bytes([0xAA, 0xBB, 0xCC])
        join_eui = bytes(range(8))
        dev_nonce = 0x0102

        expected_block = (
            bytes([0x02]) + join_nonce + join_eui
            + dev_nonce.to_bytes(2, "little") + bytes(2)
        )
        expected = AES.new(APP_KEY, AES.MODE_ECB).encrypt(expected_block)

        self.assertEqual(
            derive_app_skey(APP_KEY, join_nonce, join_eui, dev_nonce), expected
        )

    def test_different_dev_nonce_gives_different_key(self):
        join_nonce = bytes([0x01, 0x02, 0x03])
        join_eui = bytes(8)

        key_a = derive_app_skey(APP_KEY, join_nonce, join_eui, dev_nonce=0)
        key_b = derive_app_skey(APP_KEY, join_nonce, join_eui, dev_nonce=1)

        self.assertNotEqual(key_a, key_b)


class TestDecryptFrmPayload(unittest.TestCase):

    def test_round_trip_recovers_plaintext(self):
        plaintext = b"hello lorawan world!!"  # not a multiple of 16
        dev_addr = 0x260BA627
        fcnt = 42

        ciphertext = decrypt_frm_payload(
            APP_SKEY, plaintext, dev_addr, fcnt, uplink=True
        )
        recovered = decrypt_frm_payload(
            APP_SKEY, ciphertext, dev_addr, fcnt, uplink=True
        )

        self.assertEqual(recovered, plaintext)
        self.assertNotEqual(ciphertext, plaintext)

    def test_wrong_direction_gives_different_keystream(self):
        plaintext = b"same fcnt different direction"
        dev_addr = 1
        fcnt = 1

        uplink_ct = decrypt_frm_payload(APP_SKEY, plaintext, dev_addr, fcnt, uplink=True)
        downlink_ct = decrypt_frm_payload(APP_SKEY, plaintext, dev_addr, fcnt, uplink=False)

        self.assertNotEqual(uplink_ct, downlink_ct)

    def test_empty_payload(self):
        self.assertEqual(decrypt_frm_payload(APP_SKEY, b"", 1, 1), b"")


if __name__ == "__main__":
    unittest.main()
