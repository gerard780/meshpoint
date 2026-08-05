"""Emergency pager project: ch9 (FSK) message inbox/outbox and send.

Not to be confused with pager_routes.py (RTL-SDR P2000/Pagers/POCSAG
decoder endpoints, /api/p2000, /api/pagers, /api/pocsag) -- an
unrelated, pre-existing feature that happens to share the word "pager".
This file is the concentrator's own dedicated FSK channel (ch9),
prefixed /api/pager (singular, distinct from that plural /api/pagers).

Still internal/experimental, but confirmed working end-to-end on real
hardware (extra/pager_client.ino, a Heltec V3) as of 2026-08. Every frame
is a JSON envelope -- a real message, ``{"from": <capcode>, "to":
<capcode>, "text": "...", "id": "<16-hex-char id>"}``, or that message's
ACK reply, ``{"from": <capcode>, "to": <capcode>, "ack_id": "<the id
being acked>"}`` (no "text") -- see pager_event_adapter.py, same JSON
convention as extra/pocsag_companion's own serial protocol, reused
deliberately. ``from``/``to`` are plain POCSAG-style capcodes (e.g. this
fork's own real DAPNET capcode, or a shared address like 911 multiple
pagers listen on for broadcasts). Stored in the shared ``packets`` table
like DAPNET's pages (no ``messages`` row -- this isn't a mesh
conversation, just a one-way-at-a-time broadcast log) -- an ACK never
gets its own row though, it only ever updates the ``status`` field
inside the original Outbox row's ``decoded_payload`` (see coordinator.py
and PacketRepository.update_pager_status()).

``capture_source`` for every pager packet (sent or received) is
"concentrator", same as Meshtastic/LoRaWAN -- ch9 is a different IF
chain/channel on the SAME concentrator hardware, not a different
device, so tagging it differently would mislead the dashboard's
"Source" display (a real bug, caught live, fixed before this capcode
work). Inbox/Outbox are split by ``source_id`` (this device's own
configured ``radio.pager_capcode``, stringified, for sent; anything
else for received) -- unlike DAPNET's serial companion, sending here
does not echo the sent frame back into the normal receive path, so a
sent message would simply never appear anywhere unless this route
inserts its own row for it. A received message whose "from" matches
our own capcode (the concentrator's own TX leaking straight back into
its own RX -- confirmed live, near-field self-coupling) is dropped
entirely before it ever reaches here (see coordinator.py's
_process_capture), so no separate self-echo filter is needed on the
read side.
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


def init_routes(
    packet_repo: PacketRepository,
    concentrator_source,
    config: AppConfig,
) -> None:
    global _packet_repo, _concentrator_source, _config
    _packet_repo = packet_repo
    _concentrator_source = concentrator_source
    _config = config


def _decode_payload(row: dict) -> dict:
    raw = row.get("decoded_payload")
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


@router.get("/status")
async def pager_status():
    """Config + live state for the sidebar/topbar gating and the page header."""
    if _config is None:
        raise HTTPException(503, "Routes not initialised")
    radio = _config.radio
    return {
        "pager_enabled": radio.pager_enabled,
        "pager_frequency_mhz": radio.pager_frequency_mhz,
        "pager_capcode": radio.pager_capcode or None,
        "concentrator_available": _concentrator_source is not None,
    }


@router.get("/messages")
async def pager_messages(
    direction: str = Query("in", pattern="^(in|out)$"),
    limit: int = Query(100, ge=1, le=1000),
):
    """Inbox (direction=in) or Outbox (direction=out), newest first."""
    if _packet_repo is None or _config is None:
        raise HTTPException(503, "Routes not initialised")

    our_capcode = str(_config.radio.pager_capcode)
    # Operator choice (=/!=) comes from the validated `direction` path param
    # (Query's own pattern already restricts it to "in"/"out"), never from
    # raw user input -- only the source_id VALUE is parameterized below.
    op = "=" if direction == "out" else "!="
    rows = await _packet_repo._db.fetch_all(
        f"""
        SELECT packet_id, source_id, destination_id, packet_type,
               capture_source, timestamp, decoded_payload, decrypted,
               rssi, snr, frequency_mhz
        FROM packets
        WHERE protocol = 'pager' AND source_id {op} ?
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (our_capcode, limit),
    )

    result = []
    for row in rows:
        payload = _decode_payload(row)
        result.append({
            "packet_id": row.get("packet_id"),
            "direction": direction,
            "from_capcode": row.get("source_id"),
            "to_capcode": row.get("destination_id"),
            "text": payload.get("text", ""),
            # "sent" until a real ACK from the pager flips it to "acked"
            # (PacketRepository.update_pager_status(), via coordinator.py's
            # ack-matching branch) -- only ever meaningful for Outbox rows,
            # but included either way rather than direction-gating it.
            "status": payload.get("status"),
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
        })
    return result


@router.get("/stats")
async def pager_stats():
    """Aggregate counts for the page's stat tiles.

    ``acked``/``pending`` only ever count Outbox rows (status lives in
    ``decoded_payload``, same as ``pager_messages`` above, decoded in
    Python rather than via SQL JSON functions -- no other route in this
    codebase queries JSON at the SQL level, so this stays consistent
    with the rest of the app instead of introducing a one-off pattern).
    """
    if _packet_repo is None or _config is None:
        raise HTTPException(503, "Routes not initialised")

    totals = await _packet_repo._db.fetch_one(
        "SELECT COUNT(*) AS total FROM packets WHERE protocol = 'pager'"
    )
    capcode_rows = await _packet_repo._db.fetch_all(
        "SELECT DISTINCT source_id, destination_id FROM packets WHERE protocol = 'pager'"
    )
    unique_capcodes = {r["source_id"] for r in capcode_rows} | {
        r["destination_id"] for r in capcode_rows
    }
    unique_capcodes.discard(None)
    unique_capcodes.discard("")

    our_capcode = str(_config.radio.pager_capcode)
    outbox_rows = await _packet_repo._db.fetch_all(
        "SELECT decoded_payload FROM packets WHERE protocol = 'pager' AND source_id = ?",
        (our_capcode,),
    )
    acked = sum(1 for row in outbox_rows if _decode_payload(row).get("status") == "acked")
    pending = len(outbox_rows) - acked

    return {
        "total_messages": totals["total"] if totals else 0,
        "unique_capcodes": len(unique_capcodes),
        "acked": acked,
        "pending": pending,
    }


_INBOX_EXPORT_COLUMNS = [
    "timestamp", "packet_id", "from_capcode", "to_capcode", "text", "rssi", "snr",
]
_OUTBOX_EXPORT_COLUMNS = [
    "timestamp", "packet_id", "from_capcode", "to_capcode", "text", "status",
]


def _pager_flatten(row: dict) -> dict:
    payload = _decode_payload(row)
    row["from_capcode"] = row.get("source_id")
    row["to_capcode"] = row.get("destination_id")
    row["text"] = payload.get("text", "")
    row["status"] = payload.get("status")
    return row


@router.get("/export/inbox.csv")
async def pager_inbox_csv():
    """All received pager messages as a downloadable CSV."""
    if _packet_repo is None or _config is None:
        raise HTTPException(503, "Routes not initialised")
    from src.api.csv_export import export_filename, streaming_csv, stream_query

    our_capcode = str(_config.radio.pager_capcode)
    device_name = _config.device.device_name or "meshpoint"
    rows = stream_query(
        _packet_repo._db,
        """
        SELECT packet_id, source_id, destination_id, timestamp,
               decoded_payload, rssi, snr
        FROM packets
        WHERE protocol = 'pager' AND source_id != ?
        ORDER BY timestamp DESC
        """,
        (our_capcode,),
        _INBOX_EXPORT_COLUMNS,
        transform=_pager_flatten,
    )
    return streaming_csv(
        _INBOX_EXPORT_COLUMNS, rows,
        export_filename(device_name, "pager-inbox"),
    )


@router.get("/export/outbox.csv")
async def pager_outbox_csv():
    """All sent pager messages (with delivery status) as a downloadable CSV."""
    if _packet_repo is None or _config is None:
        raise HTTPException(503, "Routes not initialised")
    from src.api.csv_export import export_filename, streaming_csv, stream_query

    our_capcode = str(_config.radio.pager_capcode)
    device_name = _config.device.device_name or "meshpoint"
    rows = stream_query(
        _packet_repo._db,
        """
        SELECT packet_id, source_id, destination_id, timestamp,
               decoded_payload, rssi, snr
        FROM packets
        WHERE protocol = 'pager' AND source_id = ?
        ORDER BY timestamp DESC
        """,
        (our_capcode,),
        _OUTBOX_EXPORT_COLUMNS,
        transform=_pager_flatten,
    )
    return streaming_csv(
        _OUTBOX_EXPORT_COLUMNS, rows,
        export_filename(device_name, "pager-outbox"),
    )


class PagerSendRequest(BaseModel):
    to_capcode: int
    text: str


@router.post("/send")
async def send_pager_message(
    req: PagerSendRequest,
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Transmit one message on the pager's FSK channel (ch9).

    Unlike DAPNET's serial companion, this is a direct, synchronous HAL
    call (``send_fsk_packet``) with no device round-trip -- a successful
    response here only ever means the concentrator hardware accepted and
    queued the transmission, NOT that any device received it. The stored
    Outbox row's ``status`` starts as ``"sent"`` and flips to ``"acked"``
    if/when the pager firmware replies with an ACK envelope carrying this
    message's own ``id`` (see pager_event_adapter.py's "ack_id" handling
    and coordinator.py's ack-matching branch, PacketRepository.
    update_pager_status()) -- a real, if best-effort, delivery
    confirmation, not just a placeholder for one anymore.

    Refuses to transmit without a configured ``radio.pager_capcode`` --
    same "identify yourself before you key up" reasoning as
    pocsag_companion.ino requiring a callsign, and it's also the only
    thing that makes the self-echo filter (coordinator.py) and the
    Inbox/Outbox split (above) meaningful at all.
    """
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "Message text required")

    if _concentrator_source is None:
        raise HTTPException(503, "Concentrator not available")
    if not _concentrator_source._pager_enabled:
        raise HTTPException(503, "Pager channel (ch9) is not enabled")
    if _config is None or not _config.radio.pager_capcode:
        raise HTTPException(
            400,
            "No pager capcode configured -- set one in Configuration -> "
            "Radio (Pager) first",
        )

    our_capcode = _config.radio.pager_capcode
    # Same id ends up as this Outbox row's own packet_id below -- lets a
    # later ACK from the pager (see pager_event_adapter.py's own "ack_id"
    # handling and coordinator.py's ack-matching branch) find this exact
    # row with a plain packet_id lookup, no separate mapping needed.
    msg_id = uuid.uuid4().hex[:16]
    envelope = json.dumps({
        "from": our_capcode, "to": req.to_capcode, "text": text, "id": msg_id,
    })
    payload = envelope.encode("utf-8")
    try:
        result = _concentrator_source._wrapper.send_fsk_packet(
            payload=payload,
            frequency_hz=_concentrator_source._pager_frequency_hz,
            rf_power_dbm=_config.transmit.tx_power_dbm,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if result != 0:
        raise HTTPException(502, f"Concentrator rejected the transmission (code {result})")

    await _packet_repo.insert(
        Packet(
            packet_id=msg_id,
            source_id=str(our_capcode),
            destination_id=str(req.to_capcode),
            protocol=Protocol.PAGER,
            packet_type=PacketType.PAGER_RAW,
            decoded_payload={
                "from": our_capcode, "to": req.to_capcode,
                "text": text, "id": msg_id, "status": "sent",
            },
            decrypted=True,
            capture_source="concentrator",
            timestamp=datetime.now(timezone.utc),
        )
    )

    return {"sent": True}
