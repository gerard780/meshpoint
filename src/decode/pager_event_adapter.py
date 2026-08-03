"""Convert raw FSK captures from the concentrator's pager channel (ch9)
into Packet objects.

Real over-the-air protocol, JSON-encoded (same convention as
extra/pocsag_companion's own serial protocol -- {"capcode":...,"text":...} --
reused deliberately rather than a hand-rolled binary layout, since it's
self-describing/extensible and ArduinoJson is already a pager_client.ino
dependency): one JSON object per frame, ``{"from": <capcode>, "to":
<capcode>, "text": "<message>"}``. ``from``/``to`` are POCSAG-style
capcodes (plain integers, e.g. this fork's own 2041152, or a shared
address like 911 multiple pagers listen on for broadcasts) -- see
project memory for the addressing design discussion.
"""

from __future__ import annotations

import json
import uuid
from typing import Optional

from src.models.packet import Packet, PacketType, Protocol
from src.models.signal import SignalMetrics


def adapt_event(
    raw_payload: bytes,
    signal: Optional[SignalMetrics] = None,
) -> Optional[Packet]:
    """Decode one JSON-encoded pager frame into a Packet.

    Unlike DAPNET's serial-companion adapter, real RF signal metrics ARE
    available here (the concentrator itself received this frame), so
    ``signal`` is stored rather than discarded.

    Returns ``None`` for anything that isn't a valid ``{"from","to",
    "text"}`` JSON object (malformed/foreign noise on the channel) --
    same "fails to parse, falls back to the stray-frame log" reasoning
    as dapnet_event_adapter.py's own non-JSON-line guard.
    """
    try:
        data = json.loads(raw_payload)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or "text" not in data:
        return None

    from_capcode = data.get("from")
    to_capcode = data.get("to")
    text = str(data.get("text", ""))

    return Packet(
        packet_id=uuid.uuid4().hex[:16],
        source_id=str(from_capcode) if from_capcode is not None else "unknown",
        destination_id=str(to_capcode) if to_capcode is not None else "broadcast",
        protocol=Protocol.PAGER,
        packet_type=PacketType.PAGER_RAW,
        decoded_payload={"from": from_capcode, "to": to_capcode, "text": text},
        decrypted=True,
        signal=signal,
    )
