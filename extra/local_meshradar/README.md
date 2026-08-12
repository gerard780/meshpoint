# Local Meshradar

A self-hosted, receive-only stand-in for the `wss://api.meshradar.io` upstream
endpoint that Meshpoint's own `UpstreamClient` (`src/api/upstream_client.py`)
already knows how to talk to. Point one or more Meshpoint units at this
server instead of (or in addition to testing) the real cloud, and their
node/packet/stats data lands in a local SQLite database you can browse from
a plain web page.

**Unofficial dev tooling. Not affiliated with or endorsed by meshradar.io.**
Nothing here is a general-purpose Meshradar server implementation — it only
handles what Meshpoint's own client actually sends.

## Why this works

Meshpoint's upstream client sends `register` (once per connection), `packet`
(per decoded packet), and `heartbeat` (every 9 minutes, with rolled-up stats
and a roster of nodes that changed) as plain JSON text frames over a
WebSocket. It never waits for or requires a response to any of them — the
only thing it reacts to from the server is an inbound
`{"type": "command", ...}` message, which this receiver never sends. A
server that only ever *receives* is a complete, valid implementation of the
half of the protocol Meshpoint actually depends on.

The `Authorization: Bearer <token>` / `X-Device-Id` headers are logged on
connect for visibility only — this server never validates the token (it
can't; only meshradar.io holds the private key that signs real tokens).
Meshpoint itself validates its own token once at startup
(`src/activation.py`, an offline Ed25519 signature check) before it will
even try to connect anywhere — that check has nothing to do with which
server `upstream.url` actually points at.

## Run it

```bash
pip install -r requirements.txt
python3 server.py
```

Two listeners start:

- `ws://0.0.0.0:8765` — the ingest endpoint Meshpoint connects to. Browser
  tabs also connect here, at `ws://.../live`, for real-time dashboard
  updates (see below) — same port, different path, nothing to configure
  separately.
- `http://0.0.0.0:8080` — the dashboard/viewer pages and their JSON API
  (`/api/identity`, `/api/devices`, `/api/nodes`, `/api/packets?limit=N`,
  `/api/stats`). `/api/identity` is deliberately unauthenticated, same
  contract as a real Meshpoint's own `GET /api/identity` — lets a client
  (e.g. the Flutter fleet-manager app) confirm a URL is really this server
  before ever sending credentials.
  `/api/nodes`/`/api/packets` decode the DB's `latest_signal_json`/
  `latest_telemetry_json`/`decoded_payload_json` blob columns into real
  nested `latest_signal`/`latest_telemetry`/`decoded_payload` objects (and
  send `has_position`/`want_ack`/`via_mqtt`/`decrypted` as real JSON
  booleans, not SQLite's raw `0`/`1`) before responding — the on-disk
  schema still stores them as `_json` TEXT columns either way, only the
  HTTP response shape differs, matching the flat/nested shapes a real
  Meshpoint's own `GET /api/nodes`/`GET /api/packets` already return.

Useful flags: `--ws-port`, `--http-port`, `--db <path>` (default
`local_meshradar.db` next to the script), `--verbose`.

## Login

The HTTP dashboard/viewer/API are gated behind a login page
(`http://<this-machine>:8080/login`, styled after Meshpoint's own
radar sign-in) — a single hardcoded credential pair, `AUTH_USERNAME` /
`AUTH_PASSWORD` near the top of `server.py` (default `viewer` /
`itoldyoualready`). Sessions are an in-memory cookie, so they don't
survive a server restart. This is still not real multi-user auth — see
"No auth enforcement" below for what it does and doesn't protect against.
The `ws://.../8765` ingest port (where Meshpoint units and the browser's
live-update socket connect) is unaffected; it never carried this data.

`POST /api/auth/login` also supports the same dual-mode contract as a
real Meshpoint's own login route: an ordinary browser login (no extra
header) gets the `HttpOnly` cookie only, byte-for-byte the same response
as before. A caller that sends `X-Meshpoint-Client: <anything>` (no
cookie jar to rely on — e.g. the Flutter fleet-manager app) also gets the
raw token back in the JSON body (`{"ok": true, "token": "..."}`), to send
as `Authorization: Bearer <token>` on every subsequent request. Every
`/api/*` endpoint accepts either the cookie or the bearer header.

Two pages:

- `http://<this-machine>:8080/` — the main dashboard, same theme (colors,
  fonts) as the real Meshpoint dashboard (`frontend/css/dashboard.css`):
  - Stat tiles + a Leaflet map (same CARTO dark tile layer, marker styling,
    and clustering as `frontend/js/components/node_map.js`), plotting every
    device and positioned node.
  - **Node list**: search, sort (last heard / packets / RSSI), a
    direct/relayed filter (from each node's most recent hop count),
    favorites (star, persisted in your browser's localStorage), signal
    bars + SNR quality badge, role icon (Router/Sensor/Client/etc, from
    Meshtastic's node role), voltage/battery/altitude badges when that
    telemetry is actually present. Click a card to open its **detail
    drawer** (slide-in panel, styled after `frontend/js/node_drawer.js`) —
    full node info, signal, position, device metrics, and its most recent
    packets.
  - **Packet feed**: card-based, filterable by type / protocol / mesh
    point, with a per-type decoded summary line (position → lat/lon/alt,
    telemetry → battery, text → preview) and protocol-colored badges.
    Click a card to open its **detail modal** (styled after
    `frontend/js/packet_detail_modal.js`) — RF/Mesh/Payload/Capture
    layers, same shape as the real packet detail view.
  - **Live updates**: the dashboard opens its own WebSocket connection
    (`ws://.../live`) — mirrors `frontend/js/websocket_client.js`'s
    reconnect-with-backoff pattern. The server pushes the actual row(s)
    each ingest message just wrote (same shape `/api/devices`/`/api/nodes`/
    `/api/packets` already return), not just a "something changed, go
    refetch" ping — the browser splices it straight into its own
    in-memory state and re-renders, no REST round trip per update. A 30s
    poll still runs underneath as a safety net in case the live socket is
    ever silently down (or a push is missed while reconnecting).
  - Also reachable at `/dashboard` (kept as an alias).
- `http://<this-machine>:8080/viewer` — the original plain-tables page
  (Devices / Nodes / Recent packets, no map), still there as the simplest
  way to eyeball raw data landing without any of the above.

  Needs outbound internet for the map tiles, the Leaflet CDN assets, and
  the Google Fonts (Inter/JetBrains Mono) used to match the real
  dashboard's look; everything else (your actual node data, and all live
  updates) stays fully local.

## Point Meshpoint at it

On each Meshpoint unit, in `config/local.yaml`:

```yaml
upstream:
  enabled: true
  url: "ws://<this-machine-ip>:8765"
  auth_token: "mr1_...your real meshradar.io key..."
```

Restart the Meshpoint service. Every unit is identified by its own
`device_id`, so multiple units (e.g. several fixed spots around a city) can
all point at the same receiver — the Devices/Nodes/Packets tables are all
keyed by `device_id`, nothing collides.

## Running persistently (e.g. on a Proxmox VM)

Copy this directory to the VM (e.g. `/opt/local_meshradar`), install
`requirements.txt`, then use the included `local-meshradar.service`:

```bash
sudo cp local-meshradar.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now local-meshradar
```

Adjust `WorkingDirectory`/`ExecStart` in the unit file if you installed it
somewhere other than `/opt/local_meshradar`, or if `python3` needs to be a
venv path instead of the system interpreter.

## Data model

SQLite (`local_meshradar.db`), four tables:

- `devices` — one row per Meshpoint unit, upserted from each `register`
  (including the connecting IP, `ip_address`, taken from the WebSocket
  peer address — shown in the dashboard's device popup).
- `nodes` — one row per `(device_id, node_id)`, upserted from every
  `heartbeat.nodes[]` entry — this is "latest known state," not history.
- `packets` — one row per decoded packet ever received, append-only.
- `heartbeats` — one row per heartbeat, raw `stats` blob kept as JSON —
  append-only, useful for later charting packet-rate/RSSI trends over time.

Nothing here prunes old rows. For long-running deployments, `packets` and
`heartbeats` will grow indefinitely — add your own retention job if that
matters to you (see `scripts/` in the main Meshpoint repo for the pattern
its own SQLite retention sweep uses).

## Backfilling history from a real Meshpoint's own database

Live data only starts flowing from the moment `upstream.enabled: true`
takes effect — it doesn't include whatever that unit already captured
before then. `import_concentrator_db.py` backfills that: it reads a real
Meshpoint's own `concentrator.db` directly (stdlib `sqlite3` only, no
Meshpoint dependency, same as `server.py` itself) and writes matching rows
into this tool's database, preserving real historical timestamps.

```bash
python3 import_concentrator_db.py \
    --source /path/to/concentrator.db \
    --device-id <the real Meshpoint's device_id, from its config/local.yaml> \
    --dry-run   # reports counts only first, writes nothing

python3 import_concentrator_db.py \
    --source /path/to/concentrator.db \
    --device-id <same device_id>
```

The `--device-id` must match the value already in that Meshpoint's own
`config/local.yaml` (`device: device_id: ...`) so the backfilled history
folds into the *same* device already showing up live here, not a
duplicate. Copy `concentrator.db` (default path `data/concentrator.db` on
the real Meshpoint) to wherever you run this script — it's read-only
against the source, so nothing on the real install is touched.

**Re-running this against the same target duplicates every packet row** —
there's no reliable unique key to de-dupe real mesh traffic against over
long capture windows, so this is meant to be a one-time backfill, not a
repeatable sync. Always `--dry-run` first if unsure.

## What's deliberately not built

- **No relay to the real meshradar.io.** This is receive-only; if you also
  want the real cloud to see the same data, that's a second, separate
  `upstream.enabled` connection Meshpoint doesn't currently support running
  in parallel — not something this server can add on its own.
- **No command support.** Meshpoint's client can execute remote commands
  (`ping`, `get_status`, `restart_service`, etc.) if the server sends
  `{"type": "command", ...}` — this receiver never does. Fully optional;
  add it later if remote control turns out to matter.
- **No real multi-user auth.** The HTTP port (8080) has a single shared
  login (see "Login" above) gating the dashboard/viewer/API, but it's a
  single hardcoded credential pair in plaintext in `server.py`, not a
  proper auth system — no per-user accounts, no rate limiting/lockout, no
  HTTPS of its own. The ingest port (8765) has no auth at all: Meshpoint's
  `Authorization`/`X-Device-Id` headers are only ever logged, never
  checked. This is still meant for a trusted local network — don't expose
  either port to the public internet without fronting it with something
  that actually does this properly (a reverse proxy with real auth + TLS,
  a VPN, etc.).
