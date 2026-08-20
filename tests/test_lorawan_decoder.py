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

from src.decode.lorawan_decoder import LoRaWANDecoder
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


if __name__ == "__main__":
    unittest.main()
