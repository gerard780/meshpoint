"""Flash "dumb modem" RNode firmware onto a connected board from the
dashboard -- the same 3-step process (flash, provision EEPROM, set
firmware hash) the standalone https://liamcottle.github.io/rnode-flasher
web tool does via Web Serial in-browser, but driven server-side instead.

Deliberately NOT a Web Serial/browser-side port of rnode-flasher, even
though that's what reticulum-meshchat itself vendors verbatim
(src/frontend/public/rnode-flasher/ in that repo). Web Serial reaches
serial ports on whatever machine the *browser* is running on -- fine
for a local Electron app like meshchat, wrong for meshpoint, where the
dashboard is viewed remotely but the RNode is physically on the Pi.
Same server-side-subprocess pattern every other firmware card here
already uses (pocsag_firmware_routes.py, reticulum_companion_firmware_
routes.py, etc.) is the correct fit.

Wraps ``rnodeconf`` (RNS.Utilities.rnodeconf, a console-script bundled
with the ``rns`` pip package -- already a meshpoint dependency, so no
separate install step). ``rnodeconf --autoinstall`` is a purely
interactive wizard with no non-interactive CLI flags for board/band
selection -- confirmed by reading the real installed source
(RNS/Utilities/rnodeconf.py) rather than guessing, since a wrong
answer sequence could flash the wrong firmware for a board's radio
chip. ``_BOARDS`` below encodes the exact numbered-menu answer
sequence for each supported board, extracted directly from that
source. One confirmed simplification: ``-a`` alone (with a port
already supplied positionally) flashes firmware AND bootstraps the
EEPROM AND sets the firmware hash in the same run -- no separate
``-r``/``-H`` calls needed, confirmed from source (a successful flash
sets ``args.rom = True`` and ``wants_fw_provision = True`` internally,
falling through into the same process's own EEPROM-bootstrap step).

Two boards (LilyGO LoRa T3S3, LilyGO T-Beam) have a genuine radio-chip
ambiguity at the "868/915/923 MHz" band choice -- the menu offers it
twice, once for an SX1276 build and once for SX1262 -- so those two
expose both variants distinctly in ``_BOARDS`` rather than guessing
which chip a given physical unit has.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sys
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

router = APIRouter(prefix="/api/rnode/firmware", tags=["config", "reticulum"])


def _resolve_rnodeconf_bin() -> str:
    """``rnodeconf`` is a console-script pip installs alongside ``rns``
    in whichever Python environment ran ``pip install`` -- for
    meshpoint that's its own venv (``requirements.txt``), not
    necessarily on this *process's* ``$PATH``. Unlike an interactively
    activated venv (which prepends its own ``bin/`` to ``$PATH``),
    ``meshpoint.service`` invokes ``/opt/meshpoint/venv/bin/python``
    directly and gets systemd's own minimal default `$PATH` otherwise
    -- confirmed live: ``shutil.which("rnodeconf")`` came back empty
    even though it's genuinely installed. ``sys.executable``'s own
    directory is where pip actually put it (a sibling console-script
    next to the interpreter itself), so resolve relative to that
    first; fall back to a bare PATH lookup for any other environment
    (e.g. a real activated-venv shell) where that's simply how it's
    found.
    """
    candidate = Path(sys.executable).parent / "rnodeconf"
    if candidate.exists():
        return str(candidate)
    return "rnodeconf"


_RNODECONF_BIN = _resolve_rnodeconf_bin()

# Each value is the ordered sequence of menu answers rnodeconf's
# --autoinstall wizard expects on stdin, one line per prompt:
#   [top-level device-type number, "" (bare Enter past the info
#    screen), band/model number, "y" (final confirmation)]
# Extracted directly from RNS/Utilities/rnodeconf.py's autoinstall()
# menu -- see this module's own docstring. "label" is what the
# dropdown shows; boards are grouped by device, with one entry per
# meaningful band/chip variant.
_BOARDS = {
    "heltec_v2_433":  {"label": "Heltec LoRa32 v2 (433 MHz)",  "seq": ["7", "", "1", "y"]},
    "heltec_v2_868":  {"label": "Heltec LoRa32 v2 (868 MHz)",  "seq": ["7", "", "2", "y"]},
    "heltec_v2_915":  {"label": "Heltec LoRa32 v2 (915 MHz)",  "seq": ["7", "", "3", "y"]},
    "heltec_v2_923":  {"label": "Heltec LoRa32 v2 (923 MHz)",  "seq": ["7", "", "4", "y"]},

    "heltec_v3_433":  {"label": "Heltec LoRa32 v3 (433 MHz)",  "seq": ["8", "", "1", "y"]},
    "heltec_v3_868":  {"label": "Heltec LoRa32 v3 (868 MHz)",  "seq": ["8", "", "2", "y"]},
    "heltec_v3_915":  {"label": "Heltec LoRa32 v3 (915 MHz)",  "seq": ["8", "", "3", "y"]},
    "heltec_v3_923":  {"label": "Heltec LoRa32 v3 (923 MHz)",  "seq": ["8", "", "4", "y"]},

    # No 433 MHz variant exists for v4 -- only 3 band options in rnodeconf's own menu.
    "heltec_v4_868":  {"label": "Heltec LoRa32 v4 (868 MHz)",  "seq": ["9", "", "1", "y"]},
    "heltec_v4_915":  {"label": "Heltec LoRa32 v4 (915 MHz)",  "seq": ["9", "", "2", "y"]},
    "heltec_v4_923":  {"label": "Heltec LoRa32 v4 (923 MHz)",  "seq": ["9", "", "3", "y"]},

    "heltec_t114_433": {"label": "Heltec T114 (433 MHz)", "seq": ["15", "", "1", "y"]},
    "heltec_t114_868": {"label": "Heltec T114 (868 MHz)", "seq": ["15", "", "2", "y"]},
    "heltec_t114_915": {"label": "Heltec T114 (915 MHz)", "seq": ["15", "", "3", "y"]},
    "heltec_t114_923": {"label": "Heltec T114 (923 MHz)", "seq": ["15", "", "4", "y"]},

    "lilygo_v1_0_433": {"label": "LilyGO LoRa32 v1.0 (433 MHz)", "seq": ["5", "", "1", "y"]},
    "lilygo_v1_0_868": {"label": "LilyGO LoRa32 v1.0 (868 MHz)", "seq": ["5", "", "2", "y"]},
    "lilygo_v1_0_915": {"label": "LilyGO LoRa32 v1.0 (915 MHz)", "seq": ["5", "", "3", "y"]},
    "lilygo_v1_0_923": {"label": "LilyGO LoRa32 v1.0 (923 MHz)", "seq": ["5", "", "4", "y"]},

    "lilygo_v2_0_433": {"label": "LilyGO LoRa32 v2.0 (433 MHz)", "seq": ["4", "", "1", "y"]},
    "lilygo_v2_0_868": {"label": "LilyGO LoRa32 v2.0 (868 MHz)", "seq": ["4", "", "2", "y"]},
    "lilygo_v2_0_915": {"label": "LilyGO LoRa32 v2.0 (915 MHz)", "seq": ["4", "", "3", "y"]},
    "lilygo_v2_0_923": {"label": "LilyGO LoRa32 v2.0 (923 MHz)", "seq": ["4", "", "4", "y"]},

    # v2.1's own menu offers one combined 868/915/923 choice, plus TCXO variants.
    "lilygo_v2_1_433":          {"label": "LilyGO LoRa32 v2.1 (433 MHz)", "seq": ["3", "", "1", "y"]},
    "lilygo_v2_1_868_915_923":  {"label": "LilyGO LoRa32 v2.1 (868/915/923 MHz)", "seq": ["3", "", "2", "y"]},
    "lilygo_v2_1_433_tcxo":     {"label": "LilyGO LoRa32 v2.1 (433 MHz, TCXO)", "seq": ["3", "", "3", "y"]},
    "lilygo_v2_1_868_915_923_tcxo": {"label": "LilyGO LoRa32 v2.1 (868/915/923 MHz, TCXO)", "seq": ["3", "", "4", "y"]},

    # Chip-ambiguous: rnodeconf offers 868/915/923 twice, once per radio chip.
    "lilygo_t3s3_433_sx1278":         {"label": "LilyGO LoRa T3S3 (433 MHz, SX1278)", "seq": ["10", "", "1", "y"]},
    "lilygo_t3s3_868_915_923_sx1276": {"label": "LilyGO LoRa T3S3 (868/915/923 MHz, SX1276)", "seq": ["10", "", "2", "y"]},
    "lilygo_t3s3_433_sx1268":         {"label": "LilyGO LoRa T3S3 (433 MHz, SX1268)", "seq": ["10", "", "3", "y"]},
    "lilygo_t3s3_868_915_923_sx1262": {"label": "LilyGO LoRa T3S3 (868/915/923 MHz, SX1262)", "seq": ["10", "", "4", "y"]},
    "lilygo_t3s3_2_4ghz":             {"label": "LilyGO LoRa T3S3 (2.4 GHz)", "seq": ["10", "", "5", "y"]},

    "lilygo_tbeam_433_sx1278":         {"label": "LilyGO T-Beam (433 MHz, SX1278)", "seq": ["6", "", "1", "y"]},
    "lilygo_tbeam_868_915_923_sx1276": {"label": "LilyGO T-Beam (868/915/923 MHz, SX1276)", "seq": ["6", "", "2", "y"]},
    "lilygo_tbeam_433_sx1268":         {"label": "LilyGO T-Beam (433 MHz, SX1268)", "seq": ["6", "", "3", "y"]},
    "lilygo_tbeam_868_915_923_sx1262": {"label": "LilyGO T-Beam (868/915/923 MHz, SX1262)", "seq": ["6", "", "4", "y"]},

    "lilygo_tbeam_supreme_433":         {"label": "LilyGO T-Beam Supreme (433 MHz)", "seq": ["13", "", "1", "y"]},
    "lilygo_tbeam_supreme_868_915_923": {"label": "LilyGO T-Beam Supreme (868/915/923 MHz)", "seq": ["13", "", "2", "y"]},

    "lilygo_tdeck_433":         {"label": "LilyGO T-Deck (433 MHz)", "seq": ["14", "", "1", "y"]},
    "lilygo_tdeck_868_915_923": {"label": "LilyGO T-Deck (868/915/923 MHz)", "seq": ["14", "", "2", "y"]},

    "lilygo_techo_433": {"label": "LilyGO T-Echo (433 MHz)", "seq": ["12", "", "1", "y"]},
    "lilygo_techo_868": {"label": "LilyGO T-Echo (868 MHz)", "seq": ["12", "", "2", "y"]},
    "lilygo_techo_915": {"label": "LilyGO T-Echo (915 MHz)", "seq": ["12", "", "3", "y"]},
    "lilygo_techo_923": {"label": "LilyGO T-Echo (923 MHz)", "seq": ["12", "", "4", "y"]},

    "rak4631_433": {"label": "RAK4631 (433 MHz)", "seq": ["11", "", "1", "y"]},
    "rak4631_868": {"label": "RAK4631 (868 MHz)", "seq": ["11", "", "2", "y"]},
    "rak4631_915": {"label": "RAK4631 (915 MHz)", "seq": ["11", "", "3", "y"]},
    "rak4631_923": {"label": "RAK4631 (923 MHz)", "seq": ["11", "", "4", "y"]},
}

# Printed only when args.autoinstall is set AND the post-write EEPROM
# read-back confirms rnode.provisioned -- i.e. flash + EEPROM bootstrap
# + firmware-hash-set all genuinely succeeded. A 0 returncode alone
# isn't a reliable success signal here (e.g. an "already installed and
# provisioned" board exits early, harmlessly, without this string).
_SUCCESS_MARKER = "RNode Firmware autoinstallation complete!"


def _ndjson(payload: dict) -> bytes:
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")


def _rnodeconf_available() -> bool:
    resolved = Path(_RNODECONF_BIN)
    if resolved.is_absolute():
        return resolved.exists()
    return shutil.which(_RNODECONF_BIN) is not None


async def _stream_autoinstall(port: str, sequence: list[str]) -> AsyncIterator[bytes]:
    """Runs ``rnodeconf -a <port>``, pre-feeding the entire canned answer
    sequence to stdin immediately after spawn. Safe to do up front
    rather than matching each prompt before answering it: rnodeconf's
    ``input()`` calls are strictly sequential synchronous reads, so
    queued lines satisfy each prompt in order regardless of whether
    its prompt text has been printed yet -- confirmed against the real
    source, not assumed."""
    cmd = [_RNODECONF_BIN, "-a", port]
    yield _ndjson({"type": "started", "cmd": cmd})
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, OSError) as exc:
        yield _ndjson({
            "type": "result",
            "result": {"returncode": -1, "success": False, "error": str(exc)},
        })
        return

    if process.stdin is not None:
        input_bytes = ("\n".join(sequence) + "\n").encode("utf-8")
        process.stdin.write(input_bytes)
        await process.stdin.drain()
        process.stdin.close()

    queue: asyncio.Queue = asyncio.Queue()
    saw_success_marker = False

    async def pump(stream: Optional[asyncio.StreamReader], name: str) -> None:
        if stream is not None:
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip("\n")
                await queue.put({"type": "line", "stream": name, "text": text})
        await queue.put(None)

    stdout_task = asyncio.create_task(pump(process.stdout, "stdout"))
    stderr_task = asyncio.create_task(pump(process.stderr, "stderr"))

    pending = 2
    while pending:
        item = await queue.get()
        if item is None:
            pending -= 1
            continue
        if _SUCCESS_MARKER in item.get("text", ""):
            saw_success_marker = True
        yield _ndjson(item)

    await stdout_task
    await stderr_task
    returncode = await process.wait()
    yield _ndjson({
        "type": "result",
        "result": {"returncode": returncode, "success": saw_success_marker},
    })


@router.get("/targets")
async def firmware_targets(_claims: SessionClaims = Depends(require_admin)) -> dict:
    return {
        "boards": [
            {"value": key, "label": board["label"]}
            for key, board in _BOARDS.items()
        ],
        "rnodeconf_available": _rnodeconf_available(),
    }


class FlashRequest(BaseModel):
    board: str
    port: str


@router.post("/flash/stream")
async def flash_firmware_stream(
    req: FlashRequest,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
) -> StreamingResponse:
    """Flashes RNode firmware + bootstraps EEPROM + sets firmware hash
    in one ``rnodeconf -a`` run (see module docstring for why one
    command covers all three steps). ``port`` can be ANY currently-
    connected USB-serial device, same live-enumeration validation
    every other flash route uses -- this isn't tied to a pre-configured
    companion."""
    board = _BOARDS.get(req.board)
    if board is None:
        raise HTTPException(400, "Unknown board selection")

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
            user=claims.subject, action="rnode_firmware.flash",
            params={"board": req.board, "port": port},
        ) as ctx:
            success = False
            async for chunk in _stream_autoinstall(port, board["seq"]):
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
