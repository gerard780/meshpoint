"""Download and flash official MeshCore companion firmware via esptool.

Fetches companion- tagged releases from meshcore-dev/MeshCore, caches
``*-merged.bin`` assets, and streams esptool write-flash as NDJSON.
Credit: javastraat/meshpoint (firmware flash port).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import tempfile
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

router = APIRouter(prefix="/api/config/meshcore/firmware", tags=["config", "meshcore"])

_config: Optional[AppConfig] = None
_meshcore_sources: list = []

_CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "meshcore-firmware"
_RELEASES_LIST_URL = (
    "https://api.github.com/repos/meshcore-dev/MeshCore/releases?per_page=20"
)
_FLAVORS = ("usb", "ble")
_MERGED_BIN_RE = re.compile(
    r"^(?P<board>.+)_companion_radio_(?P<flavor>usb|ble)-.+-merged\.bin$"
)

_http = GithubHttpClient()
_streamer = EspToolNdjsonStreamer()
_esptool = EspToolBinaryResolver()


def init_routes(config: AppConfig, meshcore_sources=None) -> None:
    global _config, _meshcore_sources
    _config = config
    _meshcore_sources = meshcore_sources or []


def _resolve_meshcore_source(label: str):
    """Match ``meshcore_usb`` / ``meshcore_usb_<label>`` capture sources."""
    name = f"meshcore_usb_{label}" if label else "meshcore_usb"
    for src in _meshcore_sources:
        if src.name == name:
            return src
    return None


def _ndjson(payload: dict) -> bytes:
    return _streamer.ndjson(payload)


@router.get("/targets")
async def firmware_targets(
    tag: str = "",
    flavor: str = "usb",
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Board choices for the flash pulldown (live from release assets)."""
    if flavor not in _FLAVORS:
        raise HTTPException(400, f"Unknown flavor, expected one of {_FLAVORS}")
    loop = asyncio.get_running_loop()
    try:
        release = await loop.run_in_executor(None, _resolve_release_sync, tag)
        boards = _board_list_from_release_sync(release, flavor)
    except Exception as exc:
        raise HTTPException(502, f"Could not fetch MeshCore board list: {exc}")
    return {"boards": boards, "tag": release.get("tag_name", "")}


@router.get("/releases")
async def firmware_releases(_claims: SessionClaims = Depends(require_admin)) -> dict:
    """Recent companion- releases for the version pulldown, newest first."""
    loop = asyncio.get_running_loop()
    try:
        releases = await loop.run_in_executor(None, _companion_releases_sync, 10)
    except Exception as exc:
        raise HTTPException(502, f"Could not fetch MeshCore releases: {exc}")
    return {
        "releases": [
            {"tag": r.get("tag_name", ""), "published_at": r.get("published_at")}
            for r in releases
        ],
    }


def _companion_releases_sync(limit: int = 10) -> list[dict]:
    """Return up to ``limit`` companion- tagged releases (not /releases/latest)."""
    releases = _http.fetch_json_sync(_RELEASES_LIST_URL)
    if not isinstance(releases, list):
        raise RuntimeError("Unexpected GitHub API response for MeshCore releases")
    companion_releases = [
        r for r in releases if str(r.get("tag_name", "")).startswith("companion-")
    ]
    if not companion_releases:
        raise RuntimeError("No companion-tagged MeshCore release found")
    return companion_releases[:limit]


def _companion_release_by_tag_sync(tag: str) -> dict:
    release = _http.fetch_json_sync(
        f"https://api.github.com/repos/meshcore-dev/MeshCore/releases/tags/{tag}"
    )
    if not isinstance(release, dict) or not str(release.get("tag_name", "")).startswith(
        "companion-"
    ):
        raise RuntimeError(f"'{tag}' is not a valid companion- release")
    return release


def _resolve_release_sync(tag: str) -> dict:
    return _companion_release_by_tag_sync(tag) if tag else _companion_releases_sync(1)[0]


def _board_list_from_release_sync(release: dict, flavor: str) -> list[dict]:
    boards: dict[str, str] = {}
    for asset in release.get("assets", []):
        m = _MERGED_BIN_RE.match(asset.get("name", ""))
        if m and m.group("flavor") == flavor:
            board = m.group("board")
            boards[board] = board.replace("_", " ")
    return [
        {"board": board, "label": label}
        for board, label in sorted(boards.items(), key=lambda kv: kv[1].casefold())
    ]


def _cache_dir_for(board: str, tag: str, flavor: str) -> Path:
    return _CACHE_DIR / board / tag / flavor


def _ensure_board_firmware_cached_sync(
    board: str, tag: str = "", flavor: str = "usb",
) -> dict:
    """Download (if needed) ``board`` merged.bin; return tag/flavor/path."""
    if flavor not in _FLAVORS:
        raise RuntimeError(f"Unknown flavor '{flavor}', expected one of {_FLAVORS}")
    release = _resolve_release_sync(tag)
    resolved_tag = release.get("tag_name", "")

    cache_dir = _cache_dir_for(board, resolved_tag, flavor)
    cache_dir.mkdir(parents=True, exist_ok=True)
    existing = list(cache_dir.glob(f"{board}_companion_radio_{flavor}-*-merged.bin"))
    if existing:
        return {"tag": resolved_tag, "flavor": flavor, "merged_bin": existing[0]}

    prefix = f"{board}_companion_radio_{flavor}-"
    asset = next(
        (
            a for a in release.get("assets", [])
            if a["name"].startswith(prefix) and a["name"].endswith("-merged.bin")
        ),
        None,
    )
    if asset is None:
        raise RuntimeError(
            f"Could not find a '{prefix}*-merged.bin' asset in {resolved_tag} -- "
            "this board/flavor combination isn't esptool-flashable in this release.",
        )

    dest = cache_dir / asset["name"]
    with tempfile.NamedTemporaryFile(
        suffix=".bin", dir=cache_dir, delete=False,
    ) as tmp:
        tmp_path = Path(tmp.name)
    try:
        _http.download_to_sync(asset["browser_download_url"], tmp_path)
        tmp_path.rename(dest)
        dest.chmod(0o644)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

    return {"tag": resolved_tag, "flavor": flavor, "merged_bin": dest}


def _port_aliases(port: str) -> set[str]:
    """All known path aliases for a connected USB-serial device."""
    from src.hal.usb_classifier import list_serial_ports_with_stable_paths

    aliases = {port}
    for dev in list_serial_ports_with_stable_paths():
        values = {dev.device, dev.stable_path, dev.by_id, dev.by_path}
        if port in values:
            aliases.update(v for v in values if v)
    return aliases


def _match_meshcore_source(port: str):
    """Resolve a live capture source for ``port`` (single MeshcoreUsbConfig)."""
    if _config is None:
        return "", None
    aliases = _port_aliases(port)
    mc = _config.capture.meshcore_usb
    if mc.serial_port and mc.serial_port in aliases:
        return "", _resolve_meshcore_source("")
    for src in _meshcore_sources:
        candidates = {
            getattr(src, "_resolved_port", None),
            getattr(src, "_configured_port", None),
            getattr(src, "serial_port", None),
        }
        if aliases & {c for c in candidates if c}:
            return "", src
    return "", None


# Credit: javastraat/meshpoint 85fb576 — erase_all default False (plan flip)
class FlashRequest(BaseModel):
    board: str
    port: str
    tag: str = ""
    flavor: str = "usb"
    erase_all: bool = False


@router.post("/flash/stream")
async def flash_meshcore_stream(
    req: FlashRequest,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
) -> StreamingResponse:
    """Download MeshCore companion firmware and flash ``port`` via esptool.

    ``erase_all`` default False (in-place upgrade). True runs ``--erase-all``.
    Credit: javastraat/meshpoint 85fb576
    """
    if not req.board:
        raise HTTPException(400, "No board selected")
    if req.flavor not in _FLAVORS:
        raise HTTPException(400, f"Unknown flavor, expected one of {_FLAVORS}")

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
    label, source = _match_meshcore_source(port)

    async def body() -> AsyncIterator[bytes]:
        with audit.timed_action(
            user=claims.subject,
            action="meshcore_firmware.flash",
            params={
                "board": req.board,
                "label": label,
                "port": port,
                "tag": req.tag or "latest",
                "flavor": req.flavor,
                "erase_all": req.erase_all,
            },
        ) as ctx:
            yield _ndjson({
                "type": "line",
                "stream": "stdout",
                "text": (
                    f"Fetching MeshCore {req.tag or 'latest'} ({req.flavor}) companion "
                    f"firmware for {req.board.replace('_', ' ')}…"
                ),
            })
            loop = asyncio.get_running_loop()
            try:
                fw = await loop.run_in_executor(
                    None,
                    _ensure_board_firmware_cached_sync,
                    req.board,
                    req.tag,
                    req.flavor,
                )
            except Exception as exc:
                logger.exception("MeshCore firmware fetch failed for %s", req.board)
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
                "text": f"Using MeshCore {fw['tag']} ({fw['flavor']}).",
            })

            released = source is not None and source.connected
            if released:
                yield _ndjson({
                    "type": "line",
                    "stream": "stdout",
                    "text": f"Releasing {port} ({source.name} was connected)…",
                })
                await source.stop()

            # Credit: javastraat/meshpoint 85fb576 — erase toggle on flash stream
            cmd = [
                _esptool.resolve(), "--chip", "auto", "--port", port, "--baud", "921600",
                "write-flash", *(["--erase-all"] if req.erase_all else []),
                "0x0", str(fw["merged_bin"]),
            ]
            success = False
            async for chunk in _streamer.stream_subprocess(cmd):
                yield chunk
                event = json.loads(chunk)
                if event.get("type") == "result":
                    success = bool((event.get("result") or {}).get("success"))

            if released:
                if req.flavor == "ble":
                    yield _ndjson({
                        "type": "line",
                        "stream": "stdout",
                        "text": (
                            f"Flashed BLE firmware -- {source.name} won't reconnect over "
                            "USB (that's expected); pair it with the MeshCore app instead."
                        ),
                    })
                else:
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
