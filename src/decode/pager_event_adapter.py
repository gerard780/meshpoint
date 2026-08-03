"""Convert raw FSK captures from the concentrator's pager channel (ch9)
into placeholder Packet objects.

There is no real over-the-air framing yet -- the emergency pager project's
Heltec V3 firmware doesn't exist. Anything arriving on this dedicated,
isolated FSK channel (its own frequency and sync word, confirmed
independent of every LoRa channel this concentrator also runs) is
presumed pager-project traffic and stored raw so it's visible in the
Messages/Packets views, proving reception works before a real protocol
is designed on top of it.
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
    """Wrap one raw FSK frame as an undecoded pager Packet.

    Unlike DAPNET's serial-companion adapter, real RF signal metrics ARE
    available here (the concentrator itself received this frame), so
    ``signal`` is stored rather than discarded.
    """
    if not raw_payload:
        return None
    return Packet(
        packet_id=uuid.uuid4().hex[:16],
        source_id="unknown",
        destination_id="broadcast",
        protocol=Protocol.PAGER,
        packet_type=PacketType.PAGER_RAW,
        encrypted_payload=raw_payload,
        decrypted=False,
        signal=signal,
    )
