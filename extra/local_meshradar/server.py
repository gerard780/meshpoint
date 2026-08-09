#!/usr/bin/env python3
"""Local, self-hosted stand-in for the meshradar.io upstream endpoint.

Meshpoint's own UpstreamClient (src/api/upstream_client.py) speaks a plain
JSON-over-WebSocket protocol: it sends "register" once, "packet" per
decoded packet, and "heartbeat" every 9 minutes, and never requires a
response to any of them -- it only ever reacts to an inbound
{"type": "command", ...} message, which this receiver never sends. That
makes a receive-only server a complete, valid implementation.

Point a real Meshpoint's config/local.yaml at this server:

    upstream:
      enabled: true
      url: "ws://<this-machine>:8765"
      auth_token: "<a real mr1_... key from meshradar.io>"

The auth_token is only ever checked locally by Meshpoint itself
(src/activation.py, an offline Ed25519 signature check) before it will
start the upstream client at all -- this server never verifies it, and
doesn't need to. The X-Device-Id / Authorization headers are logged on
connect for visibility, nothing more.

Not affiliated with or endorsed by meshradar.io. Unofficial dev tooling.
"""

from __future__ import annotations

import argparse
import asyncio
import hmac
import json
import logging
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import websockets

logger = logging.getLogger("local_meshradar")

VIEWER_HTML_PATH = Path(__file__).parent / "viewer.html"
DASHBOARD_HTML_PATH = Path(__file__).parent / "dashboard.html"
LOGIN_HTML_PATH = Path(__file__).parent / "login.html"
MANIFEST_PATH = Path(__file__).parent / "manifest.json"
ASSETS_DIR = Path(__file__).parent / "assets"
_ASSET_CONTENT_TYPES = {".png": "image/png", ".svg": "image/svg+xml"}

# Single hardcoded credential pair -- this tool is meant for a trusted
# local network (see README's "No auth enforcement" section, which this
# closes the gap on); it's not a multi-user system, so one shared login
# is enough to keep the dashboard off casual LAN/portscan discovery.
AUTH_USERNAME = "viewer"
AUTH_PASSWORD = "itoldyoualready"
SESSION_COOKIE_NAME = "local_meshradar_session"

# In-memory only -- sessions don't survive a server restart. Fine here:
# there's no "remember me" requirement, and losing sessions on restart is
# actually a feature (no stale acceptance of a cookie from a previous,
# possibly-redeployed server).
_valid_sessions: set[str] = set()


def _check_credentials(username: str, password: str) -> bool:
    # Constant-time comparisons so a timing side-channel can't leak how
    # many leading characters of the real value a guess got right.
    return (
        hmac.compare_digest(username, AUTH_USERNAME)
        and hmac.compare_digest(password, AUTH_PASSWORD)
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_hours_ago(hours: float) -> str:
    from datetime import timedelta
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


# ── storage ─────────────────────────────────────────────────────────

def init_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS devices (
                device_id TEXT PRIMARY KEY,
                device_name TEXT,
                long_name TEXT,
                short_name TEXT,
                latitude REAL,
                longitude REAL,
                altitude REAL,
                hardware_description TEXT,
                firmware_version TEXT,
                ip_address TEXT,
                first_seen TEXT,
                last_seen TEXT
            );

            CREATE TABLE IF NOT EXISTS nodes (
                device_id TEXT,
                node_id TEXT,
                long_name TEXT,
                short_name TEXT,
                hardware_model TEXT,
                firmware_version TEXT,
                protocol TEXT,
                role TEXT,
                public_key TEXT,
                latitude REAL,
                longitude REAL,
                altitude REAL,
                last_heard TEXT,
                first_seen TEXT,
                packet_count INTEGER,
                display_name TEXT,
                has_position INTEGER,
                latest_signal_json TEXT,
                latest_telemetry_json TEXT,
                updated_at TEXT,
                PRIMARY KEY (device_id, node_id)
            );

            CREATE TABLE IF NOT EXISTS packets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT,
                packet_id TEXT,
                source_id TEXT,
                destination_id TEXT,
                protocol TEXT,
                packet_type TEXT,
                hop_limit INTEGER,
                hop_start INTEGER,
                hop_count INTEGER,
                channel_hash INTEGER,
                want_ack INTEGER,
                via_mqtt INTEGER,
                relay_node INTEGER,
                decoded_payload_json TEXT,
                decrypted INTEGER,
                capture_source TEXT,
                timestamp TEXT,
                rssi REAL,
                snr REAL,
                frequency_mhz REAL,
                spreading_factor INTEGER,
                bandwidth_khz REAL,
                coding_rate TEXT,
                signal_quality_percent REAL,
                received_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_packets_received_at ON packets(received_at);

            CREATE TABLE IF NOT EXISTS heartbeats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT,
                timestamp TEXT,
                packets_since_last INTEGER,
                stats_json TEXT,
                received_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_heartbeats_received_at ON heartbeats(received_at);
            """
        )
        conn.commit()
        # devices.ip_address didn't exist in earlier schema versions --
        # CREATE TABLE IF NOT EXISTS above only helps a brand-new database;
        # an existing local_meshradar.db needs the column added explicitly.
        try:
            conn.execute("ALTER TABLE devices ADD COLUMN ip_address TEXT")
            conn.commit()
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise
    finally:
        conn.close()


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ── message handlers ───────────────────────────────────────────────

def handle_register(db_path: str, message: dict) -> None:
    device = message.get("device") or {}
    device_id = device.get("device_id")
    if not device_id:
        logger.warning("register message missing device_id, ignoring")
        return

    # Stamped by ws_handler from websocket.remote_address just before this
    # runs -- the register message itself never carries an IP, the TCP
    # connection is the only place we can see one.
    peer_ip = message.get("_peer_ip")

    now = _now()
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO devices (
                device_id, device_name, long_name, short_name,
                latitude, longitude, altitude,
                hardware_description, firmware_version, ip_address,
                first_seen, last_seen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                device_name=excluded.device_name,
                long_name=excluded.long_name,
                short_name=excluded.short_name,
                latitude=excluded.latitude,
                longitude=excluded.longitude,
                altitude=excluded.altitude,
                hardware_description=excluded.hardware_description,
                firmware_version=excluded.firmware_version,
                ip_address=excluded.ip_address,
                last_seen=excluded.last_seen
            """,
            (
                device_id, device.get("device_name"), device.get("long_name"),
                device.get("short_name"), device.get("latitude"),
                device.get("longitude"), device.get("altitude"),
                device.get("hardware_description"), device.get("firmware_version"),
                peer_ip, now, now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    logger.info("register: device_id=%s name=%s", device_id, device.get("device_name"))


def handle_packet(db_path: str, message: dict) -> None:
    device_id = message.get("device_id")
    data = message.get("data") or {}
    signal = data.get("signal") or {}

    conn = _connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO packets (
                device_id, packet_id, source_id, destination_id, protocol,
                packet_type, hop_limit, hop_start, hop_count, channel_hash,
                want_ack, via_mqtt, relay_node, decoded_payload_json,
                decrypted, capture_source, timestamp,
                rssi, snr, frequency_mhz, spreading_factor, bandwidth_khz,
                coding_rate, signal_quality_percent, received_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                device_id, data.get("packet_id"), data.get("source_id"),
                data.get("destination_id"), data.get("protocol"),
                data.get("packet_type"), data.get("hop_limit"),
                data.get("hop_start"), data.get("hop_count"),
                data.get("channel_hash"), data.get("want_ack"),
                data.get("via_mqtt"), data.get("relay_node"),
                json.dumps(data.get("decoded_payload")),
                data.get("decrypted"), data.get("capture_source"),
                data.get("timestamp"),
                signal.get("rssi"), signal.get("snr"),
                signal.get("frequency_mhz"), signal.get("spreading_factor"),
                signal.get("bandwidth_khz"), signal.get("coding_rate"),
                signal.get("signal_quality_percent"),
                _now(),
            ),
        )
        _touch_node_from_packet(
            conn, device_id, data.get("source_id"), data.get("protocol"),
            data.get("packet_type"), data.get("decoded_payload"),
            data.get("timestamp"), signal,
        )
        conn.commit()
    finally:
        conn.close()


def _touch_node_from_packet(
    conn: sqlite3.Connection, device_id: str, source_id: str | None,
    protocol: str | None, packet_type: str | None, decoded_payload: dict | None,
    timestamp: str | None, signal: dict,
) -> None:
    """Make sure a node row exists the moment we see ANY packet from it,
    and learn its identity immediately from a NODEINFO packet rather than
    waiting on the next heartbeat.

    heartbeat.nodes[] (the other source of nodes rows) only arrives every
    ~9 minutes and only names nodes that "changed" -- a node whose only
    activity so far is a single chat/text packet wouldn't show up in the
    Nodes panel at all until the next heartbeat happens to include it.
    This creates a minimal placeholder immediately (protocol, last_heard,
    latest signal, a running packet_count).

    A NODEINFO packet's decoded_payload carries long_name/short_name/
    hw_model/role/public_key directly -- the same fields
    src/decode/meshcore_decoder.py's/portnum_handlers.py's own
    extract_node_update() reads to build a live Node update per-packet in
    the real app. We mirror that here instead of only ever getting a
    name via the heartbeat roster (which is also where the earlier
    PD2EMC TAG2 case showed a real gap: some MeshCore names apparently
    live only in the companion's own synced contact list, never in
    concentrator.db's nodes.long_name at all -- this at least catches
    every name that *does* arrive via an actual NODEINFO packet, live,
    the moment it's heard).
    """
    if not source_id:
        return
    # The real app formats Packet.source_id WITH a leading "!" but
    # Node.node_id WITHOUT one, for the exact same physical node (visible
    # comparing any packet feed row against /api/nodes). Normalize here
    # so a packet-triggered row lands on the SAME (device_id, node_id) as
    # the heartbeat-sourced one instead of forking a third identity for
    # this node that the heartbeat path never touches.
    node_id = source_id[1:] if source_id.startswith("!") else source_id
    now = _now()
    ts = timestamp or now
    payload = decoded_payload if packet_type == "nodeinfo" and decoded_payload else {}
    long_name = payload.get("long_name")
    short_name = payload.get("short_name")
    hardware_model = payload.get("hw_model") or payload.get("hardware_model")
    role = payload.get("role")
    public_key = payload.get("public_key")
    display_name = long_name or short_name or f"!{node_id}"
    conn.execute(
        """
        INSERT INTO nodes (
            device_id, node_id, protocol, long_name, short_name,
            hardware_model, role, public_key,
            last_heard, first_seen, packet_count, display_name,
            has_position, latest_signal_json, latest_telemetry_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 0, ?, NULL, ?)
        ON CONFLICT(device_id, node_id) DO UPDATE SET
            long_name = COALESCE(NULLIF(excluded.long_name, ''), nodes.long_name),
            short_name = COALESCE(NULLIF(excluded.short_name, ''), nodes.short_name),
            hardware_model = COALESCE(NULLIF(excluded.hardware_model, ''), nodes.hardware_model),
            role = COALESCE(NULLIF(excluded.role, ''), nodes.role),
            public_key = COALESCE(NULLIF(excluded.public_key, ''), nodes.public_key),
            display_name = COALESCE(
                NULLIF(excluded.long_name, ''), NULLIF(excluded.short_name, ''), nodes.display_name
            ),
            last_heard = MAX(excluded.last_heard, nodes.last_heard),
            packet_count = nodes.packet_count + 1,
            latest_signal_json = excluded.latest_signal_json,
            updated_at = excluded.updated_at
        """,
        (
            device_id, node_id, protocol, long_name, short_name,
            hardware_model, role, public_key, ts, ts,
            display_name, json.dumps(signal) if signal else None,
            now,
        ),
    )


def _upsert_node(conn: sqlite3.Connection, device_id: str, node: dict, updated_at: str) -> None:
    """Upsert one node dict (heartbeat.nodes[] shape) into the nodes table.

    Shared by handle_heartbeat (live) and import_concentrator_db.py
    (backfill from a real Meshpoint's own concentrator.db) so both paths
    stay in sync with the schema instead of duplicating this SQL.
    """
    node_id = node.get("node_id")
    if not node_id:
        return
    # Same normalization as _touch_node_from_packet: the heartbeat roster
    # has been observed reporting this node's id WITH a leading "!" too
    # (inconsistently -- not just Packet.source_id), which would otherwise
    # fork yet another duplicate identity this function never merges.
    node_id = node_id[1:] if node_id.startswith("!") else node_id
    conn.execute(
        """
        INSERT INTO nodes (
            device_id, node_id, long_name, short_name, hardware_model,
            firmware_version, protocol, role, public_key,
            latitude, longitude, altitude, last_heard, first_seen,
            packet_count, display_name, has_position,
            latest_signal_json, latest_telemetry_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(device_id, node_id) DO UPDATE SET
            long_name=COALESCE(NULLIF(excluded.long_name, ''), nodes.long_name),
            short_name=COALESCE(NULLIF(excluded.short_name, ''), nodes.short_name),
            hardware_model=COALESCE(NULLIF(excluded.hardware_model, ''), nodes.hardware_model),
            firmware_version=COALESCE(NULLIF(excluded.firmware_version, ''), nodes.firmware_version),
            protocol=COALESCE(NULLIF(excluded.protocol, ''), nodes.protocol),
            role=COALESCE(NULLIF(excluded.role, ''), nodes.role),
            public_key=COALESCE(NULLIF(excluded.public_key, ''), nodes.public_key),
            latitude=COALESCE(excluded.latitude, nodes.latitude),
            longitude=COALESCE(excluded.longitude, nodes.longitude),
            altitude=COALESCE(excluded.altitude, nodes.altitude),
            last_heard=excluded.last_heard,
            packet_count=excluded.packet_count,
            display_name=COALESCE(
                NULLIF(excluded.long_name, ''), NULLIF(excluded.short_name, ''), nodes.display_name
            ),
            has_position=excluded.has_position,
            latest_signal_json=excluded.latest_signal_json,
            latest_telemetry_json=excluded.latest_telemetry_json,
            updated_at=excluded.updated_at
        """,
        (
            device_id, node_id, node.get("long_name"), node.get("short_name"),
            node.get("hardware_model"), node.get("firmware_version"),
            node.get("protocol"), node.get("role"), node.get("public_key"),
            node.get("latitude"), node.get("longitude"), node.get("altitude"),
            node.get("last_heard"), node.get("first_seen"),
            node.get("packet_count"), node.get("display_name"),
            node.get("has_position"),
            json.dumps(node.get("latest_signal")),
            json.dumps(node.get("latest_telemetry")),
            updated_at,
        ),
    )


def handle_heartbeat(db_path: str, message: dict) -> None:
    device_id = message.get("device_id")
    stats = message.get("stats") or {}
    now = _now()

    conn = _connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO heartbeats (device_id, timestamp, packets_since_last, stats_json, received_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (device_id, message.get("timestamp"), message.get("packets_since_last"),
             json.dumps(stats), now),
        )
        for node in message.get("nodes") or []:
            _upsert_node(conn, device_id, node, now)
        conn.commit()
    finally:
        conn.close()
    logger.info(
        "heartbeat: device_id=%s packets_since_last=%s nodes=%d",
        device_id, message.get("packets_since_last"), len(message.get("nodes") or []),
    )


_HANDLERS = {
    "register": handle_register,
    "packet": handle_packet,
    "heartbeat": handle_heartbeat,
}

# Browser tabs on the dashboard connect to ws://.../live (no X-Device-Id)
# purely to be told "something changed, go refetch" -- see _broadcast_update.
# Kept separate from the Meshpoint-ingest connections above; a dead browser
# tab is pruned on next broadcast rather than actively watched for.
_browser_subscribers: set = set()


async def _broadcast_update(kind: str) -> None:
    if not _browser_subscribers:
        return
    message = json.dumps({"type": "update", "kind": kind})
    dead = set()
    for ws in _browser_subscribers:
        try:
            await ws.send(message)
        except Exception:
            dead.add(ws)
    _browser_subscribers.difference_update(dead)


# ── websocket ingest ────────────────────────────────────────────────

async def ws_handler(websocket, db_path: str) -> None:
    if websocket.request.path.rstrip("/").endswith("/live"):
        await _browser_subscriber_handler(websocket)
        return

    headers = websocket.request.headers
    device_id = headers.get("x-device-id", "?")
    auth_present = "authorization" in headers
    peer = websocket.remote_address
    logger.info(
        "connected: peer=%s x-device-id=%s auth=%s",
        peer, device_id, "present" if auth_present else "MISSING",
    )

    try:
        async for raw in websocket:
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("non-JSON message from %s: %s", device_id, raw[:120])
                continue

            msg_type = message.get("type")
            handler = _HANDLERS.get(msg_type)
            if handler is None:
                logger.debug("ignoring message type=%s from %s", msg_type, device_id)
                continue

            if msg_type == "register" and peer:
                message["_peer_ip"] = peer[0]

            try:
                # Handlers are synchronous sqlite3 calls -- offload so one
                # slow write can't stall the event loop for other connections.
                await asyncio.to_thread(handler, db_path, message)
                await _broadcast_update(msg_type)
            except Exception:
                logger.exception("failed to handle %s message from %s", msg_type, device_id)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        logger.info("disconnected: peer=%s x-device-id=%s", peer, device_id)


async def _browser_subscriber_handler(websocket) -> None:
    _browser_subscribers.add(websocket)
    logger.info("dashboard live-subscriber connected: peer=%s (total=%d)",
                websocket.remote_address, len(_browser_subscribers))
    try:
        await websocket.wait_closed()
    finally:
        _browser_subscribers.discard(websocket)
        logger.info("dashboard live-subscriber disconnected (total=%d)", len(_browser_subscribers))


# ── minimal HTTP viewer + JSON API ─────────────────────────────────

def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]


def make_http_handler(db_path: str, ws_port: int):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args) -> None:  # noqa: A002 -- stdlib signature
            logger.debug("http: " + fmt, *args)

        def _send_json(self, payload, status: int = 200, extra_headers: dict | None = None) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            for key, value in (extra_headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def _session_token(self) -> str | None:
            cookie_header = self.headers.get("Cookie")
            if not cookie_header:
                return None
            cookie: SimpleCookie = SimpleCookie()
            cookie.load(cookie_header)
            morsel = cookie.get(SESSION_COOKIE_NAME)
            return morsel.value if morsel else None

        def _authenticated(self) -> bool:
            token = self._session_token()
            return token is not None and token in _valid_sessions

        def _redirect(self, location: str) -> None:
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _send_file(self, path: Path, content_type: str) -> None:
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, path: Path, inject_ws_port: bool = False) -> None:
            text = path.read_text(encoding="utf-8")
            if inject_ws_port:
                text = text.replace(
                    "<head>",
                    f"<head>\n<script>window.WS_PORT = {ws_port};</script>",
                    1,
                )
            body = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            # This file changes often during development and is small
            # (re-read from disk on every request anyway) -- never let a
            # browser cache a stale copy of the JS across a redeploy.
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 -- stdlib method name
            parsed = urlparse(self.path)

            if parsed.path == "/logout":
                _valid_sessions.discard(self._session_token())
                self.send_response(302)
                self.send_header("Location", "/login")
                self.send_header("Set-Cookie", f"{SESSION_COOKIE_NAME}=; Path=/; Max-Age=0")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            is_public = (
                parsed.path in ("/login", "/login.html")
                or parsed.path == "/manifest.json"
                or parsed.path.startswith("/assets/")
            )
            if not is_public and not self._authenticated():
                if parsed.path.startswith("/api/"):
                    self._send_json({"error": "unauthorized"}, status=401)
                else:
                    self._redirect(f"/login?next={quote(self.path, safe='')}")
                return

            conn = _connect(db_path)
            try:
                if parsed.path in ("/login", "/login.html"):
                    self._send_html(LOGIN_HTML_PATH)
                elif parsed.path in ("/", "/index.html", "/dashboard", "/dashboard.html"):
                    self._send_html(DASHBOARD_HTML_PATH, inject_ws_port=True)
                elif parsed.path in ("/viewer", "/viewer.html"):
                    self._send_html(VIEWER_HTML_PATH)
                elif parsed.path == "/manifest.json":
                    self._send_file(MANIFEST_PATH, "application/manifest+json")
                elif parsed.path.startswith("/assets/"):
                    # Strip to a bare filename before touching the filesystem --
                    # this is the only place a request path reaches disk, and it
                    # must never be able to escape ASSETS_DIR (e.g. "../server.py").
                    name = Path(parsed.path).name
                    suffix = Path(name).suffix.lower()
                    asset_path = ASSETS_DIR / name
                    if name and suffix in _ASSET_CONTENT_TYPES and asset_path.is_file():
                        self._send_file(asset_path, _ASSET_CONTENT_TYPES[suffix])
                    else:
                        self._send_json({"error": "not found"}, status=404)
                elif parsed.path == "/api/stats":
                    devices = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
                    nodes_unique = conn.execute(
                        "SELECT COUNT(DISTINCT node_id) FROM nodes"
                    ).fetchone()[0]
                    nodes_rows = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
                    packets_total = conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0]
                    packets_last_hour = conn.execute(
                        "SELECT COUNT(*) FROM packets WHERE received_at >= ?",
                        (_iso_hours_ago(1),),
                    ).fetchone()[0]
                    self._send_json({
                        "devices": devices,
                        "nodes_unique": nodes_unique,
                        "nodes_rows": nodes_rows,
                        "packets_total": packets_total,
                        "packets_last_hour": packets_last_hour,
                    })
                elif parsed.path == "/api/devices":
                    rows = conn.execute(
                        "SELECT * FROM devices ORDER BY last_seen DESC"
                    ).fetchall()
                    self._send_json(_rows_to_dicts(rows))
                elif parsed.path == "/api/nodes":
                    rows = conn.execute(
                        "SELECT * FROM nodes ORDER BY last_heard DESC"
                    ).fetchall()
                    self._send_json(_rows_to_dicts(rows))
                elif parsed.path == "/api/packets":
                    qs = parse_qs(parsed.query)
                    limit = min(int(qs.get("limit", ["100"])[0]), 500)
                    rows = conn.execute(
                        "SELECT * FROM packets ORDER BY received_at DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
                    self._send_json(_rows_to_dicts(rows))
                else:
                    self._send_json({"error": "not found"}, status=404)
            finally:
                conn.close()

        def do_POST(self) -> None:  # noqa: N802 -- stdlib method name
            parsed = urlparse(self.path)
            if parsed.path != "/api/auth/login":
                self._send_json({"error": "not found"}, status=404)
                return

            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                body = {}

            username = str(body.get("username", ""))
            password = str(body.get("password", ""))
            if not _check_credentials(username, password):
                self._send_json({"ok": False, "detail": "invalid_credentials"}, status=401)
                return

            token = secrets.token_urlsafe(32)
            _valid_sessions.add(token)
            self._send_json(
                {"ok": True},
                extra_headers={
                    "Set-Cookie": f"{SESSION_COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax",
                },
            )

    return Handler


# ── entry point ─────────────────────────────────────────────────────

async def run_ws_server(host: str, port: int, db_path: str) -> None:
    async def handler(websocket):
        await ws_handler(websocket, db_path)

    async with websockets.serve(handler, host, port):
        logger.info("WebSocket ingest listening on ws://%s:%d", host, port)
        await asyncio.Future()  # run forever


def run_http_server(host: str, port: int, db_path: str, ws_port: int) -> None:
    httpd = ThreadingHTTPServer((host, port), make_http_handler(db_path, ws_port))
    logger.info("Viewer + JSON API listening on http://%s:%d", host, port)
    httpd.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ws-host", default="0.0.0.0")
    parser.add_argument("--ws-port", type=int, default=8765)
    parser.add_argument("--http-host", default="0.0.0.0")
    parser.add_argument("--http-port", type=int, default=8080)
    parser.add_argument(
        "--db", default=str(Path(__file__).parent / "local_meshradar.db")
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    init_db(args.db)

    http_thread = threading.Thread(
        target=run_http_server,
        args=(args.http_host, args.http_port, args.db, args.ws_port),
        daemon=True,
    )
    http_thread.start()

    try:
        asyncio.run(run_ws_server(args.ws_host, args.ws_port, args.db))
    except KeyboardInterrupt:
        logger.info("shutting down")


if __name__ == "__main__":
    main()
