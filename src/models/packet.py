from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from src.models.signal import SignalMetrics


class Protocol(str, Enum):
    MESHTASTIC = "meshtastic"
    MESHCORE = "meshcore"
    LORAWAN = "lorawan"
    DAPNET = "dapnet"
    PAGER = "pager"
    # ch0-ch7 of the concentrator's eu868_reticulum() band plan (see
    # concentrator_config.py) -- honest protocol_hint for that traffic
    # instead of the pre-band-plan default of LORAWAN. No real decoder
    # exists yet (see packet_router.py's explicit reject for this hint,
    # and src/decode/ -- there is no reticulum_decoder.py); this exists
    # so Stray Frames entries are labeled accurately, not to claim
    # decoding capability that doesn't exist.
    RETICULUM = "reticulum"
    # ch2 of eu868_reticulum() ("LoRa Pager", 869.155 MHz) -- one of the
    # plan's spare channels, given its own hint (rather than the generic
    # RETICULUM one every other spare channel still gets) because it has
    # its own dedicated adapter now (lora_pager_event_adapter.py). Not
    # the same thing as PAGER (ch9, real POCSAG/FSK hardware) -- this is
    # a LoRa-modulated experimental channel with its own simple
    # JSON test payload, see that adapter's own docstring.
    LORA_PAGER = "lora_pager"
    UNKNOWN = "unknown"


class PacketType(str, Enum):
    TEXT = "text"
    POSITION = "position"
    TELEMETRY = "telemetry"
    NODEINFO = "nodeinfo"
    ROUTING = "routing"
    ADMIN = "admin"
    TRACEROUTE = "traceroute"
    NEIGHBORINFO = "neighborinfo"
    WAYPOINT = "waypoint"
    RANGE_TEST = "range_test"
    STORE_FORWARD = "store_forward"
    DETECTION_SENSOR = "detection_sensor"
    PAXCOUNTER = "paxcounter"
    MAP_REPORT = "map_report"
    ENCRYPTED = "encrypted"
    LORAWAN_JOIN = "lorawan_join"
    LORAWAN_DATA = "lorawan_data"
    LORAWAN_REJOIN = "lorawan_rejoin"
    NEIGHBOUR_ADVERT = "neighbour_advert"
    DAPNET_ALPHA = "dapnet_alpha"
    DAPNET_NUMERIC = "dapnet_numeric"
    DAPNET_TONE = "dapnet_tone"
    DAPNET_ACTIVATION = "dapnet_activation"
    # Raw, undecoded bytes from the emergency pager project's own FSK
    # channel (ch9) -- the over-the-air framing isn't designed yet (no
    # Heltec V3 firmware exists to produce it), so a page currently gets
    # stored as opaque payload rather than a real decoded shape. Exists
    # to prove the concentrator is actually receiving something on this
    # channel before a real protocol/decoder is built.
    PAGER_RAW = "pager_raw"
    # heltec_lora_pager_test.ino's diagnostic payload on ch2 ("LoRa
    # Pager") -- no real over-the-air protocol designed yet for this
    # channel either, same "prove reception works first" spirit as
    # PAGER_RAW above, just LoRa-modulated instead of FSK.
    LORA_PAGER_TEST = "lora_pager_test"
    UNKNOWN = "unknown"


@dataclass
class RawCapture:
    """A raw LoRa frame as received from the capture source."""

    payload: bytes
    signal: SignalMetrics
    capture_source: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    protocol_hint: Optional[Protocol] = None
    # Set only by sources whose upstream library decrypts locally before
    # handing us the packet (meshtastic-python's serial capture): the
    # portnum (int) and inner Data payload (bytes) it already parsed.
    # `encrypted`/`decoded` share one protobuf oneof on MeshPacket, so
    # when this is set, `payload` above is a header-only reconstruction
    # with no ciphertext to decrypt -- the decoder uses this instead of
    # running its own crypto_service pass.
    pre_decoded: Optional[dict] = None


@dataclass
class Packet:
    """A fully decoded mesh packet with metadata."""

    packet_id: str
    source_id: str
    destination_id: str
    protocol: Protocol
    packet_type: PacketType

    hop_limit: int = 0
    hop_start: int = 0
    channel_hash: int = 0
    want_ack: bool = False
    via_mqtt: bool = False
    relay_node: int = 0

    decoded_payload: Optional[dict[str, Any]] = None
    encrypted_payload: Optional[bytes] = None
    # Inner application-payload bytes from the decrypted protobuf (the
    # bytes that follow `portnum` in a Meshtastic Data message). Used
    # by the legacy USB-companion relay path that calls
    # `interface.sendData(payload, portNum=…)`.
    raw_app_payload: Optional[bytes] = None
    # The full original radio frame as captured (16-byte Meshtastic
    # header + encrypted body). Used by the native relay path to
    # re-emit the packet verbatim through the onboard SX1302 with
    # only the hop_limit decremented, preserving the original
    # source_id and packet_id so other nodes' dedup treats it as a
    # legitimate relay rather than a fresh broadcast.
    raw_radio_packet: Optional[bytes] = None
    decrypted: bool = False
    # Index into crypto.get_all_keys() (0=primary, 1+=channel_keys in
    # insertion order) of the key that actually decrypted this packet.
    # Set even when channel_hash doesn't match any locally-computed
    # hash for that key -- i.e. the remote side named the channel
    # differently but shares the same PSK. Lets a reply be encrypted
    # with the right key and stamped with the original hash instead of
    # one recomputed from our own channel name (see tx_service
    # echo_hash).
    matched_channel_index: Optional[int] = None
    # Channel name reported by a capture source that decoded this
    # packet locally using its OWN channel table (e.g. a Meshtastic
    # USB stick) rather than Meshpoint's own crypto_service pass. The
    # source's local channel INDEX has no relationship to Meshpoint's
    # own channel numbering or to the real over-the-air channel_hash,
    # so it must never be treated as either -- routing by this name
    # instead is the only thing that's actually meaningful here (see
    # SerialCaptureSource._build_pre_decoded / F1 in the worklist).
    remote_channel_name: Optional[str] = None

    signal: Optional[SignalMetrics] = None
    capture_source: str = "unknown"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def hop_count(self) -> int:
        if self.hop_start > 0:
            return self.hop_start - self.hop_limit
        return 0

    def to_dict(self) -> dict:
        result = {
            "packet_id": self.packet_id,
            "source_id": self.source_id,
            "destination_id": self.destination_id,
            "protocol": self.protocol.value,
            "packet_type": self.packet_type.value,
            "hop_limit": self.hop_limit,
            "hop_start": self.hop_start,
            "hop_count": self.hop_count,
            "channel_hash": self.channel_hash,
            "want_ack": self.want_ack,
            "via_mqtt": self.via_mqtt,
            "relay_node": self.relay_node,
            "decoded_payload": self.decoded_payload,
            "decrypted": self.decrypted,
            "capture_source": self.capture_source,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.signal:
            result["signal"] = self.signal.to_dict()
        return result
