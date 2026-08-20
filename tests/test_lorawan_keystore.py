"""Tests for LoRaWANKeyStore."""

from __future__ import annotations

import unittest

from src.decode.lorawan_keystore import LoRaWANKeyStore


class TestLoRaWANKeyStore(unittest.TestCase):

    def test_add_and_lookup_root_keys(self):
        store = LoRaWANKeyStore()
        dev_eui = "70:B3:D5:7E:D0:07:8B:FD"
        app_key_hex = "10" * 16
        nwk_key_hex = "20" * 16

        store.add_device(dev_eui, app_key_hex, nwk_key_hex)

        self.assertTrue(store.has_device(dev_eui))
        app_key, nwk_key = store.root_keys_for(dev_eui)
        self.assertEqual(app_key, bytes.fromhex(app_key_hex))
        self.assertEqual(nwk_key, bytes.fromhex(nwk_key_hex))

    def test_lookup_is_case_insensitive(self):
        store = LoRaWANKeyStore()
        store.add_device("70:b3:d5:7e:d0:07:8b:fd", "10" * 16, "20" * 16)

        self.assertTrue(store.has_device("70:B3:D5:7E:D0:07:8B:FD"))

    def test_unconfigured_device_returns_none(self):
        store = LoRaWANKeyStore()
        self.assertIsNone(store.root_keys_for("00:00:00:00:00:00:00:00"))
        self.assertFalse(store.has_device("00:00:00:00:00:00:00:00"))

    def test_wrong_key_length_rejected(self):
        store = LoRaWANKeyStore()
        with self.assertRaises(ValueError):
            store.add_device("70:B3:D5:7E:D0:07:8B:FD", "1234", "20" * 16)

    def test_session_key_round_trip(self):
        store = LoRaWANKeyStore()
        self.assertIsNone(store.session_key_for(0x260BA627))

        app_skey = bytes(range(16))
        store.set_session_key(0x260BA627, app_skey)

        self.assertEqual(store.session_key_for(0x260BA627), app_skey)

    def test_rejoin_overwrites_previous_session_key(self):
        store = LoRaWANKeyStore()
        store.set_session_key(1, bytes(16))
        store.set_session_key(1, bytes(range(16)))

        self.assertEqual(store.session_key_for(1), bytes(range(16)))


if __name__ == "__main__":
    unittest.main()
