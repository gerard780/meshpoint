"""Tests for ``LoRaWANDecoder``'s Join-Accept recognition.

Join-Accept (MType=001) was silently dropped entirely before v0.8.1 --
``decode()`` didn't even route it. Added as the first step toward real
FRMPayload decrypt (deriving AppSKey from a captured Join-Accept via
NwkKey needs a real captured Join-Accept to derive from). Length/MHDR
values below are cross-checked against a real Join-Accept captured live
on 2026-08-20 (basicstation-docker log: "868.5MHz 16.0dBm DR3 SF9/BW125
frame=20620C2B...04571EC9 (33 bytes)" -- MHDR 0x20, 33 bytes, matches
exactly) -- see project memory ("LoRaWAN key store + payload decrypt").
"""

from __future__ import annotations

import unittest

from Crypto.Cipher import AES

from src.decode.lorawan_crypto import decrypt_frm_payload, derive_app_skey
from src.decode.lorawan_decoder import LoRaWANDecoder
from src.decode.lorawan_keystore import LoRaWANKeyStore
from src.models.packet import PacketType


def _join_accept_frame(with_cflist: bool) -> bytes:
    """MHDR=0x20 (Join-Accept) + the right number of arbitrary bytes.

    Real content is AES-encrypted so there are no "correct" plaintext
    bytes to construct here -- only length and MHDR matter for
    recognition, which is all this decoder does pre-decrypt.
    """
    body_len = 32 if with_cflist else 16
    return bytes([0x20]) + bytes(range(body_len))


def _join_request_frame(dev_eui_str: str, dev_nonce: int = 0) -> bytes:
    app_eui = bytes(8)  # content doesn't matter for these tests
    dev_eui = bytes.fromhex(dev_eui_str.replace(":", ""))[::-1]  # LSB order
    return (
        bytes([0x00])
        + app_eui
        + dev_eui
        + dev_nonce.to_bytes(2, "little")
        + bytes(4)  # MIC
    )


class TestJoinAcceptRecognition(unittest.TestCase):

    def test_join_accept_without_cflist_recognized(self):
        decoder = LoRaWANDecoder()
        packet = decoder.decode(_join_accept_frame(with_cflist=False))

        self.assertIsNotNone(packet)
        self.assertEqual(packet.packet_type, PacketType.LORAWAN_JOIN_ACCEPT)
        self.assertFalse(packet.decrypted)
        self.assertFalse(packet.decoded_payload["has_cflist"])

    def test_join_accept_with_cflist_recognized(self):
        decoder = LoRaWANDecoder()
        packet = decoder.decode(_join_accept_frame(with_cflist=True))

        self.assertIsNotNone(packet)
        self.assertEqual(packet.packet_type, PacketType.LORAWAN_JOIN_ACCEPT)
        self.assertTrue(packet.decoded_payload["has_cflist"])

    def test_wrong_length_join_accept_shaped_frame_rejected(self):
        """MType=001 but a length that isn't 17 or 33 bytes isn't a real
        Join-Accept -- reject rather than mis-decode garbage."""
        decoder = LoRaWANDecoder()
        frame = bytes([0x20]) + bytes(20)  # 21 bytes total, not 17 or 33

        self.assertIsNone(decoder.decode(frame))

    def test_join_accept_tagged_with_recent_join_request_dev_eui(self):
        decoder = LoRaWANDecoder()
        dev_eui = "70:B3:D5:7E:D0:07:8B:FD"

        decoder.decode(_join_request_frame(dev_eui))
        packet = decoder.decode(_join_accept_frame(with_cflist=False))

        self.assertEqual(packet.decoded_payload["likely_dev_eui"], dev_eui)
        self.assertEqual(packet.destination_id, dev_eui)

    def test_join_accept_with_no_prior_join_request_has_no_dev_eui(self):
        decoder = LoRaWANDecoder()
        packet = decoder.decode(_join_accept_frame(with_cflist=False))

        self.assertIsNone(packet.decoded_payload["likely_dev_eui"])
        self.assertEqual(packet.destination_id, "unknown")


class TestKeystoreIntegration(unittest.TestCase):
    """Full pipeline: Join-Request -> real Join-Accept decrypt+derive ->
    real Data Up FRMPayload decrypt, using a configured LoRaWANKeyStore.
    Synthetic keys (not real device secrets), but a real end-to-end
    exercise of decrypt_join_accept()/derive_app_skey()/
    decrypt_frm_payload() wired through the actual decoder, not just the
    crypto module in isolation (see test_lorawan_crypto.py for that)."""

    def setUp(self):
        self.app_key = bytes(range(16, 32))
        self.nwk_key = bytes(range(16))
        self.dev_eui_raw = bytes.fromhex("70b3d57ed0078bfd")  # LSB order on the wire
        self.app_eui_raw = bytes.fromhex("aae46192ab514f93")
        self.dev_nonce = 7
        self.dev_eui_str = ":".join(f"{b:02X}" for b in reversed(self.dev_eui_raw))

    def _join_request_frame(self) -> bytes:
        return (
            bytes([0x00])
            + self.app_eui_raw
            + self.dev_eui_raw
            + self.dev_nonce.to_bytes(2, "little")
            + bytes(4)  # MIC, unchecked
        )

    def _join_accept_frame(self, dev_addr: int, join_nonce: bytes) -> bytes:
        plaintext = (
            join_nonce
            + bytes([0x01, 0x02, 0x03])  # NetID
            + dev_addr.to_bytes(4, "little")
            + bytes([0x00, 0x01])  # DLSettings, RxDelay
            + bytes(4)  # MIC, unchecked
        )
        ciphertext = AES.new(self.nwk_key, AES.MODE_ECB).decrypt(plaintext)
        return bytes([0x20]) + ciphertext

    def test_join_accept_decrypts_and_installs_session_key(self):
        keystore = LoRaWANKeyStore()
        keystore.add_device(
            self.dev_eui_str, self.app_key.hex(), self.nwk_key.hex()
        )
        decoder = LoRaWANDecoder(keystore)

        dev_addr = 0x260BA627
        join_nonce = bytes([0x01, 0x02, 0x03])

        decoder.decode(self._join_request_frame())
        packet = decoder.decode(self._join_accept_frame(dev_addr, join_nonce))

        self.assertTrue(packet.decrypted)
        self.assertEqual(packet.decoded_payload["dev_addr"], f"{dev_addr:08X}")

        expected_app_skey = derive_app_skey(
            self.app_key, join_nonce, self.app_eui_raw, self.dev_nonce
        )
        self.assertEqual(keystore.session_key_for(dev_addr), expected_app_skey)

    def test_data_up_decrypts_once_session_key_is_known(self):
        keystore = LoRaWANKeyStore()
        keystore.add_device(
            self.dev_eui_str, self.app_key.hex(), self.nwk_key.hex()
        )
        decoder = LoRaWANDecoder(keystore)

        dev_addr = 0x260BA627
        join_nonce = bytes([0x01, 0x02, 0x03])
        decoder.decode(self._join_request_frame())
        decoder.decode(self._join_accept_frame(dev_addr, join_nonce))

        app_skey = keystore.session_key_for(dev_addr)
        fcnt = 5
        plaintext = b"hello world"
        ciphertext = decrypt_frm_payload(app_skey, plaintext, dev_addr, fcnt, uplink=True)

        frame = (
            bytes([0x40])  # MHDR: Unconfirmed Data Up
            + dev_addr.to_bytes(4, "little")
            + bytes([0x00])  # FCtrl, no FOpts
            + fcnt.to_bytes(2, "little")
            + bytes([0x02])  # FPort
            + ciphertext
            + bytes(4)  # MIC, unchecked
        )

        packet = decoder.decode(frame)

        self.assertTrue(packet.decrypted)
        self.assertEqual(
            packet.decoded_payload["frm_payload_decrypted"], plaintext.hex().upper()
        )

    def test_data_up_stays_undecrypted_without_a_session_key(self):
        decoder = LoRaWANDecoder(LoRaWANKeyStore())  # no devices configured
        dev_addr = 0x11223344
        frame = (
            bytes([0x40])
            + dev_addr.to_bytes(4, "little")
            + bytes([0x00])
            + (1).to_bytes(2, "little")
            + bytes([0x02])
            + bytes([0xAA, 0xBB])
            + bytes(4)
        )

        packet = decoder.decode(frame)

        self.assertFalse(packet.decrypted)
        self.assertNotIn("frm_payload_decrypted", packet.decoded_payload)


if __name__ == "__main__":
    unittest.main()
