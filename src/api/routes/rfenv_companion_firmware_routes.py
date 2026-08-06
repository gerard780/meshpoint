"""Compile and flash extra/rfenv_companion firmware from the dashboard.

Same ``arduino-cli`` streaming mechanism as pocsag_firmware_routes.py /
pager_firmware_routes.py. Closer to pager_client.ino in shape --
**single board only** (Heltec V3, no ``BOARD_*`` toggle, no board
pulldown) and **no compile-time injection** (no capcodes/frequency to
rewrite into the sketch -- a per-device frequency override may be added
later, deliberately deferred for now since RfEnvCompanionScanService
already carries the anchor frequency itself at runtime, not baked into
firmware).

Unlike pager_client, though, this board DOES hold a live USB-serial
connection when configured+running (RfEnvCompanionScanService owns the
port exactly like DapnetSerialSource does) -- so the flash route mirrors
pocsag_firmware_routes.py's release/reconnect logic instead of pager's
"nothing to release" simplicity: if the selected port matches the
configured ``capture.rfenv_companion`` device, the live service is
stopped before flashing (arduino-cli needs exclusive access to reset+
write the board) and restarted afterward.
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
from src.config import AppConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rfenv-companion/firmware", tags=["config", "rfenv-companion"])

_SKETCH_DIR = Path(__file__).resolve().parents[3] / "extra" / "rfenv_companion"
_ARDUINO_CLI_BIN = "arduino-cli"
_ARDUINO_CLI_CONFIG = "/opt/arduino-cli/arduino-cli.yaml"
_FQBN = "esp32:esp32:heltec_wifi_lora_32_V3"
_BOARD_LABEL = "Heltec V3"

_config: AppConfig | None = None
_service = None  # RfEnvCompanionScanService, or None if not configured/running


def init_routes(config: AppConfig, service=None) -> None:
    global _config, _service
    _config = config
    _service = service


def _sketch_ino_path() -> Path:
    return _SKETCH_DIR / "rfenv_companion.ino"


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
    """Compile rfenv_companion.ino as-is -- no per-device rewrite step
    (unlike pager_client's capcode injection), nothing in the sketch
    needs a value only known at compile-request time yet."""

    async def body() -> AsyncIterator[bytes]:
        with audit.timed_action(
            user=claims.subject, action="rfenv_companion_firmware.compile", params={},
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

    ``port`` can be ANY currently-connected USB-serial device, same
    live-enumeration validation every other flash route uses. If it
    matches the configured ``capture.rfenv_companion`` device's own
    port, the live RfEnvCompanionScanService is stopped first (esptool
    needs exclusive access) and restarted afterward -- same
    release/reconnect reasoning as pocsag_firmware_routes.py's own flash
    route, adapted for this service instead of a CaptureSource.
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

    configured_port = None
    if _config is not None and _config.capture.rfenv_companion:
        configured_port = _config.capture.rfenv_companion[0].serial_port
    service = _service if (configured_port and configured_port == port) else None

    async def body() -> AsyncIterator[bytes]:
        with audit.timed_action(
            user=claims.subject, action="rfenv_companion_firmware.flash", params={"port": port},
        ) as ctx:
            released = service is not None
            if released:
                yield _ndjson({
                    "type": "line", "stream": "stdout",
                    "text": f"Releasing {port} (RF Environment companion was connected)…",
                })
                await service.stop()

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

            if released:
                yield _ndjson({
                    "type": "line", "stream": "stdout",
                    "text": "Waiting for the board to finish rebooting…",
                })
                await asyncio.sleep(3.0)
                await service.start()
                yield _ndjson({
                    "type": "line", "stream": "stdout",
                    "text": (
                        "RF Environment companion reconnected."
                        if service.is_running
                        else "RF Environment companion did NOT reconnect -- "
                             "a service restart may be needed."
                    ),
                })

            ctx.set_result("success" if success else "error")

    return StreamingResponse(
        body(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
