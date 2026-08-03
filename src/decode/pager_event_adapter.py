"""Convert raw FSK captures from the concentrator's pager channel (ch9)
into placeholder-text Packet objects.

There is no real over-the-air framing yet -- the emergency pager
project's Heltec V3 firmware doesn't exist. Until a real protocol is
designed, anything arriving on this dedicated, isolated FSK channel
(its own frequency and sync word, confirmed independent of every LoRa
channel this concentrator also runs) is treated as plain UTF-8 text
with no envelope -- decoded best-effort (replacing anything that isn't
valid UTF-8) so the Pager page's Inbox has something readable to show,
not just a hex dump.
"""

from __future__ import annotations

import uuid
from typing import Optional

from src.models.packet import Packet, PacketType, Protocol
from src.models.signal import SignalMetrics


def adapt_event(
    raw_payload: bytes,
    signal: Optional[SignalMetrics] = None,
) -> Optional[Packet]:
    """Wrap one raw FSK frame as a placeholder-text pager Packet.

    Unlike DAPNET's serial-companion adapter, real RF signal metrics ARE
    available here (the concentrator itself received this frame), so
    ``signal`` is stored rather than discarded.
    """
    if not raw_payload:
        return None
    text = raw_payload.decode("utf-8", errors="replace")
    return Packet(
        packet_id=uuid.uuid4().hex[:16],
        source_id="unknown",
        destination_id="broadcast",
        protocol=Protocol.PAGER,
        packet_type=PacketType.PAGER_RAW,
        decoded_payload={"text": text},
        decrypted=True,
        signal=signal,
    )
