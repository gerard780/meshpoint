"""Provision and flash extra/heltec_v4_reticulum_bron/microReticulum_Firmware
from the dashboard -- the standalone Heltec V4 Reticulum node (WiFi + a TCP
uplink to a Reticulum transport backbone, LoRa on the other side).

Unlike the arduino-cli-based Pager/POCSAG/RF-Env cards, this firmware's own
platformio.ini needs PlatformIO specifically -- per-environment
``custom_variant``/littlefs/symlinked ``lib_deps`` config arduino-cli's
boards.txt system can't express. So this wraps ``pio`` instead of
``arduino-cli``, same streamed-NDJSON mechanism otherwise.

**Single fixed board/environment**, deliberately: ``heltec_wifi_lora_32_V4-
local-udp`` is the only environment this card targets, even though the
firmware's own platformio.ini defines 32 (28 ESP32 + 4 nRF52 boards this
deployment doesn't own). No board picker.

**No live service to release/reconnect**, same reasoning as
pager_firmware_routes.py: this board has no configured USB-serial
capture source (it's a standalone WiFi device, not a companion Meshpoint
holds an open connection to), so flashing it never touches a running
CaptureSource.

WiFi SSID/password and the VPS backbone host/port are this firmware's only
run-time-configurable settings, and they're compile-time ``#define``s (see
``node_config.h``) -- there's no NVS/serial provisioning path like POCSAG/
RF-Env's ``set_wifi`` commands. So "Compile" here means: validate the form,
rewrite ``node_config.h`` (same content ``flash-node.sh`` already writes),
then build. Flash uploads the resulting image, same two-step shape as every
other firmware card even though a config change always requires an actual
rebuild here (no reusing yesterday's binary with new credentials).

``_ndjson``/``_stream_subprocess`` are duplicated from pocsag_firmware_routes.py
rather than shared -- matches the existing convention in every sibling file.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from src.api.audit import AuditLogWriter
from src.api.audit.dependencies import get_audit_writer
from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/reticulum-companion/firmware", tags=["config", "reticulum-companion"],
)

_PROJECT_DIR = (
    Path(__file__).resolve().parents[3]
    / "extra" / "heltec_v4_reticulum_bron" / "microReticulum_Firmware"
)
_PIO_BIN = "pio"
_ENV_NAME = "heltec_wifi_lora_32_V4-local-udp"
_BOARD_LABEL = "Heltec V4 (standalone Reticulum node)"

_DEFAULT_VPS_HOST = "node.reticulumnet.nl"
_DEFAULT_VPS_PORT = 4242

# Both SSID and password go through this firmware's own fixed 32-byte
# EEPROM-era buffers (Remote.h: `strncpy(wr_ssid, NODE_WIFI_SSID, 32)`,
# same for wr_psk) -- confirmed from source, NOT the same as the real
# 802.11 SSID limit (also 32, coincidentally) or WPA2's real 63-char
# password allowance. A longer value silently truncates on the device
# rather than erroring, so this is enforced here instead -- better an
# explicit 400 now than a mysteriously-wrong password on the board.
_MAX_CRED_LEN = 32

# Disallows the two characters that could break out of the generated C
# string literal in node_config.h (see _c_string_literal) plus raw
# control characters -- this value gets written directly into a .h file
# that then gets compiled and run on real hardware, so this is a real
# injection boundary, not just cosmetic validation.
_FORBIDDEN_STRING_CHARS = re.compile(r'["\\\x00-\x1f]')
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9\-.]{0,251}[A-Za-z0-9])?$")


def _c_string_literal(value: str, field_name: str) -> str:
    if len(value.encode("utf-8")) > _MAX_CRED_LEN:
        raise ValueError(
            f"{field_name} is too long ({len(value)} chars) -- this firmware's own "
            f"buffer truncates at {_MAX_CRED_LEN} bytes, so anything longer would "
            f"silently fail to connect on the device"
        )
    if _FORBIDDEN_STRING_CHARS.search(value):
        raise ValueError(f'{field_name} cannot contain a quote, backslash, or control character')
    return value


class ProvisionRequest(BaseModel):
    ssid: str = Field(..., min_length=1)
    password: str = ""  # blank = open network, this firmware handles it (Remote.h)
    vps_host: str = ""  # blank -> _DEFAULT_VPS_HOST
    vps_port: int = _DEFAULT_VPS_PORT

    @field_validator("ssid")
    @classmethod
    def _validate_ssid(cls, v: str) -> str:
        return _c_string_literal(v, "SSID")

    @field_validator("password")
    @classmethod
    def _validate_password(cls, v: str) -> str:
        return _c_string_literal(v, "Password")

    @field_validator("vps_host")
    @classmethod
    def _validate_vps_host(cls, v: str) -> str:
        v = v.strip() or _DEFAULT_VPS_HOST
        if not _HOSTNAME_RE.match(v):
            raise ValueError("VPS host must look like a hostname or IP (letters, digits, dots, hyphens)")
        return v

    @field_validator("vps_port")
    @classmethod
    def _validate_vps_port(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError("VPS port must be between 1 and 65535")
        return v


def _node_config_path() -> Path:
    return _PROJECT_DIR / "node_config.h"


def _write_node_config(req: ProvisionRequest) -> None:
    """Writes node_config.h with the requested WiFi/VPS settings -- same
    content flash-node.sh generates by hand, just from a validated
    Pydantic model instead of a shell-parsed text file."""
    content = (
        "// Generated by the dashboard's Reticulum companion firmware card "
        "-- do not edit manually.\n"
        "#ifndef NODE_CONFIG_H\n"
        "#define NODE_CONFIG_H\n"
        f'#define NODE_WIFI_SSID "{req.ssid}"\n'
        f'#define NODE_WIFI_PSK  "{req.password}"\n'
        f'#define NODE_VPS_HOST  "{req.vps_host}"\n'
        f"#define NODE_VPS_PORT  {req.vps_port}\n"
        "#endif\n"
    )
    _node_config_path().write_text(content)


def _ndjson(payload: dict) -> bytes:
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")


async def _stream_subprocess(cmd: list[str], cwd: Optional[Path] = None) -> AsyncIterator[bytes]:
    """Run ``cmd``, yielding one NDJSON line per stdout/stderr line as it
    arrives, then a final ``{"type":"result",...}``. Identical shape to
    pocsag_firmware_routes.py's own copy, plus an optional ``cwd`` since
    ``pio`` (unlike arduino-cli) resolves its project from the working
    directory, not a path argument."""
    yield _ndjson({"type": "started", "cmd": cmd})
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd) if cwd else None,
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


def _platformio_available() -> bool:
    """Whether `pio` is actually on PATH -- scripts/install.sh's "Install
    PlatformIO toolchain" section is opt-in (asked interactively, or
    skippable with --skip-platformio), so a fresh install may legitimately
    not have it. Compile/Flash would otherwise just fail with an opaque
    "command not found" deep in the stream output."""
    return shutil.which(_PIO_BIN) is not None


@router.get("/targets")
async def firmware_targets(_claims: SessionClaims = Depends(require_admin)) -> dict:
    """Single fixed board/environment -- kept as a list for shape-
    compatibility with the other firmware cards' frontend code."""
    return {
        "boards": [{"macro": "HELTEC_V4", "label": _BOARD_LABEL, "env": _ENV_NAME}],
        "default_vps_host": _DEFAULT_VPS_HOST,
        "default_vps_port": _DEFAULT_VPS_PORT,
        "max_cred_len": _MAX_CRED_LEN,
        "platformio_available": _platformio_available(),
    }


@router.post("/compile/stream")
async def compile_firmware_stream(
    req: ProvisionRequest,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
) -> StreamingResponse:
    """Write node_config.h from the submitted WiFi/VPS settings, then
    build (not upload) via PlatformIO. The resulting image lands in
    PlatformIO's own build cache (``.pio/build/<env>/``, inside the
    project dir, gitignored) -- the matching flash/stream call below
    uploads it from there.
    """

    async def body() -> AsyncIterator[bytes]:
        with audit.timed_action(
            user=claims.subject, action="reticulum_companion_firmware.compile",
            params={
                "ssid": req.ssid, "vps_host": req.vps_host, "vps_port": req.vps_port,
                # password deliberately omitted from audit params
            },
        ) as ctx:
            _write_node_config(req)
            yield _ndjson({
                "type": "line", "stream": "stdout",
                "text": f"Provisioning for WiFi \"{req.ssid}\", backbone "
                        f"{req.vps_host}:{req.vps_port}…",
            })

            cmd = [_PIO_BIN, "run", "-e", _ENV_NAME]
            success = False
            async for chunk in _stream_subprocess(cmd, cwd=_PROJECT_DIR):
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
    """Upload the already-built image (see compile/stream above) to
    ``port``. PlatformIO rebuilds automatically if anything changed since
    the last compile (e.g. node_config.h), same as a bare ``pio run``
    would -- this isn't a strict "flash does not recompile" guarantee the
    way the arduino-cli cards document, just how PlatformIO's own
    incremental build works.

    ``port`` can be ANY currently-connected USB-serial device, same
    live-enumeration validation every other flash route uses. No
    configured companion service to release/reconnect here -- see the
    module docstring.
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
            user=claims.subject, action="reticulum_companion_firmware.flash", params={"port": port},
        ) as ctx:
            cmd = [_PIO_BIN, "run", "-e", _ENV_NAME, "-t", "upload", "--upload-port", port]
            success = False
            async for chunk in _stream_subprocess(cmd, cwd=_PROJECT_DIR):
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
