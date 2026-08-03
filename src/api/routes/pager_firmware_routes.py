"""Compile and flash extra/pager_client firmware from the dashboard.

Same mechanism as pocsag_firmware_routes.py (wraps ``arduino-cli``, streamed
to the browser as NDJSON), simplified in two ways since pager_client is a
much simpler sketch:

- **Single board only.** pager_client.ino has no ``BOARD_*`` toggle at all
  (Heltec V3 exclusively, per the sketch's own header comment) -- no board
  pulldown, no ``_select_board_define()``/``_discover_board_targets()``
  machinery to mirror from pocsag_firmware_routes.py.
- **No companion device to release/reconnect.** pager_client talks directly
  over the air to the concentrator's ch9 -- it has no USB-serial link to
  Meshpoint at all, unlike a configured POCSAG/MeshCore/Meshtastic companion,
  so flashing here never needs to pause/resume a live capture source first.

``_ndjson``/``_stream_subprocess`` are duplicated from pocsag_firmware_routes.py
rather than shared -- matches the existing convention (dab_routes.py,
meshcore_firmware_routes.py, and meshtastic_firmware_routes.py each keep
their own copy too), not a new pattern introduced here.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.api.audit import AuditLogWriter
from src.api.audit.dependencies import get_audit_writer
from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pager/firmware", tags=["config", "pager"])

_SKETCH_DIR = Path(__file__).resolve().parents[3] / "extra" / "pager_client"
_ARDUINO_CLI_BIN = "arduino-cli"
_ARDUINO_CLI_CONFIG = "/opt/arduino-cli/arduino-cli.yaml"
_FQBN = "esp32:esp32:heltec_wifi_lora_32_V3"
_BOARD_LABEL = "Heltec V3"


def _ndjson(payload: dict) -> bytes:
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")


async def _stream_subprocess(cmd: list[str]) -> AsyncIterator[bytes]:
    """Run ``cmd``, yielding one NDJSON line per stdout/stderr line as it
    arrives, then a final ``{"type":"result",...}``. Identical shape to
    pocsag_firmware_routes.py's own copy."""
    yield _ndjson({"type": "started", "cmd": cmd})
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, OSError) as exc:
        yield _ndjson({
            "type": "result",
            "result": {"returncode": -1, "success": False, "error": str(exc)},
        })
        return

    queue: asyncio.Queue = asyncio.Queue()

    async def pump(stream: Optional[asyncio.StreamReader], name: str) -> None:
        if stream is not None:
            while True:
                line = await stream.readline()
                if not line:
                    break
                await queue.put({
                    "type": "line", "stream": name,
                    "text": line.decode("utf-8", errors="replace").rstrip("\n"),
                })
        await queue.put(None)

    stdout_task = asyncio.create_task(pump(process.stdout, "stdout"))
    stderr_task = asyncio.create_task(pump(process.stderr, "stderr"))

    pending = 2
    while pending:
        item = await queue.get()
        if item is None:
            pending -= 1
            continue
        yield _ndjson(item)

    await stdout_task
    await stderr_task
    returncode = await process.wait()
    yield _ndjson({
        "type": "result",
        "result": {"returncode": returncode, "success": returncode == 0},
    })


@router.get("/targets")
async def firmware_targets(_claims: SessionClaims = Depends(require_admin)) -> dict:
    """Single fixed board -- kept as a list for shape-compatibility with
    the other firmware cards' frontend code, even though there's only
    ever one entry."""
    return {"boards": [{"macro": "HELTEC_V3", "label": _BOARD_LABEL, "fqbn": _FQBN}]}


@router.post("/compile/stream")
async def compile_firmware_stream(
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
) -> StreamingResponse:
    """Compile pager_client.ino, streaming arduino-cli's own stdout/stderr
    live. The compiled artifact lands in arduino-cli's own build cache
    (/opt/arduino-cli/cache), keyed by sketch path + fqbn -- the matching
    flash/stream call below finds it there."""

    async def body() -> AsyncIterator[bytes]:
        with audit.timed_action(
            user=claims.subject, action="pager_firmware.compile", params={},
        ) as ctx:
            cmd = [
                _ARDUINO_CLI_BIN, "--config-file", _ARDUINO_CLI_CONFIG,
                "compile", "-v", "--fqbn", _FQBN, str(_SKETCH_DIR),
            ]
            success = False
            async for chunk in _stream_subprocess(cmd):
                yield chunk
                event = json.loads(chunk)
                if event.get("type") == "result":
                    success = bool((event.get("result") or {}).get("success"))
            ctx.set_result("success" if success else "error")

    return StreamingResponse(
        body(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


class FlashRequest(BaseModel):
    port: str


@router.post("/flash/stream")
async def flash_firmware_stream(
    req: FlashRequest,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
) -> StreamingResponse:
    """Upload the already-compiled artifact (see compile/stream above --
    flash does not recompile) to ``port``.

    ``port`` can be ANY currently-connected USB-serial device -- validated
    against the live enumeration below (same one GET /api/config/serial-ports
    uses), never trusted as a raw path from the browser. Unlike the POCSAG/
    MeshCore/Meshtastic flash routes, there's no configured companion source
    to release/reconnect here: pager_client has no USB-serial link to
    Meshpoint at all, so flashing it never touches a live capture source.
    """
    from src.hal.usb_classifier import list_serial_ports_with_stable_paths
    real_ports = {
        value
        for dev in list_serial_ports_with_stable_paths()
        if dev.vid is not None
        for value in (dev.device, dev.stable_path, dev.by_id, dev.by_path)
        if value
    }
    if req.port not in real_ports:
        raise HTTPException(400, "Selected port is not a currently connected USB-serial device")
    port = req.port

    async def body() -> AsyncIterator[bytes]:
        with audit.timed_action(
            user=claims.subject, action="pager_firmware.flash", params={"port": port},
        ) as ctx:
            cmd = [
                _ARDUINO_CLI_BIN, "--config-file", _ARDUINO_CLI_CONFIG,
                "upload", "-p", port, "--fqbn", _FQBN, str(_SKETCH_DIR),
            ]
            success = False
            async for chunk in _stream_subprocess(cmd):
                yield chunk
                event = json.loads(chunk)
                if event.get("type") == "result":
                    success = bool((event.get("result") or {}).get("success"))
            ctx.set_result("success" if success else "error")

    return StreamingResponse(
        body(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
