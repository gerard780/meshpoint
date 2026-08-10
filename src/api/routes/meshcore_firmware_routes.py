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
one, rather than trusting ``/releases/latest`` directly. This project's
older "Check for updates" feature in ``meshcore_config_routes.py`` used
to trust ``/releases/latest`` directly -- a latent bug found while
building this module -- and has since been fixed to use the same
releases-list-plus-filter approach.

Board list is derived LIVE from whichever release+flavor is actually
selected (``_board_list_from_release_sync``), not a hardcoded curated
list -- confirmed against a real release (companion-v1.16.0): of ~76
distinct board targets, only 32 ship a self-contained ``*-merged.bin``
(ESP32 family, flashable with plain ``esptool write-flash``); the other
~44 are nRF52-family, shipping only ``.uf2``/``.zip`` for drag-and-drop
flashing, a completely different mechanism this route doesn't implement
-- filtering to ``*-merged.bin`` assets naturally excludes exactly the
boards that couldn't be flashed this way anyway, no separate allowlist
needed. ``--chip auto`` (esptool's own real-hardware auto-detection) is
used for every board instead of a hardcoded chip-per-board mapping --
MeshCore ships no per-release board->chip manifest, so a static mapping
would need hand-verifying ~32 boards' chip families against hardware
this project doesn't own; auto-detect sidesteps that risk entirely and
needs no maintenance as MeshCore adds boards over time.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
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
async def firmware_targets(
    tag: str = "", flavor: str = "usb",
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Board choices for the MeshCore flash pulldown, derived live from
    whichever release+flavor is actually selected (empty tag = latest) --
    see the module docstring for why this isn't a static list."""
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
    """Recent companion- releases for the version pulldown, newest first.
    The flash route still defaults to latest when no tag is given -- this
    is only for an operator who wants to deliberately pin an older (or
    re-pin a matching) version instead."""
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


_FLAVORS = ("usb", "ble")


def _companion_releases_sync(limit: int = 10) -> list[dict]:
    """Fetches the releases list and returns up to ``limit`` ``companion-``
    tagged ones, newest first -- NOT ``/releases/latest``, which can return
    whichever of MeshCore's three per-version releases (companion/repeater/
    room-server) happened to publish last (see module docstring)."""
    releases = _fetch_json_sync(_RELEASES_LIST_URL)
    if not isinstance(releases, list):
        raise RuntimeError("Unexpected GitHub API response for MeshCore releases")
    companion_releases = [
        r for r in releases if str(r.get("tag_name", "")).startswith("companion-")
    ]
    if not companion_releases:
        raise RuntimeError("No companion-tagged MeshCore release found")
    return companion_releases[:limit]


def _companion_release_by_tag_sync(tag: str) -> dict:
    """Fetches one specific companion- release by tag name (GitHub's
    single-release-by-tag endpoint, cheaper than re-listing)."""
    release = _fetch_json_sync(
        f"https://api.github.com/repos/meshcore-dev/MeshCore/releases/tags/{tag}"
    )
    if not isinstance(release, dict) or not str(release.get("tag_name", "")).startswith(
        "companion-"
    ):
        raise RuntimeError(f"'{tag}' is not a valid companion- release")
    return release


def _resolve_release_sync(tag: str) -> dict:
    """Empty tag -> latest companion- release; otherwise that exact tag."""
    return _companion_release_by_tag_sync(tag) if tag else _companion_releases_sync(1)[0]


_MERGED_BIN_RE = re.compile(r"^(?P<board>.+)_companion_radio_(?P<flavor>usb|ble)-.+-merged\.bin$")


def _board_list_from_release_sync(release: dict, flavor: str) -> list[dict]:
    """Every board this release+flavor can actually esptool-flash --
    derived from real asset filenames, not a hardcoded list (see module
    docstring for why: only the ESP32-family boards shipping a
    self-contained ``*-merged.bin`` are flashable this way at all; a
    board that only ships ``.uf2``/``.zip`` needs drag-and-drop flashing,
    a mechanism this route doesn't implement, so it's correctly absent
    here rather than needing a separate exclusion list)."""
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
    """Downloads (if not already cached) the given board's official
    MeshCore companion release, returning::

        {"tag": str, "flavor": str, "merged_bin": Path}

    ``board`` is the release asset's own filename prefix (e.g.
    "Heltec_v3") -- there's no separate curated-board lookup anymore,
    see module docstring. ``tag`` empty means "latest companion-
    release". ``flavor`` is ``"usb"`` (talks to this dashboard's own
    capture sources over serial -- the default, and the only flavor
    that can ever connect to this app) or ``"ble"`` (Bluetooth-only
    firmware, e.g. for flashing a spare board for someone to pair with
    the official MeshCore phone app instead -- never reconnects to
    this dashboard's own USB capture source afterward, by design,
    since the firmware no longer speaks the companion USB serial
    protocol at all).

    Runs entirely off the event loop -- callers must wrap this in
    ``run_in_executor``.
    """
    if flavor not in _FLAVORS:
        raise RuntimeError(f"Unknown flavor '{flavor}', expected one of {_FLAVORS}")
    release = _resolve_release_sync(tag)
    resolved_tag = release.get("tag_name", "")

    cache_dir = _cache_dir_for(board, resolved_tag, flavor)
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Cache under the asset's own real filename -- includes the build
    # hash, so a cache hit only happens for byte-identical content, never
    # a stale file silently reused under a different release's name.
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
        _download_to_sync(asset["browser_download_url"], tmp_path)
        tmp_path.rename(dest)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

    return {"tag": resolved_tag, "flavor": flavor, "merged_bin": dest}


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
    port: str
    tag: str = ""
    flavor: str = "usb"
    erase_all: bool = True


@router.post("/flash/stream")
async def flash_meshcore_stream(
    req: FlashRequest,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
) -> StreamingResponse:
    """Downloads (if needed) the chosen board's official MeshCore
    companion release -- latest, or a specific ``tag`` if pinned -- and
    writes it to ``port`` with esptool.

    ``erase_all`` (default ``True``) runs esptool's ``--erase-all``
    first, so this works whether the board is blank or currently running
    something else entirely (Meshtastic, extra/pocsag_companion, etc.),
    same reasoning as the Meshtastic flash route. Passing ``False``
    skips it -- an in-place upgrade of a board already running MeshCore.
    Unlike Meshtastic, there's no separate write to skip here: the
    ``*-merged.bin`` written at ``0x0`` is only bootloader+partition-
    table+app (confirmed against the real board_build.partitions =
    min_spiffs.csv layout), ending well under the ``spiffs`` partition at
    0x3D0000 where DataStore's identity/contacts/channels actually live
    -- so leaving out ``--erase-all`` alone is enough to leave that
    untouched, no code path change beyond the one flag.

    ``port`` can be ANY currently-connected USB-serial device, not just
    one already added as a configured MeshCore companion -- flashing a
    spare board (or a friend's board, just passing through) shouldn't
    require adding-then-removing a permanent companion entry first. It's
    still validated against the live enumeration below (same one
    GET /api/config/serial-ports uses), never trusted as a raw path
    from the browser. If it happens to match a configured companion's
    port, that companion's capture source is stopped before flashing
    and restarted after, same as before; if it doesn't match anything
    configured, there's nothing to stop/restart, which is exactly right
    for a board that isn't part of this box's own config at all.

    ``flavor`` "ble" flashes Bluetooth-only firmware (e.g. for a spare
    board headed to someone who wants to pair it with the official
    MeshCore phone app) -- it deliberately does NOT attempt to
    reconnect the USB capture source afterward, since BLE firmware no
    longer speaks the companion USB serial protocol at all.
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
        raise HTTPException(400, "Selected port is not a currently connected USB-serial device")
    port = req.port

    label = ""
    source = None
    if _config is not None:
        for c in _config.capture.meshcore_usb:
            if c.serial_port == port:
                label = c.label or ""
                source = _resolve_meshcore_source(label)
                break

    async def body() -> AsyncIterator[bytes]:
        with audit.timed_action(
            user=claims.subject, action="meshcore_firmware.flash",
            params={
                "board": req.board, "label": label, "port": port,
                "tag": req.tag or "latest", "flavor": req.flavor,
                "erase_all": req.erase_all,
            },
        ) as ctx:
            yield _ndjson({
                "type": "line", "stream": "stdout",
                "text": f"Fetching MeshCore {req.tag or 'latest'} ({req.flavor}) companion "
                        f"firmware for {req.board.replace('_', ' ')}…",
            })
            loop = asyncio.get_running_loop()
            try:
                fw = await loop.run_in_executor(
                    None, _ensure_board_firmware_cached_sync, req.board, req.tag, req.flavor,
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
                "text": f"Using MeshCore {fw['tag']} ({fw['flavor']}).",
            })

            released = source is not None and source.connected
            if released:
                yield _ndjson({
                    "type": "line", "stream": "stdout",
                    "text": f"Releasing {port} ({source.name} was connected)…",
                })
                await source.stop()

            # --chip auto: esptool detects the real connected chip family
            # itself rather than trusting a hardcoded board->chip mapping
            # this project would otherwise have to hand-verify against
            # hardware it doesn't own (see module docstring).
            cmd = [
                _ESPTOOL_BIN, "--chip", "auto", "--port", port, "--baud", "921600",
                "write-flash", *(["--erase-all"] if req.erase_all else []),
                "0x0", str(fw["merged_bin"]),
            ]
            success = False
            async for chunk in _stream_subprocess(cmd):
                yield chunk
                event = json.loads(chunk)
                if event.get("type") == "result":
                    success = bool((event.get("result") or {}).get("success"))

            if released:
                if req.flavor == "ble":
                    # BLE firmware doesn't speak the companion USB serial
                    # protocol at all -- trying to reconnect would just
                    # time out and read as a failure, so don't pretend
                    # this dashboard could ever talk to it again.
                    yield _ndjson({
                        "type": "line", "stream": "stdout",
                        "text": f"Flashed BLE firmware -- {source.name} won't reconnect over "
                                f"USB (that's expected); pair it with the MeshCore app instead.",
                    })
                else:
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
