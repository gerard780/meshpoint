"""Convert raw LoRa captures from the concentrator's ch2 ("LoRa Pager",
869.155 MHz -- one of eu868_reticulum()'s spare channels) into Packet
objects.

No real over-the-air protocol exists for this channel yet -- the only
thing that currently transmits on it is extra/heltec_lora_pager_test.ino,
a diagnostic tool with a fixed JSON payload:
``{"test": true, "channel": <int>, "name": "<str>", "count": <int>}``.
This adapter exists to prove that payload actually round-trips end to
end (received -> decoded -> stored -> shown), the same "prove reception
works before designing the real protocol" spirit as PAGER_RAW on ch9.

Deliberately its own file/Protocol/adapter rather than reusing
pager_event_adapter.py or Protocol.PAGER: ch9 is real POCSAG/FSK
hardware with its own capcode/ACK semantics baked into coordinator.py's
_process_capture(); this is a LoRa-modulated experimental channel with
an unrelated payload shape. Each spare channel (Chat/Public/Data/
Weather/Alert/Emergency) is expected to eventually get its own adapter
file the same way, once it has something real of its own to decode --
copy this file as the starting point, not the shared generic path.
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
    """Decode one JSON test frame from ch2 ("LoRa Pager") into a Packet.

    Returns ``None`` for anything that isn't a valid JSON object with
    ``"test": true`` (malformed/foreign noise on the channel) -- same
    "fails to parse, falls back to the stray-frame log" reasoning as
    pager_event_adapter.py's own guard.
    """
    try:
        data = json.loads(raw_payload)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("test") is not True:
        return None

    channel_idx = data.get("channel")
    name = str(data.get("name", "")) or "LoRa Pager"
    count = data.get("count")

    # No sender identity exists in this payload at all (the test tool
    # never sends one) -- "test-tx" is a fixed placeholder, not a real
    # device id, same idea as pager_event_adapter.py's "unknown"
    # fallback when a real from/to capcode is missing.
    return Packet(
        packet_id=uuid.uuid4().hex[:16],
        source_id="test-tx",
        destination_id="broadcast",
        protocol=Protocol.LORA_PAGER,
        packet_type=PacketType.LORA_PAGER_TEST,
        decoded_payload={"channel": channel_idx, "name": name, "count": count},
        decrypted=True,
        signal=signal,
    )
