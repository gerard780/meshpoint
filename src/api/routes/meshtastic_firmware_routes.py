"""Download and flash official Meshtastic firmware onto a Serial companion.

Companion to ``pocsag_firmware_routes.py`` but for repurposing a spare
ESP32 board (e.g. one previously running ``pocsag_companion``) into a
Meshtastic USB stick for Configuration -> Serial, using Meshtastic's own
official prebuilt releases rather than anything compiled in this repo.

No compiling here at all -- Meshtastic firmware is PlatformIO-built
upstream, not an Arduino sketch, so ``arduino-cli`` doesn't apply. Instead:
fetch the latest ``meshtastic/firmware`` GitHub release, resolve which
per-chip-architecture ZIP a given board lives in via the release's own
top-level manifest (``firmware-<version>.json``, ``{"board":...,
"platform":...}`` per target -- see ``_resolve_board_platform``), extract
just that board's ``.factory.bin`` (a combined bootloader+partition-
table+app image meant for offset 0x0 -- i.e. a from-scratch flash of a
board that wasn't already running Meshtastic) plus its ``littlefs-*.bin``
(the filesystem partition, offset read from the SAME per-board
``.mt.json`` metadata file bundled in the zip, not hardcoded), cache both
under ``<repo_root>/data/meshtastic-firmware``, then flash with the standalone
``esptool`` (installed by ``scripts/install.sh``, since arduino-cli's own
bundled copy isn't on ``PATH``) -- ``--erase-all`` first, since the board
may currently hold an entirely different firmware's partition layout.

Curated board list (``_CURATED_BOARDS``) rather than Meshtastic's full
~130-target catalog -- just the hardware this project's users actually
have. The per-board chip/mcu and every flash offset still come from the
release's own metadata at flash time, never hardcoded here, so a new
Meshtastic release can't silently drift out of sync with this file --
only the *list of boards offered* needs a manual addition for new
hardware.
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import urllib.request
import zipfile
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

router = APIRouter(prefix="/api/config/serial/firmware", tags=["config", "serial"])

_config: Optional[AppConfig] = None
_serial_sources: list = []

# Lives under this install's own data/ dir (like the SQLite DB) rather
# than a standalone /opt path -- data/ already exists (install.sh's
# "Create data directory" section), is already excluded from install.sh's
# rsync so an upgrade never touches it, and is already owned by
# `meshpoint` recursively, so no separate mkdir/chown step is needed the
# way /opt/arduino-cli (a genuinely separate, reusable toolchain) needed
# its own. Resolved dynamically, same technique pocsag_firmware_routes.py
# uses for _SKETCH_DIR, rather than hardcoding /opt/meshpoint.
_CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "meshtastic-firmware"
_RELEASES_LATEST_URL = "https://api.github.com/repos/meshtastic/firmware/releases/latest"
_ESPTOOL_BIN = "esptool"

# board slug -> display label. Deliberately not Meshtastic's whole
# catalog (~130 targets as of writing) -- just what this project's
# hardware lineup (extra/pocsag_companion's own TTGO/Heltec boards)
# actually covers.
_CURATED_BOARDS: dict[str, str] = {
    "heltec-v3": "Heltec V3",
    "tlora-v2-1-1_6": "TTGO LoRa32 V2.1-1.6",
    "tlora-v3-3-0-tcxo": "TTGO T3 V3.0 (TCXO)",
}


def init_routes(config: AppConfig, serial_sources=None) -> None:
    global _config, _serial_sources
    _config = config
    _serial_sources = serial_sources or []


def _resolve_serial_source(label: str):
    """Mirrors serial_config_routes.py's own helper -- same
    ``serial_<label>``/bare ``serial`` naming convention."""
    name = f"serial_{label}" if label else "serial"
    for src in _serial_sources:
        if src.name == name:
            return src
    return None


def _ndjson(payload: dict) -> bytes:
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")


@router.get("/targets")
async def firmware_targets(_claims: SessionClaims = Depends(require_admin)) -> dict:
    """Curated board choices for the Meshtastic flash pulldown."""
    return {"boards": [{"board": b, "label": lbl} for b, lbl in _CURATED_BOARDS.items()]}


def _fetch_json_sync(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _download_to_sync(url: str, dest: Path) -> None:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=180) as resp, open(dest, "wb") as out:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)


def _cache_dir_for(board: str, version: str) -> Path:
    return _CACHE_DIR / board / version


def _ensure_board_firmware_cached_sync(board: str) -> dict:
    """Downloads (if not already cached) the given board's latest
    official Meshtastic release, returning::

        {"version": str, "mcu": str,
         "factory_bin": Path, "littlefs_bin": Path | None,
         "littlefs_offset": int | None}

    Runs entirely off the event loop (blocking network I/O + zip
    extraction) -- callers must wrap this in ``run_in_executor``.
    """
    release = _fetch_json_sync(_RELEASES_LATEST_URL)
    assets = {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}

    manifest_name = next(
        (n for n in assets if n.startswith("firmware-") and n.endswith(".json")), None,
    )
    if not manifest_name:
        raise RuntimeError("Could not find the firmware manifest in the latest release")
    with tempfile.NamedTemporaryFile(suffix=".json") as tmp:
        _download_to_sync(assets[manifest_name], Path(tmp.name))
        manifest = json.loads(Path(tmp.name).read_text())

    version = manifest.get("version") or release.get("tag_name", "").lstrip("v")
    target = next((t for t in manifest.get("targets", []) if t.get("board") == board), None)
    if target is None:
        raise RuntimeError(f"Board '{board}' not found in the latest Meshtastic release")
    platform = target["platform"]

    cache_dir = _cache_dir_for(board, version)
    mt_json_path = cache_dir / f"firmware-{board}-{version}.mt.json"
    factory_path = cache_dir / f"firmware-{board}-{version}.factory.bin"

    if mt_json_path.exists() and factory_path.exists():
        mt = json.loads(mt_json_path.read_text())
    else:
        zip_name = f"firmware-{platform}-{version}.zip"
        if zip_name not in assets:
            raise RuntimeError(f"Could not find {zip_name} in the latest release assets")
        cache_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".zip") as tmp_zip:
            _download_to_sync(assets[zip_name], Path(tmp_zip.name))
            with zipfile.ZipFile(tmp_zip.name) as zf:
                names = set(zf.namelist())
                mt_name = f"firmware-{board}-{version}.mt.json"
                factory_name = f"firmware-{board}-{version}.factory.bin"
                if mt_name not in names or factory_name not in names:
                    raise RuntimeError(
                        f"Expected files for '{board}' missing from {zip_name}",
                    )
                mt = json.loads(zf.read(mt_name))
                mt_json_path.write_bytes(zf.read(mt_name))
                factory_path.write_bytes(zf.read(factory_name))

                spiffs_file = next(
                    (f["name"] for f in mt.get("files", []) if f.get("part_name") == "spiffs"),
                    None,
                )
                if spiffs_file and spiffs_file in names:
                    (cache_dir / spiffs_file).write_bytes(zf.read(spiffs_file))

    spiffs_file = next(
        (f["name"] for f in mt.get("files", []) if f.get("part_name") == "spiffs"), None,
    )
    littlefs_path = (cache_dir / spiffs_file) if spiffs_file else None
    spiffs_part = next((p for p in mt.get("part", []) if p.get("name") == "spiffs"), None)
    littlefs_offset = int(spiffs_part["offset"], 16) if spiffs_part else None

    return {
        "version": version,
        "mcu": mt["mcu"],
        "factory_bin": factory_path,
        "littlefs_bin": littlefs_path if (littlefs_path and littlefs_path.exists()) else None,
        "littlefs_offset": littlefs_offset,
    }


async def _stream_subprocess(cmd: list[str]) -> AsyncIterator[bytes]:
    """Same NDJSON subprocess-streaming shape as
    pocsag_firmware_routes.py's own helper -- duplicated rather than
    imported since the two route modules are otherwise independent and
    this is the only piece they'd share."""
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


class FlashRequest(BaseModel):
    board: str
    label: str = ""


@router.post("/flash/stream")
async def flash_meshtastic_stream(
    req: FlashRequest,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
) -> StreamingResponse:
    """Downloads (if needed) the chosen board's latest official
    Meshtastic release and writes it to one configured Serial device's
    port with esptool -- full from-scratch flash (--erase-all), for
    repurposing a board that may currently hold entirely different
    firmware (e.g. extra/pocsag_companion). Port is resolved server-side
    from capture.serial by label, never trusted from the browser.
    """
    if req.board not in _CURATED_BOARDS:
        raise HTTPException(400, "Unknown board")

    port = None
    if _config is not None:
        for d in _config.capture.serial:
            if (d.label or "") == (req.label or ""):
                port = d.serial_port
                break
    if not port:
        raise HTTPException(400, "No configured serial port for this device")

    source = _resolve_serial_source(req.label)

    async def body() -> AsyncIterator[bytes]:
        with audit.timed_action(
            user=claims.subject, action="meshtastic_firmware.flash",
            params={"board": req.board, "label": req.label, "port": port},
        ) as ctx:
            yield _ndjson({
                "type": "line", "stream": "stdout",
                "text": f"Fetching latest Meshtastic firmware for {_CURATED_BOARDS[req.board]}…",
            })
            loop = asyncio.get_running_loop()
            try:
                fw = await loop.run_in_executor(
                    None, _ensure_board_firmware_cached_sync, req.board,
                )
            except Exception as exc:
                logger.exception("Meshtastic firmware fetch failed for %s", req.board)
                yield _ndjson({"type": "line", "stream": "stderr", "text": str(exc)})
                yield _ndjson({
                    "type": "result",
                    "result": {"returncode": -1, "success": False, "error": str(exc)},
                })
                ctx.set_result("error")
                return

            yield _ndjson({
                "type": "line", "stream": "stdout",
                "text": f"Using Meshtastic {fw['version']} ({fw['mcu']}).",
            })

            released = source is not None and source.connected
            if released:
                yield _ndjson({
                    "type": "line", "stream": "stdout",
                    "text": f"Releasing {port} ({source.name} was connected)…",
                })
                await source.stop()

            write_flash_args = ["0x0", str(fw["factory_bin"])]
            if fw["littlefs_bin"] and fw["littlefs_offset"] is not None:
                write_flash_args += [hex(fw["littlefs_offset"]), str(fw["littlefs_bin"])]

            cmd = [
                _ESPTOOL_BIN, "--chip", fw["mcu"], "--port", port, "--baud", "921600",
                "write-flash", "--erase-all", *write_flash_args,
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
                await source.start()
                yield _ndjson({
                    "type": "line", "stream": "stdout",
                    "text": (
                        f"{source.name} reconnected on {port}."
                        if source.connected
                        else f"{source.name} did NOT reconnect -- "
                             "a service restart may be needed."
                    ),
                })

            ctx.set_result("success" if success else "error")

    return StreamingResponse(
        body(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
