"""Download and flash official MeshCore companion firmware onto a USB stick.

Companion to ``meshtastic_firmware_routes.py`` but for MeshCore -- same
overall shape (no compiling, download an official prebuilt release, flash
with ``esptool``), simpler in one real way: MeshCore's release assets
already ship as a single self-contained ``*-merged.bin`` per board (the
project's own ``merge-bin.py`` runs ``esptool merge_bin`` at build time),
confirmed by inspecting a real download -- it starts with the ESP32 image
magic byte (``0xE9``) at offset 0, so the whole file is written at ``0x0``
with no separate littlefs/metadata file or offset lookup needed the way
Meshtastic's ``.factory.bin``/``littlefs-*.bin`` pair required.

One real gotcha MeshCore has that Meshtastic doesn't: it tags THREE
separate GitHub releases per version bump -- ``companion-vX.Y.Z``,
``repeater-vX.Y.Z``, ``room-server-vX.Y.Z`` -- each with its own distinct
asset list. ``GET /releases/latest`` returns whichever of the three was
published most recently, which happens to currently be the companion one
each cycle but isn't guaranteed to stay that way -- so this module fetches
the releases LIST and explicitly picks the newest ``companion-`` tagged
one, rather than trusting ``/releases/latest`` directly (unlike this
project's own pre-existing "Check for updates" feature in
``meshcore_config_routes.py``, which does trust it -- a latent bug noted
but not fixed here, out of scope for this feature).

Curated board list (``_CURATED_BOARDS``) rather than MeshCore's full
board catalog (~50+ companion targets across ESP32 and nRF52 families,
the latter flashed via UF2 drag-and-drop, not esptool at all) -- just
this project's own hardware lineup, same reasoning as the Meshtastic
firmware routes' own curated list.
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import urllib.request
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

router = APIRouter(prefix="/api/config/meshcore/firmware", tags=["config", "meshcore"])

_config: Optional[AppConfig] = None
_meshcore_sources: list = []

# Lives under this install's own data/ dir (like the SQLite DB and the
# Meshtastic firmware cache) rather than a standalone /opt path -- data/
# is already excluded from install.sh's rsync and already owned by the
# meshpoint service user, so no separate mkdir/chown step is needed.
_CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "meshcore-firmware"
_RELEASES_LIST_URL = "https://api.github.com/repos/meshcore-dev/MeshCore/releases?per_page=20"
_ESPTOOL_BIN = "esptool"

# board slug -> (display label, release asset filename prefix, esptool
# chip). Same slugs as meshtastic_firmware_routes.py's own curated list
# where the physical board is identical, so a user picking hardware sees
# consistent naming across both flash cards. asset_prefix/chip aren't
# discoverable from a manifest the way Meshtastic's board->platform
# mapping is (MeshCore ships no per-release board manifest) -- both are
# just as hardcoded as the board list itself, confirmed against a real
# release's actual asset names before relying on them.
_CURATED_BOARDS: dict[str, dict[str, str]] = {
    "heltec-v3": {"label": "Heltec V3", "asset_prefix": "Heltec_v3", "chip": "esp32s3"},
    "tlora-v2-1-1_6": {
        "label": "TTGO LoRa32 V2.1-1.6",
        "asset_prefix": "LilyGo_TLora_V2_1_1_6",
        "chip": "esp32",
    },
}


def init_routes(config: AppConfig, meshcore_sources=None) -> None:
    global _config, _meshcore_sources
    _config = config
    _meshcore_sources = meshcore_sources or []


def _resolve_meshcore_source(label: str):
    """Mirrors meshcore_config_routes.py's own _resolve_companion_source --
    same ``meshcore_usb_<label>``/bare ``meshcore_usb`` naming convention."""
    name = f"meshcore_usb_{label}" if label else "meshcore_usb"
    for src in _meshcore_sources:
        if src.name == name:
            return src
    return None


def _ndjson(payload: dict) -> bytes:
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")


@router.get("/targets")
async def firmware_targets(_claims: SessionClaims = Depends(require_admin)) -> dict:
    """Curated board choices for the MeshCore flash pulldown."""
    return {
        "boards": [{"board": b, "label": v["label"]} for b, v in _CURATED_BOARDS.items()],
    }


def _fetch_json_sync(url: str) -> object:
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


def _latest_companion_release_sync() -> dict:
    """Fetches the releases list and returns the newest ``companion-``
    tagged one -- NOT ``/releases/latest``, which can return whichever of
    MeshCore's three per-version releases (companion/repeater/room-server)
    happened to publish last (see module docstring)."""
    releases = _fetch_json_sync(_RELEASES_LIST_URL)
    if not isinstance(releases, list):
        raise RuntimeError("Unexpected GitHub API response for MeshCore releases")
    for release in releases:
        if str(release.get("tag_name", "")).startswith("companion-"):
            return release
    raise RuntimeError("No companion-tagged MeshCore release found")


def _cache_dir_for(board: str, tag: str) -> Path:
    return _CACHE_DIR / board / tag


def _ensure_board_firmware_cached_sync(board: str) -> dict:
    """Downloads (if not already cached) the given board's latest
    official MeshCore companion release, returning::

        {"tag": str, "chip": str, "merged_bin": Path}

    Runs entirely off the event loop -- callers must wrap this in
    ``run_in_executor``.
    """
    spec = _CURATED_BOARDS[board]
    release = _latest_companion_release_sync()
    tag = release.get("tag_name", "")

    cache_dir = _cache_dir_for(board, tag)
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Cache under the asset's own real filename -- includes the build
    # hash, so a cache hit only happens for byte-identical content, never
    # a stale file silently reused under a different release's name.
    existing = list(cache_dir.glob(f"{spec['asset_prefix']}_companion_radio_usb-*-merged.bin"))
    if existing:
        return {"tag": tag, "chip": spec["chip"], "merged_bin": existing[0]}

    prefix = f"{spec['asset_prefix']}_companion_radio_usb-"
    asset = next(
        (
            a for a in release.get("assets", [])
            if a["name"].startswith(prefix) and a["name"].endswith("-merged.bin")
        ),
        None,
    )
    if asset is None:
        raise RuntimeError(
            f"Could not find a '{prefix}*-merged.bin' asset in {tag}",
        )

    dest = cache_dir / asset["name"]
    with tempfile.NamedTemporaryFile(
        suffix=".bin", dir=cache_dir, delete=False,
    ) as tmp:
        tmp_path = Path(tmp.name)
    try:
        _download_to_sync(asset["browser_download_url"], tmp_path)
        tmp_path.rename(dest)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

    return {"tag": tag, "chip": spec["chip"], "merged_bin": dest}


async def _stream_subprocess(cmd: list[str]) -> AsyncIterator[bytes]:
    """Same NDJSON subprocess-streaming shape as
    pocsag_firmware_routes.py/meshtastic_firmware_routes.py's own helper
    -- duplicated rather than shared, matching how those two already
    each keep their own copy since the route modules are independent."""
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
async def flash_meshcore_stream(
    req: FlashRequest,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
) -> StreamingResponse:
    """Downloads (if needed) the chosen board's latest official MeshCore
    companion release and writes it to one configured MeshCore USB
    companion's port with esptool -- full from-scratch flash
    (--erase-all), so this works whether the board is blank or currently
    running something else entirely (Meshtastic, extra/pocsag_companion,
    etc.), same reasoning as the Meshtastic flash route. Port is resolved
    server-side from capture.meshcore_usb by label, never trusted from
    the browser.
    """
    if req.board not in _CURATED_BOARDS:
        raise HTTPException(400, "Unknown board")

    port = None
    if _config is not None:
        for c in _config.capture.meshcore_usb:
            if (c.label or "") == (req.label or ""):
                port = c.serial_port
                break
    if not port:
        raise HTTPException(400, "No configured serial port for this device")

    source = _resolve_meshcore_source(req.label)

    async def body() -> AsyncIterator[bytes]:
        with audit.timed_action(
            user=claims.subject, action="meshcore_firmware.flash",
            params={"board": req.board, "label": req.label, "port": port},
        ) as ctx:
            yield _ndjson({
                "type": "line", "stream": "stdout",
                "text": f"Fetching latest MeshCore companion firmware for "
                        f"{_CURATED_BOARDS[req.board]['label']}…",
            })
            loop = asyncio.get_running_loop()
            try:
                fw = await loop.run_in_executor(
                    None, _ensure_board_firmware_cached_sync, req.board,
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
                "type": "line", "stream": "stdout",
                "text": f"Using MeshCore {fw['tag']} ({fw['chip']}).",
            })

            released = source is not None and source.connected
            if released:
                yield _ndjson({
                    "type": "line", "stream": "stdout",
                    "text": f"Releasing {port} ({source.name} was connected)…",
                })
                await source.stop()

            cmd = [
                _ESPTOOL_BIN, "--chip", fw["chip"], "--port", port, "--baud", "921600",
                "write-flash", "--erase-all", "0x0", str(fw["merged_bin"]),
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
