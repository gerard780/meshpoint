"""Capture source for the RAK2287 SX1302 LoRa concentrator.

Requires a Raspberry Pi with the RAK2287 HAT connected via SPI,
and the patched libloragw.so compiled and installed.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, AsyncIterator, Optional

from src.capture.base import CaptureSource
from src.hal.concentrator_config import ConcentratorChannelPlan
from src.hal.sx1302_wrapper import BW_MAP, SX1302Wrapper
from src.models.packet import Protocol, RawCapture
from src.models.signal import SignalMetrics

if TYPE_CHECKING:
    from src.config import RadioConfig

logger = logging.getLogger(__name__)

# Frequency (Hz) used by Meshtastic on EU868.  Packets on this frequency
# are routed to the Meshtastic decoder; everything else is treated as LoRaWAN.
# Only the ch8 service channel (869.525 MHz) can decode Meshtastic -- ch0-ch7
# multi-SF channels share a single board-wide LoRaWAN sync word, so no other
# frequency will ever carry a Meshtastic-decoded packet (see eu868_lorawan()
# in concentrator_config.py).
_MESHTASTIC_EU868_FREQS_HZ: frozenset[int] = frozenset({
    869_525_000,
})

# Emergency pager project: ch9's own frequency and sync word, fixed
# constants rather than config since there's no real protocol/firmware
# yet -- see memory/project_m1_meshpoint.md for the decision writeup.
# 869.4625 MHz sits inside the ETSI EU868 "sub-band P" high-power window
# (869.40-869.65 MHz) and 62.5 kHz clear of 869.525 MHz (this concentrator's
# own Meshtastic channel, and the frequency real-world TTN gateways use for
# RX2 downlinks) -- deliberately not stacked on that exact frequency.
# 0x946437 is a 3-byte sync word, longer than ch0-7/ch8's 1-byte LoRa sync
# words, since FSK sync detection is raw bit-pattern correlation and
# benefits more from extra length against ambient sub-band traffic.
# Reads as "PAGER" in hex leetspeak; also checked against the alternatives
# for real RF quality (longest identical-bit run, no repeating
# sub-pattern) before picking it, not chosen for the joke alone --
# candidates like 0xAAAA.. (alternates just like a radio preamble) or
# 0xC0FFEE (an 11-bit run of 1s) would have real false-lock risk.
PAGER_FSK_FREQUENCY_HZ = 869_462_500
PAGER_FSK_SYNC_WORD = 0x946437
PAGER_FSK_SYNC_WORD_SIZE = 3
PAGER_FSK_RF_CHAIN = 1


class ConcentratorCaptureSource(CaptureSource):
    """Captures LoRa packets via the RAK2287 SX1302 concentrator."""

    def __init__(
        self,
        spi_path: str = "/dev/spidev0.0",
        lib_path: Optional[str] = None,
        channel_plan: Optional[ConcentratorChannelPlan] = None,
        poll_interval_ms: int = 10,
        syncword: int = 0x2B,
        radio_config: Optional[RadioConfig] = None,
        sx1261_spi_path: str = "",
        pager_enabled: bool = False,
    ):
        self._wrapper = SX1302Wrapper(
            lib_path=lib_path,
            spi_path=spi_path,
            sx1261_spi_path=sx1261_spi_path,
        )
        self._channel_plan = self._resolve_channel_plan(
            channel_plan, radio_config
        )
        self._poll_interval = poll_interval_ms / 1000.0
        self._syncword = syncword
        self._pager_enabled = pager_enabled
        self._running = False
        self._restart_lock = asyncio.Lock()

    @staticmethod
    def _resolve_channel_plan(
        channel_plan: Optional[ConcentratorChannelPlan],
        radio_config: Optional[RadioConfig],
    ) -> ConcentratorChannelPlan:
        if radio_config is not None:
            return ConcentratorChannelPlan.from_radio_config(
                region=radio_config.region,
                frequency_mhz=radio_config.frequency_mhz,
                spreading_factor=radio_config.spreading_factor,
                bandwidth_khz=radio_config.bandwidth_khz,
            )
        if channel_plan is not None:
            return channel_plan
        return ConcentratorChannelPlan.meshtastic_us915_default()

    @property
    def name(self) -> str:
        return "concentrator"

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def rx_crc_stats(self) -> tuple[int, int]:
        """(crc_bad_total, no_crc_total) since concentrator start."""
        return self._wrapper.crc_bad_count, self._wrapper.no_crc_count

    async def start(self) -> None:
        self._wrapper.load()

        late_reset = os.environ.get("CONCENTRATOR_LATE_RESET", "0") == "1"

        if not late_reset:
            self._wrapper.reset()

        self._wrapper.configure(self._channel_plan)

        if self._pager_enabled:
            self._wrapper.configure_fsk_channel(
                rf_chain=PAGER_FSK_RF_CHAIN,
                rf_chain_freq_hz=self._channel_plan.radio_1_freq_hz,
                frequency_hz=PAGER_FSK_FREQUENCY_HZ,
                sync_word=PAGER_FSK_SYNC_WORD,
                sync_word_size=PAGER_FSK_SYNC_WORD_SIZE,
            )

        if late_reset:
            # Perform reset as late as possible, right before lgw_start().
            # This is required on some sensitive RAK Hotspot V2 / RAK7248
            # carriers where an earlier reset (from the pre-script or early
            # Python call) can leave the chip in a bad state.
            self._wrapper.reset()

        self._wrapper.start()
        self._wrapper.set_syncword(self._syncword)
        self._wrapper.set_tx_syncword(self._syncword)
        self._running = True
        logger.info(
            "Concentrator capture started (syncword=0x%02X)",
            self._syncword,
        )

    async def stop(self) -> None:
        self._running = False
        self._wrapper.stop()
        logger.info("Concentrator capture stopped")

    async def restart_pipeline(self) -> None:
        """Stop RX, reset the SX1302, and restart without restarting meshpoint."""
        async with self._restart_lock:
            self._running = False
            await asyncio.sleep(0.15)
            self._wrapper.stop()
            await self.start()

    async def packets(self) -> AsyncIterator[RawCapture]:
        poll_count = 0
        while self._running:
            raw_packets = self._wrapper.receive()
            poll_count += 1
            if poll_count == 1 or poll_count % 50000 == 0:
                logger.info(
                    "Receive loop alive (poll #%d, %d pkt this cycle)",
                    poll_count, len(raw_packets),
                )

            for pkt in raw_packets:
                signal = SignalMetrics(
                    rssi=pkt.rssi,
                    snr=pkt.snr,
                    frequency_mhz=pkt.frequency_hz / 1_000_000.0,
                    spreading_factor=pkt.spreading_factor,
                    bandwidth_khz=BW_MAP.get(pkt.bandwidth, 125.0),
                    timestamp=datetime.now(timezone.utc),
                )

                if pkt.modulation == "fsk":
                    # ch9 pager traffic -- routed by capture_source prefix
                    # straight to _adapt_pager in coordinator.py, bypassing
                    # PacketRouter.decode()'s Meshtastic/LoRaWAN/MeshCore
                    # trial-decode fallback entirely (foreign FSK framing
                    # would never match any of those anyway).
                    yield RawCapture(
                        payload=pkt.payload,
                        signal=signal,
                        capture_source="pager",
                        timestamp=datetime.now(timezone.utc),
                        protocol_hint=Protocol.PAGER,
                    )
                    continue

                protocol_hint = (
                    Protocol.MESHTASTIC
                    if pkt.frequency_hz in _MESHTASTIC_EU868_FREQS_HZ
                    else Protocol.LORAWAN
                )

                yield RawCapture(
                    payload=pkt.payload,
                    signal=signal,
                    capture_source="concentrator",
                    timestamp=datetime.now(timezone.utc),
                    protocol_hint=protocol_hint,
                )

            await asyncio.sleep(self._poll_interval)
