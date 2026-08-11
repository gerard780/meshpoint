# Meshpoint App (Flutter) — session context

Companion doc to `memory/project_m1_meshpoint.md`, scoped to the new
`flutter/meshpoint_app/` sub-project specifically. Same conventions apply
(read this at the start of a session touching the Flutter app, update it
after real progress — status, decisions, verification evidence).

## What this is

A native (Android/iOS/macOS/Linux/Windows/web — `flutter create` scaffolded
all six platforms) companion app to **manage and view multiple meshpoint
deployments** from one place. User's own framing: `main.dart` is a welcome
screen; from there, `start.dart` (not built yet) lets you add/remove
meshpoint servers; from each server you open its own dashboard-style
screens (nodes, packets, stats, etc.), mirroring what the web dashboard
already shows per box.

Directly motivated by the user's own real setup: at least 3 live boxes
(`sensecap-meshpoint`, `rakv2-meshpoint`, `ti-meshpoint`, all visible
throughout `project_m1_meshpoint.md`'s recent sessions) — checking on all
three today means opening 3 separate browser tabs and logging into each.

## Current state of the Flutter project (as of 2026-08-10)

Confirmed by reading the actual files, not assumed: **completely stock**
`flutter create` scaffold, unmodified.

- `lib/main.dart` — the default Flutter counter-app template verbatim
  (MyApp/MyHomePage/`_incrementCounter`), not yet touched.
- `pubspec.yaml` — only the default deps (`cupertino_icons`,
  `flutter_lints`). No `http`/`dio`, no state-management package, no
  secure-storage package, no WebSocket package. Blank slate.
- No `start.dart` or any other app-specific file exists yet — the user's
  description is the *plan*, not the current state.
- All 6 platform folders present (android/ios/macos/linux/windows/web) —
  scaffolded for all of them, not yet decided which to actually target.

## Meshpoint's own API surface (verified by reading the actual route/auth
code this session, not recalled from memory alone)

### Auth — the one thing to get right before writing any app code

`src/api/auth/dependencies.py`'s own docstring is explicit that this is a
**dual-mode** auth contract, already designed with non-browser clients in
mind:

1. `Cookie: meshpoint_session=...` (HttpOnly, SameSite=Lax) — the browser
   path.
2. `Authorization: Bearer <jwt>` — explicitly documented as "curl /
   non-browser clients."

**The catch, confirmed by reading `auth_routes.py`'s `login()` handler
directly**: `POST /api/auth/login` currently only returns `{"role": ...}`
in the JSON body — the actual JWT is *only* ever handed back via
`Set-Cookie` (`_set_session_cookie`), never in the response body. So today,
a Flutter client has exactly two real options:

- **(A) Real cookie jar** — `dio` + `dio_cookie_manager` + `cookie_jar`,
  persist the jar (e.g. to secure storage) across app restarts, let it
  behave like a browser. Zero backend changes needed; ships today.
- **(B) Small backend addition** — have `login()` also return the raw
  token in the JSON body (e.g. gated on a client hint header so browser
  responses stay unchanged), then the app stores just that token
  (`flutter_secure_storage`) and sends `Authorization: Bearer <token>` on
  every request — no cookie-jar complexity, cleaner mobile-native pattern,
  matches what the Bearer-header code path was already built for.

**Not decided yet — worth explicitly choosing before writing the HTTP
client layer**, since it shapes the whole `ApiClient` design. Leaning (B)
myself (cleaner, and the server already half-supports it), but (A) needs
no server-side changes at all if minimizing backend risk matters more.

Session TTL is server-configurable (`JwtSessionService.expiry_minutes`,
not hardcoded) — whatever the deployed default is today is tuned for
browser sessions; worth checking it's long enough for "stay logged into
your phone app for weeks," not re-prompting for a password constantly.

### Plain HTTP, not HTTPS

Every real deployment seen this whole session is `http://192.168.x.x:8080`
— plain HTTP on the LAN, no TLS. This is a real, concrete platform-config
task, not just Dart code: Android needs
`android:usesCleartextTraffic="true"` (or a network-security-config XML
scoped to local IP ranges instead of a blanket allow), iOS needs an
`NSAppTransportSecurity` exception in `Info.plist`. Skipping this means
every request just silently fails on real devices the moment it's tested
against a real box, not a bug to chase blind later.

### REST endpoints relevant to "view multiple servers" (non-exhaustive,
the ones that map directly to natural app screens)

- `GET /api/identity` — role + `available_sections` (unauthenticated-safe
  subset). Good first call after adding a server: confirms the URL is
  really a meshpoint box before asking for credentials.
- `GET /api/device/status` — uptime, version, health. The natural
  "server list" summary tile (online/offline, version, uptime at a
  glance) — same data the web sidebar's own status strip already shows.
- `GET /api/nodes` — the node roster (same data `node_cards.js` renders).
- `GET /api/packets` — packet history/feed.
- `GET /api/config` — full radio/protocol config (large payload, same one
  the whole Configuration section of the web app reads from) — a
  read-only "server settings at a glance" view is low-risk; editing is a
  much bigger scope decision, see below.
- `GET /api/meshcore/repeaters` (shape confirmed via `repeater_poller.py`
  work earlier this session) — repeater status/telemetry, matches the
  Repeaters page.
- Various per-protocol endpoints (DAPNET, Pager, LoRaWAN, MeshCore,
  Reticulum) mirroring the web dashboard's own per-protocol pages — build
  these screen-by-screen as needed, not all at once.

### WebSocket `/ws` — for a live feed / push-style screen

Auth-gated (`src/api/auth/ws_guard.py`, same cookie/bearer contract).
Full catalog of broadcast event types, confirmed by grepping every
`.broadcast(` call site in `src/` directly (not guessed):

- `packet` — every decoded packet, live (`packet.to_dict()`).
- `message_received` / `message_updated` — the cross-protocol Messages
  page's own live feed.
- `noise_floor` — RF noise floor snapshot updates.
- `reticulum_peer` / `reticulum_message` — Reticulum-specific live events
  (only fires if that box has Reticulum enabled).

`web_socket_channel` is the natural Flutter package for this.

## My actual opinion (asked for directly, answering it directly)

**Genuinely a good idea, not a "nice someday" thing** — the user already
runs a small real fleet (3 boxes) and today's workflow really is "open 3
browser tabs, log into each separately." A phone app that shows "sensecap:
online, 131 nodes, v0.8.0 · rakv2: online, ... · ti-meshpoint: MeshCore
companion reconnecting..." at a glance, with push-worthy alerts for the
things this session spent hours debugging live (a companion gone
unresponsive, a repeater poll failing repeatedly), is a real, concrete
value-add on top of infrastructure that already exists and already works.
It's also low-risk to build incrementally — read-only screens against an
already-stable REST API, no new backend surface required to get a useful
v1 out the door (the ONE backend question worth resolving is the
auth-response shape above, and even that has a zero-backend-change
fallback).

**Where I'd start (v1 scope, deliberately narrow)**: server list
(add/remove/edit, secure storage) → per-server login → per-server
dashboard showing device-status tile + searchable node list + a live
packet feed over the WebSocket. That alone is a genuinely useful app.
Repeater management, config editing, per-protocol deep-dives, push
notifications — real, valuable, but v2+; building all of it before the
core loop (glance at your phone, see your fleet's health) even works
would be over-building before validating the shape is right.

**Architecture leaning** (not yet decided with the user, just my
recommendation): `flutter_riverpod` for state (small-to-medium app, but
riverpod's testability is worth it over raw `setState` once there's a
list of servers each with their own live connection state) +
`dio`/`http` for REST + `web_socket_channel` for live +
`flutter_secure_storage` for credentials/tokens. `lib/models/` (server,
node, packet, device-status shapes), `lib/services/` (per-server
`ApiClient`, a `ServerStore`, a `WebSocketService`), `lib/screens/`
(`start_screen.dart` for the server list, `server_login_screen.dart`,
`server_dashboard_screen.dart` with tabs mirroring the web sidebar).

## v1 built (2026-08-10, same session as the planning pass above)

User said "yes do it if you can to start" — resolved the one open
decision myself (leaned **(B)**, the small backend addition, over a
cookie-jar) and built the actual v1 scope end to end.

### Backend change

`src/api/routes/auth_routes.py`'s `login()` now accepts an optional
`X-Meshpoint-Client` header; when present, the response body also
includes `{"token": "..."}` (raw JWT) alongside `{"role": ...}` --
gated specifically so an ordinary browser login (no header) is
byte-for-byte unchanged, preserving the HttpOnly cookie's XSS
protection for the web app. Functionally tested against a real FastAPI
`TestClient` (fake `AuthService`, not mocked at the HTTP layer) in a
throwaway venv: confirmed browser logins never see a token, app logins
(header present) get the real token back, cookie is set either way,
and failed logins still 401 regardless of the header. `ruff==0.15.1`
clean. New CHANGELOG bullet (v0.8.0, 49 bullets, re-parsed clean).

### Flutter app

Added `http`, `flutter_secure_storage`, `web_socket_channel`,
`provider`, `intl` to `pubspec.yaml`. Went with `provider` over
`riverpod` for v1 -- simpler, no codegen, plenty for this app's size;
revisit if state complexity actually grows past what a couple
`ChangeNotifier`s comfortably handle.

- `lib/models/`: `MeshpointServer` (id/name/baseUrl/token/role +
  cached last-known status for the list screen), `DeviceStatus`,
  `NodeSummary`, `PacketEvent` -- all built directly against the real
  response shapes (`Node.to_dict()`, `Packet.to_dict()`,
  `device_status()`'s return dict, `SignalMetrics.to_dict()`), read
  from the actual Python source, not guessed.
- `lib/services/server_store.dart`: the configured-server list,
  persisted as one JSON blob via `flutter_secure_storage` (not
  `shared_preferences` -- these are effectively admin credentials for
  real radio infrastructure). `ChangeNotifier`-based, `load()` on app
  start, `addServer`/`removeServer`/`save()`.
- `lib/services/api_client.dart`: one instance per server. Pure
  bearer-token auth (`Authorization: Bearer <token>`, `X-Meshpoint-Client:
  app` on every request) -- no cookie jar, matching the backend
  decision above. `getIdentity()` (unauthenticated, used to validate a
  URL before ever sending credentials), `login()`, `getDeviceStatus()`,
  `getNodes()`, and `websocketUri()` (builds the `ws://`/`wss://` +
  `?token=` form for the live feed, using the query-param fallback
  `src/api/auth/ws_guard.py` already supports since a plain WebSocket
  handshake can't carry a custom header).
- `lib/services/websocket_service.dart`: connects to `/ws`, decodes
  only `{"type": "packet", ...}` frames for now (the other broadcast
  types -- `message_received`/`message_updated`/`noise_floor`/
  `reticulum_peer`/`reticulum_message`, full catalog confirmed by
  grepping every real `.broadcast(` call site in `src/` -- are ignored
  for v1, not errors).
- `lib/screens/start_screen.dart`: the fleet list. Add/remove servers,
  a live online/offline dot per server (checks `getIdentity()` on
  pull-to-refresh and on load), empty state with a call to action.
- `lib/screens/add_edit_server_screen.dart`: add-new or re-login-to-
  existing, same form. Calls `getIdentity()` first to confirm the URL
  is really a meshpoint box before ever sending credentials; friendly
  error messages mapped from the real `LoginFailure` reasons
  (`invalid_credentials`/`locked_out`/`setup_required`).
- `lib/screens/server_dashboard_screen.dart`: 3 tabs -- Status (device
  status fields), Nodes (searchable list, sorted by last-heard,
  pull-to-refresh), Live (scrolling feed off the WebSocket, capped at
  100 entries).
- `lib/main.dart`: rewritten from the stock counter-app template --
  `ChangeNotifierProvider<ServerStore>` at the root, `StartScreen` as
  home.

**Platform config fixes, found by actually checking rather than assuming
they'd just work**:
- macOS `DebugProfile.entitlements`/`Release.entitlements` had
  `com.apple.security.network.server` (inbound) but were missing
  `com.apple.security.network.client` (outbound) -- under App Sandbox
  this would have silently blocked every single HTTP/WebSocket call the
  app makes. Added to both.
- Android `AndroidManifest.xml` had no `INTERNET` permission at all
  (missing entirely, not just cleartext) and no
  `usesCleartextTraffic="true"` -- meshpoint servers are plain HTTP on
  the LAN (confirmed against every real deployment referenced in
  `project_m1_meshpoint.md`), so cleartext is a hard requirement here,
  not a nice-to-have. Blanket-allowed (not scoped to one domain) since
  the whole point is arbitrary user-entered LAN addresses.
- iOS `Info.plist` had no `NSAppTransportSecurity` exception -- same
  plain-HTTP reasoning, same blanket-allow choice, same reason it can't
  be scoped to one domain.
- Caught and fixed a real mistake of my own along the way: my first
  pass at the iOS ATS comment used `--` (double hyphen) as a separator
  inside an XML comment, which is invalid per the XML spec (comments
  can't contain `--` anywhere in the body, not just at the edges) --
  broke `Info.plist`'s XML validity. Caught by actually parsing every
  edited plist/entitlements/manifest file with `xml.etree.ElementTree`
  after editing, not just eyeballing the diff; fixed by rewording.

**Verified for real, not just written**: `flutter analyze` clean (zero
issues). `flutter test` passes -- and genuinely exercises
`ServerStore.load()`'s real code path rather than skipping it: mocked
`flutter_secure_storage`'s actual platform MethodChannel
(`plugins.it_nomads.com/flutter_secure_storage`, confirmed by reading
the plugin's own source rather than guessing the channel name) so
`pumpAndSettle` doesn't hang forever waiting on a channel call with no
real platform handler in the bare test VM. All 4 edited
plist/entitlements/manifest files re-validated as well-formed XML after
the fix above.

**Not yet done**: no real device/simulator run yet (only `flutter
analyze`/`flutter test`, which don't catch every possible platform-build
issue) -- next real step is `flutter run` against an actual meshpoint
box on the LAN to confirm the full login → dashboard → live-feed loop
actually works end to end, not just that it compiles and the widget
tree renders correctly in isolation. Also not done: iOS/macOS code
signing setup (irrelevant until an actual device build is attempted),
app icon/branding (still the default Flutter icon), and everything
explicitly deferred to v2 in the original plan (config editing,
repeater management, per-protocol pages, push notifications).
