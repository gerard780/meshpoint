"""Emergency pager project: ch9 (FSK) message inbox/outbox and send.

Not to be confused with pager_routes.py (RTL-SDR P2000/Pagers/POCSAG
decoder endpoints, /api/p2000, /api/pagers, /api/pocsag) -- an
unrelated, pre-existing feature that happens to share the word "pager".
This file is the concentrator's own dedicated FSK channel (ch9),
prefixed /api/pager (singular, distinct from that plural /api/pagers).

Still internal/experimental -- there is no real Heltec V3 firmware or
over-the-air protocol yet. Received and sent frames are both treated as
plain UTF-8 text with no envelope (see pager_event_adapter.py), stored
in the shared ``packets`` table like DAPNET's pages (no ``messages``
row -- same reasoning as DAPNET: this isn't a mesh conversation, just a
one-way-at-a-time broadcast log). Inbox/Outbox are split by
``capture_source`` ("pager" for received, "pager_tx" for sent) since,
unlike DAPNET's serial companion, sending here does not echo the sent
frame back into the normal receive path -- there is no over-the-air
loopback, so a sent message would simply never appear anywhere unless
this route inserts its own row for it.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims
from src.config import AppConfig
from src.models.packet import Packet, PacketType, Protocol
from src.storage.packet_repository import PacketRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pager", tags=["pager"])

_packet_repo: PacketRepository | None = None
_concentrator_source = None
_config: AppConfig | None = None

_CAPTURE_SOURCE_BY_DIRECTION = {"in": "pager", "out": "pager_tx"}


def init_routes(
    packet_repo: PacketRepository,
    concentrator_source,
    config: AppConfig,
) -> None:
    global _packet_repo, _concentrator_source, _config
    _packet_repo = packet_repo
    _concentrator_source = concentrator_source
    _config = config


def _decode_text(row: dict) -> str:
    raw = row.get("decoded_payload")
    if not raw:
        return ""
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return ""
    return payload.get("text", "") if isinstance(payload, dict) else ""


@router.get("/status")
async def pager_status():
    """Config + live state for the sidebar/topbar gating and the page header."""
    if _config is None:
        raise HTTPException(503, "Routes not initialised")
    radio = _config.radio
    return {
        "pager_enabled": radio.pager_enabled,
        "pager_frequency_mhz": radio.pager_frequency_mhz,
        "concentrator_available": _concentrator_source is not None,
    }


@router.get("/messages")
async def pager_messages(
    direction: str = Query("in", pattern="^(in|out)$"),
    limit: int = Query(100, ge=1, le=1000),
):
    """Inbox (direction=in) or Outbox (direction=out), newest first."""
    if _packet_repo is None:
        raise HTTPException(503, "Routes not initialised")

    capture_source = _CAPTURE_SOURCE_BY_DIRECTION[direction]
    rows = await _packet_repo._db.fetch_all(
        """
        SELECT packet_id, source_id, destination_id, packet_type,
               capture_source, timestamp, decoded_payload, decrypted,
               rssi, snr, frequency_mhz
        FROM packets
        WHERE protocol = 'pager' AND capture_source = ?
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (capture_source, limit),
    )

    return [
        {
            "packet_id": row.get("packet_id"),
            "direction": direction,
            "text": _decode_text(row),
            "timestamp": row["timestamp"],
            "rssi": row.get("rssi"),
            "snr": row.get("snr"),
            "frequency_mhz": row.get("frequency_mhz"),
            # Included so the frontend's PacketDetailModal (row-click detail
            # popup) has real data to show rather than needing to guess/
            # synthesize From/To/capture_source client-side.
            "protocol": "pager",
            "source_id": row.get("source_id"),
            "destination_id": row.get("destination_id"),
            "packet_type": row.get("packet_type"),
            "capture_source": row.get("capture_source"),
            "decrypted": bool(row.get("decrypted")),
        }
        for row in rows
    ]


class PagerSendRequest(BaseModel):
    text: str


@router.post("/send")
async def send_pager_message(
    req: PagerSendRequest,
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Transmit one message on the pager's FSK channel (ch9).

    Unlike DAPNET's serial companion, this is a direct, synchronous HAL
    call (``send_fsk_packet``) with no device round-trip -- a successful
    response here means the concentrator hardware accepted and queued
    the transmission, NOT that any device received it. There is no ACK
    scheme yet (a real one may be possible once real pager firmware
    exists), so the stored Outbox row's ``status`` is just ``"sent"``
    for now -- a placeholder for a future ``"acked"`` once that's real.
    """
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "Message text required")

    if _concentrator_source is None:
        raise HTTPException(503, "Concentrator not available")
    if not _concentrator_source._pager_enabled:
        raise HTTPException(503, "Pager channel (ch9) is not enabled")

    payload = text.encode("utf-8")
    try:
        result = _concentrator_source._wrapper.send_fsk_packet(
            payload=payload,
            frequency_hz=_concentrator_source._pager_frequency_hz,
            rf_power_dbm=_config.transmit.tx_power_dbm if _config else 14,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if result != 0:
        raise HTTPException(502, f"Concentrator rejected the transmission (code {result})")

    await _packet_repo.insert(
        Packet(
            packet_id=uuid.uuid4().hex[:16],
            source_id="meshpoint",
            destination_id="broadcast",
            protocol=Protocol.PAGER,
            packet_type=PacketType.PAGER_RAW,
            decoded_payload={"text": text, "status": "sent"},
            decrypted=True,
            capture_source="pager_tx",
            timestamp=datetime.now(timezone.utc),
        )
    )

    return {"sent": True}
