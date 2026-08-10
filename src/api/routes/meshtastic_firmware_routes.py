"""Download and flash official Meshtastic firmware via esptool.

Fetches meshtastic/firmware GitHub releases, caches per-board
``.factory.bin`` + littlefs, streams esptool write-flash as NDJSON.
Credit: javastraat/meshpoint (firmware flash port).
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
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
from src.api.firmware import (
    EspToolBinaryResolver,
    EspToolNdjsonStreamer,
    GithubHttpClient,
)
from src.config import AppConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config/serial/firmware", tags=["config", "serial"])

_config: Optional[AppConfig] = None
_serial_sources: list = []

_CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "meshtastic-firmware"
_RELEASES_LATEST_URL = (
    "https://api.github.com/repos/meshtastic/firmware/releases/latest"
)
_RELEASES_LIST_URL = (
    "https://api.github.com/repos/meshtastic/firmware/releases?per_page=10"
)
_RELEASES_BY_TAG_URL = (
    "https://api.github.com/repos/meshtastic/firmware/releases/tags/{tag}"
)

_http = GithubHttpClient()
_streamer = EspToolNdjsonStreamer()
_esptool = EspToolBinaryResolver()


def init_routes(config: AppConfig, serial_sources=None) -> None:
    global _config, _serial_sources
    _config = config
    _serial_sources = serial_sources or []


def _resolve_serial_source(label: str):
    """Match ``serial`` / ``serial_<label>`` capture sources."""
    name = f"serial_{label}" if label else "serial"
    for src in _serial_sources:
        if src.name == name:
            return src
    return None


def _ndjson(payload: dict) -> bytes:
    return _streamer.ndjson(payload)


@router.get("/installed")
async def firmware_installed(
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Firmware versions reported by configured Meshtastic USB serial sticks."""
    from src.capture.serial_firmware_info import SerialFirmwareInfoReader

    reader = SerialFirmwareInfoReader()
    devices = [reader.read_from_source(src) for src in _serial_sources]
    return {"devices": devices}


def _resolve_release_sync(tag: str) -> dict:
    if tag:
        return _http.fetch_json_sync(_RELEASES_BY_TAG_URL.format(tag=tag))
    return _http.fetch_json_sync(_RELEASES_LATEST_URL)


def _releases_sync(limit: int = 10) -> list[dict]:
    releases = _http.fetch_json_sync(_RELEASES_LIST_URL)
    if not isinstance(releases, list):
        raise RuntimeError("Unexpected GitHub API response for Meshtastic releases")
    return releases[:limit]


def _manifest_from_release_sync(release: dict) -> dict:
    assets = {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}
    manifest_name = next(
        (n for n in assets if n.startswith("firmware-") and n.endswith(".json")),
        None,
    )
    if not manifest_name:
        raise RuntimeError("Could not find the firmware manifest in this release")
    with tempfile.NamedTemporaryFile(suffix=".json") as tmp:
        _http.download_to_sync(assets[manifest_name], Path(tmp.name))
        return json.loads(Path(tmp.name).read_text())


def _board_list_from_manifest_sync(manifest: dict) -> list[dict]:
    boards = [
        {"board": t["board"], "label": t["board"].replace("-", " ")}
        for t in manifest.get("targets", [])
        if t.get("board")
    ]
    boards.sort(key=lambda b: b["label"].casefold())
    return boards


@router.get("/targets")
async def firmware_targets(
    tag: str = "",
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Board choices for the flash pulldown (live from release manifest)."""
    loop = asyncio.get_running_loop()
    try:
        release = await loop.run_in_executor(None, _resolve_release_sync, tag)
        manifest = await loop.run_in_executor(
            None, _manifest_from_release_sync, release,
        )
        boards = _board_list_from_manifest_sync(manifest)
    except Exception as exc:
        raise HTTPException(502, f"Could not fetch Meshtastic board list: {exc}")
    return {"boards": boards, "tag": release.get("tag_name", "")}


@router.get("/releases")
async def firmware_releases(_claims: SessionClaims = Depends(require_admin)) -> dict:
    """Recent Meshtastic releases for the version pulldown, newest first."""
    loop = asyncio.get_running_loop()
    try:
        releases = await loop.run_in_executor(None, _releases_sync, 10)
    except Exception as exc:
        raise HTTPException(502, f"Could not fetch Meshtastic releases: {exc}")
    return {
        "releases": [
            {"tag": r.get("tag_name", ""), "published_at": r.get("published_at")}
            for r in releases
        ],
    }


def _cache_dir_for(board: str, version: str) -> Path:
    return _CACHE_DIR / board / version


def _ensure_board_firmware_cached_sync(board: str, tag: str = "") -> dict:
    """Download (if needed) board factory + littlefs; return paths/offsets."""
    release = _resolve_release_sync(tag)
    manifest = _manifest_from_release_sync(release)
    assets = {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}

    version = manifest.get("version") or release.get("tag_name", "").lstrip("v")
    target = next(
        (t for t in manifest.get("targets", []) if t.get("board") == board), None,
    )
    if target is None:
        raise RuntimeError(
            f"Board '{board}' not found in Meshtastic "
            f"{release.get('tag_name', 'this release')}"
        )
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
            _http.download_to_sync(assets[zip_name], Path(tmp_zip.name))
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
                mt_json_path.chmod(0o644)
                factory_path.chmod(0o644)

                spiffs_file = next(
                    (
                        f["name"]
                        for f in mt.get("files", [])
                        if f.get("part_name") == "spiffs"
                    ),
                    None,
                )
                if spiffs_file and spiffs_file in names:
                    spiffs_path = cache_dir / spiffs_file
                    spiffs_path.write_bytes(zf.read(spiffs_file))
                    spiffs_path.chmod(0o644)

    spiffs_file = next(
        (f["name"] for f in mt.get("files", []) if f.get("part_name") == "spiffs"),
        None,
    )
    littlefs_path = (cache_dir / spiffs_file) if spiffs_file else None
    spiffs_part = next(
        (p for p in mt.get("part", []) if p.get("name") == "spiffs"), None,
    )
    littlefs_offset = int(spiffs_part["offset"], 16) if spiffs_part else None

    return {
        "version": version,
        "mcu": mt["mcu"],
        "factory_bin": factory_path,
        "littlefs_bin": littlefs_path if (littlefs_path and littlefs_path.exists()) else None,
        "littlefs_offset": littlefs_offset,
    }


def _port_aliases(port: str) -> set[str]:
    from src.hal.usb_classifier import list_serial_ports_with_stable_paths

    aliases = {port}
    for dev in list_serial_ports_with_stable_paths():
        values = {dev.device, dev.stable_path, dev.by_id, dev.by_path}
        if port in values:
            aliases.update(v for v in values if v)
    return aliases


def _match_serial_source(port: str):
    """Resolve label + live capture source for ``port``."""
    label = ""
    source = None
    if _config is None:
        return label, source
    aliases = _port_aliases(port)
    for d in _config.capture.serial:
        if d.serial_port and d.serial_port in aliases:
            label = d.label or ""
            source = _resolve_serial_source(label)
            return label, source
    if _config.capture.serial_port and _config.capture.serial_port in aliases:
        source = _resolve_serial_source("")
    return label, source


# Credit: javastraat/meshpoint 85fb576 — erase_all default False (plan flip)
class FlashRequest(BaseModel):
    board: str
    port: str
    tag: str = ""
    erase_all: bool = False


@router.post("/flash/stream")
async def flash_meshtastic_stream(
    req: FlashRequest,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
) -> StreamingResponse:
    """Download Meshtastic firmware and flash ``port`` via esptool.

    ``erase_all`` default False (keep settings / app-only). True erases all
    and also writes littlefs when present.
    Credit: javastraat/meshpoint 85fb576
    """
    if not req.board:
        raise HTTPException(400, "No board selected")

    from src.hal.usb_classifier import list_serial_ports_with_stable_paths

    real_ports = {
        value
        for dev in list_serial_ports_with_stable_paths()
        if dev.vid is not None
        for value in (dev.device, dev.stable_path, dev.by_id, dev.by_path)
        if value
    }
    if req.port not in real_ports:
        raise HTTPException(
            400, "Selected port is not a currently connected USB-serial device",
        )
    port = req.port
    label, source = _match_serial_source(port)

    async def body() -> AsyncIterator[bytes]:
        with audit.timed_action(
            user=claims.subject,
            action="meshtastic_firmware.flash",
            params={
                "board": req.board,
                "label": label,
                "port": port,
                "tag": req.tag or "latest",
                "erase_all": req.erase_all,
            },
        ) as ctx:
            yield _ndjson({
                "type": "line",
                "stream": "stdout",
                "text": (
                    f"Fetching Meshtastic {req.tag or 'latest'} firmware for "
                    f"{req.board.replace('-', ' ')}…"
                ),
            })
            loop = asyncio.get_running_loop()
            try:
                fw = await loop.run_in_executor(
                    None, _ensure_board_firmware_cached_sync, req.board, req.tag,
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
                "type": "line",
                "stream": "stdout",
                "text": f"Using Meshtastic {fw['version']} ({fw['mcu']}).",
            })

            # Always stop a matched source before esptool — reconnect /
            # half-open serial still races the port when connected=False.
            released = source is not None
            if released:
                yield _ndjson({
                    "type": "line",
                    "stream": "stdout",
                    "text": (
                        f"Releasing {port} ({source.name}"
                        f"{'' if source.connected else ' reconnect loop'})…"
                    ),
                })
                await source.stop()

            write_flash_args = ["0x0", str(fw["factory_bin"])]
            if req.erase_all and fw["littlefs_bin"] and fw["littlefs_offset"] is not None:
                write_flash_args += [
                    hex(fw["littlefs_offset"]), str(fw["littlefs_bin"]),
                ]

            # Credit: javastraat/meshpoint 85fb576 — erase toggle on flash stream
            cmd = [
                _esptool.resolve(), "--chip", fw["mcu"], "--port", port, "--baud", "921600",
                "write-flash", *(["--erase-all"] if req.erase_all else []),
                *write_flash_args,
            ]
            success = False
            async for chunk in _streamer.stream_subprocess(cmd):
                yield chunk
                event = json.loads(chunk)
                if event.get("type") == "result":
                    success = bool((event.get("result") or {}).get("success"))

            if released:
                yield _ndjson({
                    "type": "line",
                    "stream": "stdout",
                    "text": "Waiting for the board to finish rebooting…",
                })
                await asyncio.sleep(3.0)
                await source.start()
                yield _ndjson({
                    "type": "line",
                    "stream": "stdout",
                    "text": (
                        f"{source.name} reconnected on {port}."
                        if source.connected
                        else (
                            f"{source.name} did NOT reconnect -- "
                            "a service restart may be needed."
                        )
                    ),
                })

            ctx.set_result("success" if success else "error")

    return StreamingResponse(
        body(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
