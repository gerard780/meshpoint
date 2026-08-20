"""Tests for ``SX1302Wrapper.receive`` packet filtering.

Locks in the contract: CRC_BAD and any unknown status are always dropped
(RF-corrupted bytes, no legitimate use). NO_CRC is more nuanced --
Meshtastic's own channel (if_chain == LGW_MULTI_NB, ch8) and FSK/pager
traffic (ch9) still drop NO_CRC (CRC is always expected there by
spec/convention, so NO_CRC there really is noise-floor garbage). The
LoRaWAN multi-SF channels (ch0-7) now pass NO_CRC through instead --
real LoRaWAN downlinks (Join-Accept, Data Down, ...) are *always* NO_CRC
by spec (LoRaWAN's PHY CRC is an uplink-only feature), so dropping them
there meant every downlink was silently discarded, not just noise.
Without the CRC_BAD/unknown-status filter, RF-corrupted bytes flow into
the Meshtastic decoder where they create three classes of noise:
  - phantom node IDs (corrupted source field)
  - false ENCRYPTED packets (corrupted channel hash byte)
  - garbled-but-readable text (corrupted payload mid-packet)

History: v0.7.2 added the CRC_BAD drop. v0.7.3 extended the gate to
NO_CRC and unknown statuses after fleet diagnostics on high-traffic
Meshpoints (nopemesh, kmax) showed NO_CRC packets at the noise floor
were the dominant remaining phantom-creation path -- that fleet has no
LoRaWAN capture, so the fix was correct for the problem at hand but
too broad once LoRaWAN downlink capture became a real use case.
v0.8.1 narrowed NO_CRC-drop to Meshtastic/FSK channels only.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from src.hal.sx1302_types import LgwPktRxS
from src.hal.sx1302_wrapper import (
    BW_250KHZ,
    LGW_MULTI_NB,
    LGW_PKT_MAX,
    MOD_FSK,
    MOD_LORA,
    STAT_CRC_BAD,
    STAT_CRC_OK,
    STAT_NO_CRC,
    SX1302Wrapper,
)


def _set_packet(
    pkt: LgwPktRxS,
    *,
    status: int,
    size: int,
    if_chain: int = 0,
    modulation: int = MOD_LORA,
    rssi: float = -50.0,
    snr: float = 7.0,
    payload_byte: int = 0x42,
) -> None:
    """Populate the minimum LgwPktRxS fields the wrapper reads."""
    pkt.status = status
    pkt.size = size
    pkt.if_chain = if_chain
    pkt.modulation = modulation
    pkt.datarate = 11
    pkt.bandwidth = BW_250KHZ
    pkt.coderate = 0
    pkt.rssic = rssi
    pkt.snr = snr
    pkt.freq_hz = 906_875_000
    pkt.count_us = 12345
    for i in range(min(size, 256)):
        pkt.payload[i] = payload_byte


def _build_wrapper() -> SX1302Wrapper:
    """Build a wrapper with a mocked ctypes library, ready to receive()."""
    wrapper = SX1302Wrapper()
    wrapper._lib = MagicMock()
    wrapper._started = True
    return wrapper


class TestReceiveFiltersCorruptedPackets(unittest.TestCase):
    """Only CRC_OK packets reach the decoder; everything else is dropped."""

    def test_crc_bad_packet_is_dropped(self):
        wrapper = _build_wrapper()

        def populate(_max, pkt_array):
            _set_packet(pkt_array[0], status=STAT_CRC_BAD, size=32)
            return 1

        wrapper._lib.lgw_receive.side_effect = populate

        result = wrapper.receive()

        self.assertEqual(result, [])
        self.assertEqual(wrapper.crc_bad_count, 1)
        self.assertEqual(wrapper.no_crc_count, 0)
        self.assertEqual(wrapper.unknown_status_count, 0)

    def test_crc_ok_packet_passes_through(self):
        wrapper = _build_wrapper()

        def populate(_max, pkt_array):
            _set_packet(pkt_array[0], status=STAT_CRC_OK, size=16)
            return 1

        wrapper._lib.lgw_receive.side_effect = populate

        result = wrapper.receive()

        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].crc_ok)
        self.assertEqual(len(result[0].payload), 16)
        self.assertEqual(wrapper.crc_bad_count, 0)
        self.assertEqual(wrapper.no_crc_count, 0)
        self.assertEqual(wrapper.unknown_status_count, 0)

    def test_no_crc_packet_on_meshtastic_channel_is_dropped(self):
        """STAT_NO_CRC on Meshtastic's own channel (ch8, if_chain ==
        LGW_MULTI_NB) carries corrupted header bytes that produce phantom
        node rows downstream. v0.7.3 drops them at source; v0.8.1 kept
        that behavior specifically for this channel (never touch ch8/9)."""
        wrapper = _build_wrapper()

        def populate(_max, pkt_array):
            _set_packet(
                pkt_array[0], status=STAT_NO_CRC, size=16, if_chain=LGW_MULTI_NB
            )
            return 1

        wrapper._lib.lgw_receive.side_effect = populate

        result = wrapper.receive()

        self.assertEqual(result, [])
        self.assertEqual(wrapper.no_crc_count, 1)
        self.assertEqual(wrapper.crc_bad_count, 0)
        self.assertEqual(wrapper.unknown_status_count, 0)

    def test_no_crc_fsk_packet_is_dropped(self):
        """STAT_NO_CRC on FSK (ch9/pager) is also still dropped -- pager's
        own no_crc=True send option is a deliberate application-level
        choice, but a raw NO_CRC receive here is unrelated: FSK isn't part
        of the LoRaWAN-downlinks-are-legitimately-NO_CRC exception."""
        wrapper = _build_wrapper()

        def populate(_max, pkt_array):
            _set_packet(
                pkt_array[0], status=STAT_NO_CRC, size=16,
                if_chain=9, modulation=MOD_FSK,
            )
            return 1

        wrapper._lib.lgw_receive.side_effect = populate

        result = wrapper.receive()

        self.assertEqual(result, [])
        self.assertEqual(wrapper.no_crc_count, 1)

    def test_no_crc_packet_on_lorawan_channel_passes_through(self):
        """STAT_NO_CRC on a LoRaWAN multi-SF channel (ch0-7) now passes
        through instead of being dropped -- real LoRaWAN downlinks
        (Join-Accept, Data Down, ...) are *always* NO_CRC by spec, so
        this is what a genuine downlink looks like, not noise. Added
        v0.8.1 for LoRaWAN Join-Accept capture -- see project memory."""
        wrapper = _build_wrapper()

        def populate(_max, pkt_array):
            _set_packet(
                pkt_array[0], status=STAT_NO_CRC, size=33,
                if_chain=3, modulation=MOD_LORA,
            )
            return 1

        wrapper._lib.lgw_receive.side_effect = populate

        result = wrapper.receive()

        self.assertEqual(len(result), 1)
        self.assertFalse(result[0].crc_ok)
        self.assertEqual(len(result[0].payload), 33)
        self.assertEqual(wrapper.no_crc_count, 1)
        self.assertEqual(wrapper.crc_bad_count, 0)
        self.assertEqual(wrapper.unknown_status_count, 0)

    def test_unknown_status_packet_is_dropped(self):
        """Anything that isn't CRC_OK / CRC_BAD / NO_CRC is treated as
        suspect and dropped, so a future HAL revision that introduces a
        new status code can't silently re-open the leak path."""
        wrapper = _build_wrapper()

        def populate(_max, pkt_array):
            _set_packet(pkt_array[0], status=0x42, size=24)
            return 1

        wrapper._lib.lgw_receive.side_effect = populate

        result = wrapper.receive()

        self.assertEqual(result, [])
        self.assertEqual(wrapper.unknown_status_count, 1)
        self.assertEqual(wrapper.crc_bad_count, 0)
        self.assertEqual(wrapper.no_crc_count, 0)

    def test_mixed_batch_returns_only_crc_ok_packets(self):
        """NO_CRC here is on Meshtastic's own channel specifically (ch8,
        if_chain=LGW_MULTI_NB), so it's still dropped -- see the
        LoRaWAN-channel pass-through case in its own dedicated test."""
        wrapper = _build_wrapper()

        def populate(_max, pkt_array):
            _set_packet(pkt_array[0], status=STAT_CRC_OK, size=16, rssi=-40.0)
            _set_packet(pkt_array[1], status=STAT_CRC_BAD, size=32, rssi=-75.0)
            _set_packet(pkt_array[2], status=STAT_CRC_OK, size=24, rssi=-55.0)
            _set_packet(
                pkt_array[3], status=STAT_NO_CRC, size=20, rssi=-110.0,
                if_chain=LGW_MULTI_NB,
            )
            _set_packet(pkt_array[4], status=0x07, size=18, rssi=-95.0)
            return 5

        wrapper._lib.lgw_receive.side_effect = populate

        result = wrapper.receive()

        self.assertEqual(len(result), 2)
        rssi_values = sorted(p.rssi for p in result)
        self.assertEqual(rssi_values, [-55.0, -40.0])
        self.assertEqual(wrapper.crc_bad_count, 1)
        self.assertEqual(wrapper.no_crc_count, 1)
        self.assertEqual(wrapper.unknown_status_count, 1)

    def test_crc_bad_counter_persists_across_calls(self):
        wrapper = _build_wrapper()

        def populate_one_bad(_max, pkt_array):
            _set_packet(pkt_array[0], status=STAT_CRC_BAD, size=32)
            return 1

        wrapper._lib.lgw_receive.side_effect = populate_one_bad

        wrapper.receive()
        wrapper.receive()
        wrapper.receive()

        self.assertEqual(wrapper.crc_bad_count, 3)

    def test_no_crc_counter_persists_across_calls(self):
        wrapper = _build_wrapper()

        def populate_one_no_crc(_max, pkt_array):
            _set_packet(pkt_array[0], status=STAT_NO_CRC, size=20)
            return 1

        wrapper._lib.lgw_receive.side_effect = populate_one_no_crc

        wrapper.receive()
        wrapper.receive()

        self.assertEqual(wrapper.no_crc_count, 2)

    def test_size_zero_packet_is_skipped_before_status_check(self):
        """size==0 is a separate skip path that still works after the fix."""
        wrapper = _build_wrapper()

        def populate(_max, pkt_array):
            _set_packet(pkt_array[0], status=STAT_CRC_OK, size=0)
            return 1

        wrapper._lib.lgw_receive.side_effect = populate

        result = wrapper.receive()

        self.assertEqual(result, [])
        self.assertEqual(wrapper.crc_bad_count, 0)

    def test_receive_returns_empty_when_not_started(self):
        wrapper = SX1302Wrapper()
        wrapper._lib = MagicMock()

        result = wrapper.receive()

        self.assertEqual(result, [])
        wrapper._lib.lgw_receive.assert_not_called()

    def test_lgw_receive_error_returns_empty(self):
        wrapper = _build_wrapper()
        wrapper._lib.lgw_receive.return_value = -1

        result = wrapper.receive()

        self.assertEqual(result, [])
        self.assertEqual(wrapper.crc_bad_count, 0)


class TestReceiveBatchSize(unittest.TestCase):
    def test_uses_lgw_pkt_max_constant(self):
        """Sanity check: the wrapper requests LGW_PKT_MAX packets per poll."""
        wrapper = _build_wrapper()
        wrapper._lib.lgw_receive.return_value = 0

        wrapper.receive()

        args, _ = wrapper._lib.lgw_receive.call_args
        self.assertEqual(args[0], LGW_PKT_MAX)


if __name__ == "__main__":
    unittest.main()
