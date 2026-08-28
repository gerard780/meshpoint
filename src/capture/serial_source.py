from __future__ import annotations

import asyncio
import base64
import hmac
import logging
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from src.capture.base import CaptureSource
from src.capture.serial_radio_handshake import SerialRadioHandshake
from src.capture.serial_self_origin import SerialSelfOriginFilter
from src.models.packet import RawCapture
from src.models.signal import SignalMetrics
from src.radio.channel_frequency import resolve_frequency_mhz

logger = logging.getLogger(__name__)

# Re-export for existing test imports.
__all__ = ["SerialCaptureSource", "SerialSelfOriginFilter"]

_RECONNECT_INITIAL_DELAY_S = 5.0
_RECONNECT_MAX_DELAY_S = 60.0


class SerialCaptureSource(CaptureSource):
    """Captures packets from a Meshtastic radio connected via USB serial.

    Uses the meshtastic-python pub/sub API to receive decoded packets.
    Packets arrive already decoded, so they are re-serialized as raw
    capture events for the pipeline to process uniformly.
    """

    def __init__(
        self,
        port: Optional[str] = None,
        baud: int = 115200,
        label: str = "",
    ):
        self._port = port
        self._baud = baud
        self._label = (label or "").strip()
        self._interface = None
        self._running = False
        self._self_origin = SerialSelfOriginFilter()
        self._radio_info: dict = {"channel_table": {}}
        # Kept separate from _radio_info so channel secrets are never exposed
        # through the status API. Values are firmware-compatible expanded PSKs.
        self._channel_keys: dict[int, bytes] = {}
        self._queue: asyncio.Queue[RawCapture] = asyncio.Queue(maxsize=500)
        self._reconnect_task: Optional[asyncio.Task] = None

    @property
    def name(self) -> str:
        return f"serial_{self._label}" if self._label else "serial"

    @property
    def is_running(self) -> bool:
        return self._running

    def get_radio_info(self) -> dict:
        """Connect-time LoRa/identity snapshot (copy)."""
        return dict(self._radio_info)

    def resolve_channel_index(
        self,
        name: str,
        channel_key: bytes | None = None,
    ) -> Optional[int]:
        """This stick's index for a Meshpoint channel identity.

        Meshtastic channel slots are device-local and can be ordered
        differently on every radio. Match the effective channel name and
        expanded PSK when handshake key data is available. Name-only matching
        remains as a compatibility fallback for older/incomplete handshakes.
        """
        table = self._radio_info.get("channel_table") or {}
        if self._channel_keys:
            if channel_key is None:
                return None
            for idx, ch_name in table.items():
                stick_key = self._channel_keys.get(idx)
                if (
                    ch_name == name
                    and stick_key is not None
                    and hmac.compare_digest(stick_key, channel_key)
                ):
                    return idx
            return None
        for idx, ch_name in table.items():
            if ch_name == name:
                return idx
        return None

    async def start(self) -> None:
        """Open the stick; soft-fail busy/wrong ports so other sources stay up."""
        self._running = True
        try:
            await asyncio.to_thread(self._open_interface)
        except ImportError:
            self._running = False
            logger.error(
                "meshtastic package not installed. "
                "Install with: pip install meshtastic"
            )
            raise
        except Exception:
            logger.warning(
                "Failed to open serial interface on %s; other capture "
                "sources stay up. Will retry in background (port may be "
                "held by gpsd or another process, or the path may be wrong).",
                self._port or "auto-detect",
                exc_info=True,
            )
            self._schedule_reconnect()

    def _open_interface(self) -> None:
        """Blocking open + handshake. Raises on failure."""
        import meshtastic.serial_interface
        from pubsub import pub

        try:
            if self._port:
                self._interface = meshtastic.serial_interface.SerialInterface(
                    devPath=self._port
                )
            else:
                self._interface = meshtastic.serial_interface.SerialInterface()

            own_node = SerialSelfOriginFilter.read_own_node_num(self._interface)
            self._self_origin.set_own_node_num(own_node)
            self._radio_info = SerialRadioHandshake.read(self._interface)
            self._radio_info["own_node_num"] = own_node
            try:
                modem_preset = self._radio_info.get("modem_preset")
                if modem_preset == "CUSTOM":
                    modem_preset = None
                self._radio_info["channel_table"] = self._read_channel_table(
                    self._interface, modem_preset
                )
            except Exception:
                logger.debug(
                    "Could not read channel names from serial interface",
                    exc_info=True,
                )
                self._radio_info["channel_table"] = {}
            try:
                self._channel_keys = self._read_channel_key_table(self._interface)
            except Exception:
                logger.debug(
                    "Could not read channel keys from serial interface; "
                    "falling back to name-only matching",
                    exc_info=True,
                )
                self._channel_keys = {}

            pub.subscribe(self._on_receive, "meshtastic.receive")
            region = self._radio_info.get("region")
            freq = resolve_frequency_mhz(
                region=region,
                channel_num=self._radio_info.get("channel_num"),
                bandwidth_khz=self._radio_info.get("bandwidth_khz") or 250.0,
                channel_name=self._radio_info.get("channel_name"),
                modem_preset=self._radio_info.get("modem_preset"),
                use_preset=self._radio_info.get("use_preset", True),
                frequency_offset=self._radio_info.get("frequency_offset")
                or 0.0,
                override_frequency=self._radio_info.get("override_frequency")
                or 0.0,
            )
            if own_node is not None:
                logger.info(
                    "Serial capture started on %s (own_node=%08x region=%s "
                    "freq=%.3f SF%s BW%s)",
                    self._port or "auto-detect",
                    own_node,
                    region or "?",
                    freq,
                    self._radio_info.get("spreading_factor") or "?",
                    self._radio_info.get("bandwidth_khz") or "?",
                )
            else:
                logger.info(
                    "Serial capture started on %s (region=%s freq=%.3f)",
                    self._port or "auto-detect",
                    region or "?",
                    freq,
                )
        except Exception:
            if self._interface is not None:
                try:
                    self._interface.close()
                except Exception:
                    pass
                self._interface = None
            self._self_origin.set_own_node_num(None)
            self._channel_keys = {}
            raise

    def _schedule_reconnect(self) -> None:
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.create_task(
            self._reconnect_until_connected(),
            name=f"{self.name}-reconnect",
        )

    async def _reconnect_until_connected(self) -> None:
        delay = _RECONNECT_INITIAL_DELAY_S
        try:
            while self._running and not self.connected:
                await asyncio.sleep(delay)
                if not self._running:
                    return
                try:
                    await asyncio.to_thread(self._open_interface)
                    logger.info(
                        "Serial capture recovered on %s",
                        self._port or "auto-detect",
                    )
                    return
                except ImportError:
                    self._running = False
                    raise
                except Exception:
                    logger.warning(
                        "Serial reconnect still failing on %s; retry in %.0fs",
                        self._port or "auto-detect",
                        min(delay * 2, _RECONNECT_MAX_DELAY_S),
                        exc_info=True,
                    )
                    delay = min(delay * 2, _RECONNECT_MAX_DELAY_S)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Serial reconnect loop error on %s", self.name)

    @property
    def connected(self) -> bool:
        """True while the serial interface is open and capture is running."""
        return self._running and self._interface is not None

    def _config_writer(self):
        if not self.connected:
            return None
        from src.capture.serial_device_config import SerialDeviceConfigWriter

        return SerialDeviceConfigWriter(
            self._interface, self._radio_info, self.name
        )

    def set_region(self, region: str) -> dict:
        writer = self._config_writer()
        if writer is None:
            return {"success": False, "error": "Not connected"}
        return writer.set_region(region)

    def set_modem_preset(self, preset: str) -> dict:
        writer = self._config_writer()
        if writer is None:
            return {"success": False, "error": "Not connected"}
        return writer.set_modem_preset(preset)

    def set_broadcast_intervals(
        self,
        node_info_secs: Optional[int] = None,
        telemetry_secs: Optional[int] = None,
    ) -> dict:
        writer = self._config_writer()
        if writer is None:
            return {"success": False, "error": "Not connected"}
        return writer.set_broadcast_intervals(node_info_secs, telemetry_secs)

    def set_bluetooth(
        self,
        enabled: bool,
        mode: Optional[str] = None,
        fixed_pin: Optional[int] = None,
    ) -> dict:
        writer = self._config_writer()
        if writer is None:
            return {"success": False, "error": "Not connected"}
        return writer.set_bluetooth(enabled, mode, fixed_pin)

    @staticmethod
    def _read_channel_table(
        interface, modem_preset_name: Optional[str] = None
    ) -> dict:
        """Stick channel-table index -> name (for locally decoded packets).

        Firmware ``Channels::getName()`` substitutes the modem preset display
        name (e.g. ``LongFast``) for an empty name on *any* enabled channel,
        including a public secondary behind a private primary.
        """
        from meshtastic.protobuf import channel_pb2

        from src.radio.presets import get_preset

        table: dict[int, str] = {}
        channels = getattr(interface.localNode, "channels", None) or []
        for ch in channels:
            if ch.role == channel_pb2.Channel.Role.DISABLED:
                continue
            name = ch.settings.name
            if not name:
                preset = get_preset(modem_preset_name) if modem_preset_name else None
                name = preset.display_name if preset else (modem_preset_name or "Custom")
            if name:
                table[ch.index] = name
        return table

    @staticmethod
    def _read_channel_key_table(interface) -> dict[int, bytes]:
        """Stick channel index -> firmware-compatible expanded PSK.

        A secondary channel with an empty PSK inherits the primary channel's
        key in the reference firmware. The returned mapping stays private to
        this source and is never included in ``get_radio_info()``.
        """
        from meshtastic.protobuf import channel_pb2

        from src.decode.crypto_service import CryptoService

        channels = getattr(interface.localNode, "channels", None) or []
        primary_index: int | None = None
        primary_psk = b""
        for ch in channels:
            if ch.role == channel_pb2.Channel.Role.PRIMARY:
                primary_index = int(ch.index)
                primary_psk = bytes(getattr(ch.settings, "psk", b"") or b"")
                break

        table: dict[int, bytes] = {}
        for ch in channels:
            if ch.role == channel_pb2.Channel.Role.DISABLED:
                continue
            raw_psk = bytes(getattr(ch.settings, "psk", b"") or b"")
            if (
                not raw_psk
                and ch.role == channel_pb2.Channel.Role.SECONDARY
                and int(ch.index) != primary_index
            ):
                raw_psk = primary_psk
            table[int(ch.index)] = CryptoService._expand_key(raw_psk)
        return table

    def send_text(
        self,
        text: str,
        destination: int | str,
        channel_index: int = 0,
        want_ack: bool = False,
    ) -> dict:
        """Send text via this stick's meshtastic-python interface.

        Returns a plain dict (not ``SendResult``) so capture stays free of
        transmit-layer types. Credit: javastraat/meshpoint ``f6b2bcd``.
        """
        iface = self._interface
        if iface is None or not self.connected:
            return {"success": False, "error": "Not connected", "packet_id": ""}
        try:
            sent = iface.sendText(
                text,
                destinationId=destination,
                wantAck=want_ack,
                channelIndex=channel_index,
            )
            packet_id = (
                f"{sent.id:08x}"
                if sent is not None and hasattr(sent, "id")
                else ""
            )
            logger.info(
                "%s: text message sent (dest=%s, id=%s)",
                self.name,
                destination,
                packet_id or "unknown",
            )
            return {"success": True, "error": "", "packet_id": packet_id}
        except Exception as exc:
            logger.exception("%s: send_text failed", self.name)
            return {"success": False, "error": str(exc), "packet_id": ""}

    def send_traceroute(
        self,
        destination: int | str,
        channel_index: int = 0,
    ) -> dict:
        """Initiate a traceroute through this stick's Meshtastic interface."""
        iface = self._interface
        if iface is None or not self.connected:
            return {"success": False, "error": "Not connected", "packet_id": ""}
        try:
            from meshtastic.protobuf import mesh_pb2, portnums_pb2

            sent = iface.sendData(
                mesh_pb2.RouteDiscovery().SerializeToString(),
                destinationId=destination,
                portNum=portnums_pb2.PortNum.TRACEROUTE_APP,
                wantAck=True,
                wantResponse=True,
                channelIndex=channel_index,
            )
            packet_id = (
                f"{sent.id:08x}"
                if sent is not None and hasattr(sent, "id")
                else ""
            )
            logger.info(
                "%s: traceroute sent (dest=%s, id=%s)",
                self.name,
                destination,
                packet_id or "unknown",
            )
            return {"success": True, "error": "", "packet_id": packet_id}
        except Exception as exc:
            logger.exception("%s: send_traceroute failed", self.name)
            return {"success": False, "error": str(exc), "packet_id": ""}

    async def stop(self) -> None:
        self._running = False
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None
        self._self_origin.set_own_node_num(None)
        self._channel_keys = {}
        if self._interface:
            try:
                self._interface.close()
            except Exception:
                pass
            self._interface = None
        logger.info("Serial capture stopped")

    async def packets(self) -> AsyncIterator[RawCapture]:
        while self._running:
            try:
                raw = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
                yield raw
            except asyncio.TimeoutError:
                continue

    def _on_receive(self, packet, interface) -> None:
        """Callback invoked by meshtastic-python on packet reception.

        meshtastic-python publishes every open interface on one process-wide
        topic, so multi-stick setups must ignore foreign interfaces.
        """
        if not self._running or interface is not self._interface:
            return

        try:
            raw_capture = self._packet_to_raw_capture(packet)
            if raw_capture:
                try:
                    self._queue.put_nowait(raw_capture)
                except asyncio.QueueFull:
                    logger.warning("Serial capture queue full")
        except Exception:
            logger.debug("Failed to convert serial packet", exc_info=True)

    def _packet_to_raw_capture(self, packet: dict) -> Optional[RawCapture]:
        """Convert a meshtastic-python packet dict to a RawCapture."""
        if self._self_origin.should_drop(packet):
            logger.debug(
                "Dropping self-originated non-text packet from own node %08x",
                self._self_origin.own_node_num,
            )
            return None

        raw_bytes = packet.get("raw", b"")
        if isinstance(raw_bytes, str):
            raw_bytes = bytes.fromhex(raw_bytes)
        elif not isinstance(raw_bytes, (bytes, bytearray)):
            # meshtastic-python sets packet["raw"] to the MeshPacket
            # protobuf object, not bytes. Treat as absent so reconstruct runs.
            raw_bytes = b""

        if not raw_bytes:
            # Reconstruct even without "decoded": encrypted/decoded share a
            # oneof, so undecryptable-by-stick traffic has no "decoded" key.
            raw_bytes = self._reconstruct_raw(packet)

        if not raw_bytes:
            return None

        radio = self._radio_info
        # Fall back to LongFast SF/BW only when handshake left them unset.
        bandwidth_khz = radio.get("bandwidth_khz") or 250.0
        signal = SignalMetrics(
            rssi=float(packet.get("rxRssi", packet.get("rssi", -100))),
            snr=float(packet.get("rxSnr", packet.get("snr", 0))),
            frequency_mhz=resolve_frequency_mhz(
                region=radio.get("region"),
                channel_num=radio.get("channel_num"),
                bandwidth_khz=bandwidth_khz,
                channel_name=radio.get("channel_name"),
                modem_preset=radio.get("modem_preset"),
                use_preset=radio.get("use_preset", True),
                frequency_offset=radio.get("frequency_offset") or 0.0,
                override_frequency=radio.get("override_frequency") or 0.0,
            ),
            spreading_factor=radio.get("spreading_factor") or 11,
            bandwidth_khz=float(bandwidth_khz),
        )

        return RawCapture(
            payload=raw_bytes,
            signal=signal,
            capture_source=self.name,
            timestamp=datetime.now(timezone.utc),
            pre_decoded=self._build_pre_decoded(packet),
        )

    def _build_pre_decoded(self, packet: dict) -> Optional[dict]:
        """Portnum + payload when the stick already decrypted locally."""
        decoded = packet.get("decoded")
        if not isinstance(decoded, dict):
            return None
        portnum_name = decoded.get("portnum")
        if portnum_name is None:
            return None
        try:
            if isinstance(portnum_name, int):
                portnum = portnum_name
            else:
                from meshtastic.protobuf import portnums_pb2

                portnum = portnums_pb2.PortNum.Value(portnum_name)
        except (ImportError, ValueError):
            logger.debug("Unrecognized portnum name %r", portnum_name)
            return None

        payload_b64 = decoded.get("payload", "")
        try:
            payload = base64.b64decode(payload_b64) if payload_b64 else b""
        except Exception:
            logger.debug("Could not base64-decode decoded.payload", exc_info=True)
            payload = b""

        result = {
            "portnum": portnum,
            "payload": payload,
            "request_id": decoded.get("requestId", 0),
            "want_response": decoded.get("wantResponse", False),
        }
        channel_idx = packet.get("channel")
        if channel_idx is not None:
            channel_name = self._radio_info.get("channel_table", {}).get(
                channel_idx
            )
            if channel_name:
                result["channel_name"] = channel_name
        return result

    @staticmethod
    def _reconstruct_raw(packet: dict) -> bytes:
        """Build a minimal raw frame from a decoded meshtastic packet.

        When the meshtastic library provides already-decoded data
        without raw bytes, we reconstruct the header so the pipeline
        can process it. The payload portion will be empty/encrypted.
        """
        import struct

        dest = packet.get("to", 0xFFFFFFFF)
        source = packet.get("from", 0)
        pkt_id = packet.get("id", 0)

        hop_limit = packet.get("hopLimit", 3)
        hop_start = packet.get("hopStart", 3)
        want_ack = packet.get("wantAck", False)

        flags = (hop_limit & 0x07)
        if want_ack:
            flags |= 0x08
        flags |= (hop_start & 0x07) << 5

        channel = packet.get("channel", 0)

        header = struct.pack("<III", dest, source, pkt_id)
        header += bytes([flags, channel, 0, 0])

        # MessageToDict base64-encodes the MeshPacket "encrypted" field.
        encoded = packet.get("encrypted", b"")
        if isinstance(encoded, str):
            encoded = base64.b64decode(encoded)

        return header + encoded
