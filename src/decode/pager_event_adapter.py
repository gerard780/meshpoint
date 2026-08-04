"""Convert raw FSK captures from the concentrator's pager channel (ch9)
into Packet objects.

Real over-the-air protocol, JSON-encoded (same convention as
extra/pocsag_companion's own serial protocol -- {"capcode":...,"text":...} --
reused deliberately rather than a hand-rolled binary layout, since it's
self-describing/extensible and ArduinoJson is already a pager_client.ino
dependency): one JSON object per frame, either a real message --
``{"from": <capcode>, "to": <capcode>, "text": "<message>", "id":
"<5-hex-char id>"}`` -- or an ACK reply to one -- ``{"from": <capcode>,
"to": <capcode>, "ack_id": "<the id being acknowledged>"}`` (no "text").
``from``/``to`` are POCSAG-style capcodes (plain integers -- a device's
own personal number, or a shared address like 911 multiple pagers listen
on for broadcasts) -- see project memory for the addressing design
discussion, and the ACK round-trip's own design discussion for the id
format: 16 hex chars, same as every other protocol's packet_id in this
app (a shorter id was considered for the few extra bytes of airtime it'd
save, but rejected -- the saving is negligible at 4.8kbps and a shorter
id would just look visually inconsistent next to every other protocol's
packet_id in the same packet detail popup).

For an ACK frame, ``packet_id`` on the returned Packet is deliberately
set to the id being acknowledged, not a freshly generated one -- lets
coordinator.py match it straight back to the original Outbox row with a
plain packet_id lookup (PacketRepository.update_pager_status()), no
separate id-to-packet_id mapping needed. For a real message,
``packet_id`` is the message's own "id" field if present (so a reply ACK
sent later can be matched the same way), falling back to a fresh
uuid.uuid4().hex[:16] only when it's missing (older firmware, or foreign
noise on the channel that happened to parse as valid JSON).
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
    """Decode one JSON-encoded pager frame (message or ACK) into a Packet.

    Unlike DAPNET's serial-companion adapter, real RF signal metrics ARE
    available here (the concentrator itself received this frame), so
    ``signal`` is stored rather than discarded.

    Returns ``None`` for anything that isn't a valid JSON object with
    either a "text" or an "ack_id" field (malformed/foreign noise on the
    channel) -- same "fails to parse, falls back to the stray-frame log"
    reasoning as dapnet_event_adapter.py's own non-JSON-line guard.
    """
    try:
        data = json.loads(raw_payload)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    from_capcode = data.get("from")
    to_capcode = data.get("to")
    source_id = str(from_capcode) if from_capcode is not None else "unknown"
    destination_id = str(to_capcode) if to_capcode is not None else "broadcast"

    if "ack_id" in data:
        ack_id = str(data["ack_id"])
        return Packet(
            packet_id=ack_id,
            source_id=source_id,
            destination_id=destination_id,
            protocol=Protocol.PAGER,
            packet_type=PacketType.PAGER_RAW,
            decoded_payload={"from": from_capcode, "to": to_capcode, "ack_id": ack_id},
            decrypted=True,
            signal=signal,
        )

    if "text" not in data:
        return None

    text = str(data.get("text", ""))
    msg_id = str(data["id"]) if data.get("id") is not None else uuid.uuid4().hex[:16]

    return Packet(
        packet_id=msg_id,
        source_id=source_id,
        destination_id=destination_id,
        protocol=Protocol.PAGER,
        packet_type=PacketType.PAGER_RAW,
        decoded_payload={"from": from_capcode, "to": to_capcode, "text": text, "id": msg_id},
        decrypted=True,
        signal=signal,
    )
