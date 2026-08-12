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

## Real branding + theme system (2026-08-11, live-tested via real macOS run)

User: "the appicons can you please use the icons from meshpoint now its
all the stock icons" + "also can you use the same color sheme as
meshpoint please also a toggle for light/dark/blue etc the meshpoint has
like 3 darkthemes."

- **App icon**: copied the real existing `frontend/assets/icon-512.png`
  (already used as the web PWA icon -- purple/orange gradient, mesh-globe
  "M" mark, "Meshpoint" wordmark) into `assets/icon/icon.png`, added
  `flutter_launcher_icons` as a dev dependency, ran it to regenerate real
  icons for Android/iOS/macOS/Windows/web from that one source
  (`remove_alpha_ios: true` since iOS requires an opaque icon and the
  source has transparency outside its own pre-baked rounded-card shape;
  web background/theme color set to the real dark theme's
  `--bg-primary`/`--accent-cyan`). Did not design a new icon -- reused
  the existing brand asset exactly as asked.
- **Theme system**: NOT invented -- read the web dashboard's actual
  `frontend/js/theme_controller.js` (three named themes: `dark` default,
  `high-contrast`, `sunlight`) and pulled real color values straight from
  `frontend/css/dashboard.css`'s `:root` and
  `frontend/css/theme_high_contrast.css`'s two override blocks. All
  three are dark-background variants (the user's "like 3 darkthemes" was
  accurate -- there's no actual light theme to port). Built
  `lib/theme/meshpoint_theme.dart` (3 `MeshpointPalette` consts with the
  exact hex values + a `ThemeData` builder) and
  `lib/services/theme_store.dart` (persists the choice via the same
  secure-storage instance the server list already uses, rather than
  adding `shared_preferences` for one extra value). Toggle is a palette
  icon button in `StartScreen`'s AppBar (`_ThemeMenuButton`, a popup menu
  with the 3 named options + a checkmark on the current one) --
  deliberately a named-options menu, not a blind cycle button, since a
  first-time user picking from labels beats guessing what a cycle icon
  does.

### Real bugs found live (only surfaced once the user actually ran the app)

1. **Auth token still missing after "I updated meshpoint"** -- turned
   out to be exactly the standing gotcha this whole project's own memory
   already warns about: `git pull` doesn't reload a running Python
   process. Diagnosed cleanly via a raw `curl -X POST .../api/auth/login
   -H "X-Meshpoint-Client: app" ...` bypassing the app entirely --
   confirmed `{"role":"admin"}` with no `token` field, i.e. definitely
   still the old pre-fix code. User then confirmed the commit *was*
   present locally (`git log` showed it) but the fix only actually took
   effect after `sudo systemctl restart meshpoint`. Not a code bug on
   either side -- a deployment-step gotcha, resolved by direct
   verification rather than guessing.
2. **`PlatformException(-34018, "A required entitlement isn't
   present.")` on every `flutter_secure_storage` write, live on the real
   macOS build** (removing a server, changing the theme -- anything that
   persists). Root cause: `flutter_secure_storage` uses the Keychain on
   macOS, and under App Sandbox (already enabled in both entitlements
   files from the earlier network-permission fixes) Keychain API calls
   need an explicit `keychain-access-groups` entitlement or they fail
   with exactly this error code -- a real, separate gotcha from the
   network-client one found earlier, not caught by `flutter analyze`/
   `flutter test` since the widget test mocks the storage channel
   entirely (never exercises the real macOS Keychain code path). Fixed
   by adding `keychain-access-groups` (`$(AppIdentifierPrefix)$(PRODUCT_BUNDLE_IDENTIFIER)`)
   to both `DebugProfile.entitlements` and `Release.entitlements`.
   **Entitlement changes are baked into code signing at build time --
   need a full stop + fresh `flutter run`, not hot reload/restart, to
   actually take effect.** Not yet confirmed fixed (told the user this
   right after making the change, live verification pending).
3. **Self-caught, twice in the same session**: used `--` (double
   hyphen) as a prose separator inside an XML comment twice now (once in
   the iOS ATS comment, now again in this exact entitlements comment) --
   XML comments cannot contain `--` anywhere in the body per spec, not
   just at the edges, and it silently breaks the whole file's XML
   validity. Caught both times by actually parsing the file with
   `xml.etree.ElementTree` after editing, not by eyeballing the diff.
   **Worth remembering for next time: never use `--` inside any
   plist/entitlements/manifest XML comment in this project, use a plain
   period or comma instead.**

Status: awaiting live confirmation from the user that a full rebuild
(not hot reload) resolves the Keychain crash.

### Correction, same session: keychain-access-groups made it worse, not better

`flutter run -d macos` immediately failed with a *build* error (worse
than the runtime crash it was meant to fix): `"Runner" has entitlements
that require signing with a development certificate. Enable development
signing in the Signing & Capabilities editor.` -- adding
`keychain-access-groups` forces Xcode to require a real Apple
Developer signing team, which this local dev setup doesn't have
configured. That's a strictly worse failure mode (won't build at all)
than the one it was fixing (built fine, crashed at runtime on a
Keychain write).

**Real fix**: App Sandbox (`com.apple.security.app-sandbox`, present in
both entitlements files since the original stock `flutter create`
scaffold -- i.e. this bug was latent from the very start, not something
any of this session's edits introduced) is only actually required for
Mac App Store distribution. This app is a personal LAN utility with no
App Store plans, so the sandbox entitlement was removed entirely from
both `DebugProfile.entitlements` and `Release.entitlements` rather than
trying to satisfy it with `keychain-access-groups`. Unsandboxed,
Keychain access works with zero special entitlements and plain
automatic/ad-hoc signing -- no Apple Developer team needed, matching how
the project already built successfully before any of today's
entitlements edits.

**Verified for real this time, not just reasoned about**: `flutter
build macos --debug` actually succeeds (confirmed live, was failing
before this fix). Launched the built `.app` directly and confirmed via
`ps aux` it's actually running, not just that the build step exited 0.
Quit that verification instance afterward so it doesn't collide with
the user's own `flutter run` dev session. **Still not confirmed**: the
actual Keychain write path itself (remove a server / change theme) --
that needs the user's own interactive test, since it requires real UI
interaction the build+launch check above doesn't exercise.

**Same `--`-in-XML-comment mistake made a third time** writing this
exact fix's own explanatory comment, caught immediately by grepping for
`--` across every touched file before re-validating (not just
re-running the single-file parse check that already caught it twice
today) -- this really is worth remembering going forward, not just
noting after the fact each time.

### Resolved -- confirmed live by the user ("works fixed :)")

The Keychain error persisted one more round after the App Sandbox
removal, still showing the same `errSecMissingEntitlement`-family
message. Root cause was environmental, not a further code bug: a stale
Keychain item from an earlier build (ad-hoc signing regenerates a new
identity each rebuild, so a keychain entry written under an older
signature can become inaccessible to a newer build even after the
actual entitlements are fixed) combined with the running process not
yet being a genuinely fresh launch. Resolved by the user clearing the
stale `meshpoint` entry in Keychain Access.app and doing a full quit +
fresh `flutter run -d macos`. No further code change needed -- the
App Sandbox removal from earlier was the correct and sufficient fix;
this last round was purely stale local state on the test machine.

**v1 is now fully live-verified end to end**: server add/login (real
bearer token from the updated Pi), the dashboard's Status/Nodes/Live
tabs, real app icon, and the 3-theme picker all confirmed working on an
actual running build against a real deployed meshpoint box, not just
`flutter analyze`/`flutter test`/a build-success check. Good stopping
point for this feature; next real steps whenever picked back up are the
explicitly-deferred v2 items (config editing, repeater management,
per-protocol pages, push notifications) or a first Android/iOS device
test (only macOS has been live-tested so far).

## App name + splash screen (2026-08-11, same session)

User: "in the app can you name everything the app is Meshpoint Fleet
Manager can you fix this in the flutter app everywhere ?" + "also the
start needs the app icon to be shown splash screen."

### Renamed everywhere a display name actually appears

Every platform's window title / bundle display name / task-switcher
label, updated to "Meshpoint Fleet Manager": `lib/main.dart`
(`MaterialApp.title`), `lib/screens/start_screen.dart` (AppBar),
`macos/Runner/Configs/AppInfo.xcconfig` (`PRODUCT_NAME` -- this is the
one that actually controls the macOS window/bundle title, confirmed
live: the built app is literally named `Meshpoint Fleet Manager.app`
now), `ios/Runner/Info.plist` (`CFBundleDisplayName` and
`CFBundleName`), `android/app/src/main/AndroidManifest.xml`
(`android:label`), `linux/runner/my_application.cc` (header bar +
window title), `windows/runner/Runner.rc` (`FileDescription`/
`ProductName` -- left `InternalName`/`OriginalFilename` as the literal
`.exe` filename, not a display string) and `main.cpp` (window title),
`web/manifest.json` (`name`/`description` -- `short_name` deliberately
kept as just "Meshpoint", a PWA-specific space-constrained field, not
really a second "app name"), `web/index.html` (`<title>` +
`apple-mobile-web-app-title` + description meta), `pubspec.yaml`
(`description`, not the Dart package `name:` itself -- renaming that
would cascade into every import statement across the project for a
purely internal identifier, not something "everywhere the app is
named" was actually asking for). `test/widget_test.dart`'s assertion
updated to match.

One deliberate technical caveat left as-is rather than silently
avoided: iOS's `CFBundleName` is traditionally meant to stay short
(~15 chars) since it's used in space-constrained system UI; "Meshpoint
Fleet Manager" is 23. Set it anyway per the explicit "everywhere"
instruction -- iOS will just truncate it wherever that constraint
actually bites, which is a device-rendering behavior, not a bug in
this app.

Verified with a real `flutter build macos --debug` (not just
`analyze`/`test`) specifically to see the actual built bundle name
change, not just trust the config edit -- confirmed
`Meshpoint Fleet Manager.app` really is the output filename now.
Launched it and confirmed via `ps aux` it runs.

### Splash screen

Native splash (via new `flutter_native_splash` dev dependency,
`flutter_native_splash.yaml` config, `dart run
flutter_native_splash:create`) for Android/iOS -- the platforms that
actually have an OS-level splash phase before the Flutter engine even
starts. Uses the same real `assets/icon/icon.png` on the same dark
background every one of the app's 3 themes shares (`#0a0e17`).

macOS/Windows/Linux have no such OS-level concept at all -- flutter_native_splash
doesn't target desktop for exactly that reason -- so `lib/screens/splash_screen.dart`
(new) is a plain Flutter widget shown instead, for the platform this
app has actually been live-tested on. Bundled `assets/icon/icon.png`
as a real runtime asset (`pubspec.yaml`'s `flutter: assets:`, previously
only used as an icon-generator *input*, never loadable at runtime) so
`Image.asset()` can actually show it.

**A real design bug caught by writing a real test for this, not just
eyeballing it**: first version had `SplashScreen.build()` internally
return `StartScreen()` once `ServerStore.loaded` was true -- meaning
`SplashScreen` never actually left the widget tree, it just changed
what it rendered as its own child, so `find.byType(SplashScreen)`
still matched even after "handoff." A test asserting `findsNothing`
for `SplashScreen` post-settle caught this immediately. Fixed by
moving the loaded/not-loaded decision up to `MeshpointApp` itself
(`Consumer<ServerStore>` picking between `StartScreen`/`SplashScreen`
directly as siblings, not one wrapping the other) -- genuinely mutually
exclusive in the tree now, confirmed by the same test passing after
the restructure. `flutter analyze` clean, `flutter test` passes (2
assertions: splash visible + real `Image` widget present before
settling, splash gone + fleet screen visible after), `flutter build
macos --debug` still succeeds, launched and confirmed running via
`ps aux`.

Splash text updated per follow-up ask ("under our icon also display
Meshpoint Fleet Manager as text"): added a `Text('Meshpoint Fleet
Manager')` below the icon in `splash_screen.dart`, styled off
`MeshpointPalette.dark.textPrimary` (the splash always uses the dark
palette regardless of the user's chosen theme, since it renders before
`ThemeStore.load()` resolves). `widget_test.dart`'s pre-settle
assertions extended to check `find.text('Meshpoint Fleet Manager')`
alongside the existing `SplashScreen`/`Image` checks.

### Light theme

Fourth theme, `MeshpointThemeName.light` -- unlike the other three
(`dark`/`highContrast`/`sunlight`, all mirrored from the web
dashboard's actual CSS), there's no light theme on the web dashboard to
mirror, so this reuses the real, already-tuned light palette from
`extra/local_meshradar/dashboard.html` (contrast-fixed for real bugs
earlier in this same session, so proven values, not a fresh guess).
`accentBlue` has no local_meshradar equivalent and was picked fresh
(`#2563EB`) to read cleanly on white.

Required `MeshpointPalette` to stop assuming dark mode everywhere: added
a `brightness` field (default `Brightness.dark`, so the three existing
palettes needed no changes) and made `buildMeshpointTheme()` read
`p.brightness` instead of hardcoding it -- also switches between
`ThemeData.dark().textTheme`/`ThemeData.light().textTheme` as the base
before applying palette colors. `_ThemeMenuButton` in
`start_screen.dart` needed no changes at all since it already iterates
`MeshpointThemeName.values` generically -- confirmed by reading it, not
assumed.

Added a real (non-widget) test asserting the brightness genuinely
propagates: `MeshpointPalette.light.brightness == Brightness.light`,
and that `buildMeshpointTheme(MeshpointPalette.light).brightness` and
`.scaffoldBackgroundColor` come out right too -- guards against a
palette field existing but silently not being read anywhere, the same
class of bug the splash-screen test caught earlier. `flutter analyze`
clean, `flutter test` passes (3 assertions total now), `flutter build
macos --debug` still succeeds.

### Node cards + detail popup

User's ask: make the Nodes tab's node list look like the web dashboard's
own node cards, and open a detail popup on tap. Read both real
references first: `frontend/js/node_cards.js` +
`frontend/css/node_cards.css` (the live dashboard's rich card --
hash-colored avatar, online dot, protocol badge, signal/telemetry/meta
chip rows) and `extra/local_meshradar/dashboard.html`'s `.node-card`
(the "perfect" one the user specifically called out -- same visual
language, standalone single-file version), plus `frontend/js/node_drawer.js`
for the slide-out detail panel's section structure.

**Model gap found first**: `NodeSummary` only captured a handful of the
fields `/api/nodes` (`NodeRepository.get_all_with_signal()` in
`src/storage/node_repository.py`) actually returns -- confirmed by
reading the real backend route (`src/api/routes/nodes.py`'s
`list_nodes()`, `enrich=True` by default) and repository method, not
assumed. Extended the model with every `latest_*` flat column the query
joins in (`latest_hops`, `latest_capture_source`, `latest_battery`,
`latest_voltage`, `latest_temperature`, `latest_humidity`,
`latest_channel_util`, `latest_air_util`) plus base columns the model
was missing (`short_name`, `firmware_version`, `altitude`, `first_seen`).
No new API calls needed -- this all already comes back from the single
`GET /api/nodes` call the app already makes; only the model was
under-reading the response.

New files:
- `lib/utils/node_visuals.dart` -- shared signal-quality/battery-tier/
  avatar-hash-color helpers, ported from the same tier breaks
  `node_cards.js`/`node_drawer.js` use (so an RSSI value reads the same
  color here as on the web dashboard), used by both the card and the
  detail sheet so they can't drift apart.
- `lib/utils/hardware_names.dart` -- direct port of
  `frontend/js/meshtastic_hw_names.js`'s `HW_NAMES` enum table (57
  entries, same enum values) so hardware models resolve to the same
  names on both surfaces.
- `lib/widgets/node_card.dart` -- `NodeCard`, mirrors `nc-card`'s
  layout: avatar + online dot + name/heard-time + MT/MC protocol badge,
  then wrapped chip rows for signal (bars + dBm + SNR + quality label),
  telemetry (voltage/battery/temp/humidity/ChUtil/AirUtil), and meta
  (hardware/role/band/node-id). Palette-aware via
  `MeshpointPalette.forTheme(context.watch<ThemeStore>().current)`, so
  it reskins correctly across all 4 themes including the new light one,
  not hardcoded to dark like the splash screen deliberately is.
- `lib/widgets/node_detail_sheet.dart` -- `showNodeDetailSheet()` opens
  a `DraggableScrollableSheet` (reads as "more about the card you
  tapped", not a full navigation away, matching how `node_drawer.js`'s
  slide-out panel relates to the node list beside it) with Node
  Info/Signal/Device Metrics/Environment/Position sections, mirroring
  `node_drawer.js`'s own section split. Deliberately v1-scoped: no
  metrics-over-time chart, no recent-packets list -- both need their own
  API calls (`/api/nodes/{id}/metrics_history`,
  `/api/packets/by-source/{id}`) this app doesn't make yet, left for a
  later pass rather than half-building them now.

`server_dashboard_screen.dart`'s `_NodesTab` swapped from a plain
`ListTile` list to `ListView.builder` of `NodeCard`, `onTap:
showNodeDetailSheet(context, n)`.

**Real bug caught by writing a real test, not just eyeballing the UI**:
first version of `test/node_card_test.dart` wrapped `ThemeStore`'s
provider around only the `Scaffold`/`home` content, not `MaterialApp`
itself. `showModalBottomSheet` inserts into the `Navigator`'s `Overlay`,
which is a sibling of `home`'s subtree, not a descendant of it -- so
`NodeDetailSheet`'s `context.watch<ThemeStore>()` threw
`ProviderNotFoundException` the instant the sheet opened. Fixed by
wrapping `MaterialApp` itself in the provider, matching `main.dart`'s
real placement (`MultiProvider` wraps `MaterialApp` there too) -- this
was a genuine placement bug the test caught, not a test-only quirk.
`flutter analyze` clean, `flutter test` passes (4 assertions total:
card renders identity/badge/chips; tapping opens the real sheet with
matching RSSI/band/hardware/role info), `flutter build macos --debug`
still succeeds.

### Unrelated fix found along the way: macOS About panel copyright

User noticed the native "About Meshpoint Fleet Manager" panel (macOS
app menu) showed "Copyright © 2026 com.example. All rights reserved."
-- the unconfigured `flutter create` template default leaking through.
Traced to `macos/Runner/Configs/AppInfo.xcconfig`'s `PRODUCT_COPYRIGHT`,
which `macos/Runner/Info.plist`'s `NSHumanReadableCopyright` reads via
`$(PRODUCT_COPYRIGHT)` -- confirmed by grepping for both keys, not
guessed. Changed to "Copyright © 2026 Meshpoint. All rights reserved."
Verified against the actual built bundle, not just the source template:
`PlistBuddy -c "Print :NSHumanReadableCopyright"` on the real `.app`'s
`Info.plist` after a fresh `flutter build macos --debug`.

**Deliberately left alone**: the bundle identifiers are also still
`com.example.meshpointApp` (macOS/iOS) / `com.example.meshpoint_app`
(Android), same template default. Not touched here -- changing a bundle
ID changes the app's code-signing identity, which is exactly what broke
Keychain access earlier this session (`PlatformException -34018`, see
above) when the signing identity shifted between builds. Worth doing
deliberately as its own change if the user wants it, not as a drive-by
alongside a copyright string edit.

### Android build config: compileSdk/NDK/minSdk bumped

`flutter build apk` failed outright (manifest merge error, not just a
warning): `flutter_secure_storage`'s own manifest declares `minSdk 23`,
but this Flutter install's bundled `flutter.minSdkVersion` default is
21. Also warned about `compileSdk`/NDK version mismatches from
`flutter_secure_storage`/`flutter_native_splash`/`path_provider_android`
all wanting higher than this install's bundled defaults
(`flutter.compileSdkVersion`/`flutter.ndkVersion`). Fixed in
`android/app/build.gradle.kts`: `compileSdk` pinned to `36`, `ndkVersion`
pinned to `"27.0.12077973"` (both backward compatible, per Flutter's own
suggested fix), `minSdk` raised from the tool's default `21` to `23`
(matching the plugin's real requirement, not overridden away with
`tools:overrideLibrary` which the plugin's own error text warns "may
lead to runtime failures"). Verified with a real `flutter build apk`
(release) -- went from a hard failure to `✓ Built
build/app/outputs/flutter-apk/app-release.apk (52.3MB)`.

### Android 12+ splash icon was zoomed in / cropped

User real-device report (installed the just-built APK, saw it live):
"in the splash screen the icon is zoomed in weird" -- then clarified
"logo i mean". Root cause, confirmed by actually opening the generated
resource file (`android/app/src/main/res/drawable-xxxhdpi/android12splash.png`)
and seeing it was the plain, unmodified `assets/icon/icon.png`: Android
12+'s `SplashScreen` API (`windowSplashScreenAnimatedIcon` in
`android/app/src/main/res/values-v31/styles.xml`) renders the icon
inside its own fixed icon window sized like an adaptive-icon foreground
(visual content expected within roughly the inner 66% safe zone, margin
around it). `icon.png` bakes its own rounded-square background + the
"Meshpoint" wordmark in edge-to-edge with zero margin, so the OS's own
scaling zoomed into the center of that with no safe zone to respect,
cropping the wordmark -- a well-documented `flutter_native_splash` +
Android 12 gotcha, not a bug in this app's own code, and not something
`dart run flutter_native_splash:create` warns about since it's happy to
resize whatever source image you hand it.

Fix: generated a padded variant specifically for the `android_12` splash
source -- `assets/icon/icon_splash_android12.png`, built with a small
Python/PIL script (transparent 512x512 canvas, source icon scaled to
62% and centered, real transparent margin around it) so the OS's own
zoom lands on a correctly-framed badge instead of cropping in on an
unpadded one. The plain full-bleed `icon.png` is untouched and still
used everywhere else (launcher icon, pre-Android-12 splash, desktop
`splash_screen.dart`) -- this padding is specifically an Android-12-splash-API
workaround, not a general icon fix. Wired into
`flutter_native_splash.yaml`'s `android_12.image`/`image_dark`, then
regenerated for real (`dart run flutter_native_splash:create`) --
confirmed by reopening the newly-generated
`drawable-xxxhdpi/android12splash.png` and seeing the padded badge, not
just trusting the config edit. `flutter analyze` clean, `flutter build
apk --debug` still succeeds.

Not yet re-verified on the user's actual Android device (that's the
next real check -- this was verified as far as "the generated resource
file is now correctly padded," not yet "the user has seen it render
correctly on hardware").

### Nodes tab wasn't actually live -- only updated on screen re-entry

User report (testing on Mac): "the data pulled or streamed over
websocket, i dont get live updates i have togo out of the screen and
back and i see updates." Real bug, confirmed by reading
`server_dashboard_screen.dart`'s existing code: `_connectLive()`'s `/ws`
stream listener only ever appended to `_livePackets` (the Live tab) --
it never touched `_nodes` (the Nodes tab) at all. `_loadNodes()` was a
one-shot `initState()` call plus manual pull-to-refresh; the only reason
leaving and re-entering the screen "fixed" it is that recreates
`ServerDashboardScreenState` and reruns `initState()`.

Checked how the web dashboard actually avoids this
(`frontend/js/app.js`): it does two things together, not one instead of
the other -- `nodeCards.updateFromPacket(packet)` patches
`last_heard`/`latest_rssi`/`latest_snr` into the in-memory node list
immediately on every websocket message, *and* a `setInterval(..., 15_000)`
calls `_refreshData()` (a full `/api/nodes` re-fetch) for everything a
single packet can't carry (new nodes joining, battery/voltage/hardware
telemetry). Ported both:

- `NodeSummary.withLivePacket({heardAt, rssi, snr})` (new method,
  `lib/models/node_summary.dart`) -- returns a copy with lastHeard/
  rssi/snr patched and packetCount bumped, everything else preserved.
  `rssi`/`snr` fall back to the existing value when the packet doesn't
  carry a signal block (e.g. MQTT-relayed), rather than blanking a
  still-good reading.
- `_ServerDashboardScreenState._applyLivePacketToNodes()` (new,
  `server_dashboard_screen.dart`) -- on every `/ws` packet, finds the
  matching node by `sourceId` and replaces it in `_nodes` via
  `withLivePacket`, moved to the front to match `_loadNodes()`'s
  most-recently-heard-first sort. Unknown source IDs are left alone for
  the reconciliation timer to pick up as a real new node (inserting a
  half-populated placeholder from a bare packet was deliberately not
  done -- `PacketEvent` doesn't carry display name/hardware/role, so a
  synthesized entry would look broken until the next reconciliation
  overwrote it anyway).
- `Timer.periodic(Duration(seconds: 15), ...)` calling `_loadNodes(showLoading: false)`,
  started in `initState()`, cancelled in `dispose()`. `_loadNodes()`
  gained a `showLoading` param so this background tick doesn't flash the
  `LinearProgressIndicator` every 15s, and a failed background tick no
  longer clobbers an already-good node list with an error screen (only
  the user-initiated initial load / pull-to-refresh surface `_nodesError`).

Real tests added, not just trusted the logic: `test/node_summary_test.dart`
(new) proves `withLivePacket` patches the right fields, bumps
packetCount, preserves everything else, and correctly keeps prior
rssi/snr when the packet carries none. Didn't attempt to test
`_applyLivePacketToNodes` itself at the widget level -- `WebSocketService`
isn't currently injectable into `ServerDashboardScreen` (it's constructed
inline, `_ws = WebSocketService()`), so exercising the full live-socket
path would need a DI refactor beyond this bug's scope; flagged here as a
real gap, not silently skipped. `flutter analyze` clean, `flutter test`
passes (6 assertions total now), `flutter build macos --debug` still
succeeds.

### Splash screen / boot screen churn -- reverted, not pursued further

A long back-and-forth followed (rename "Meshpoint Fleet Manager" ->
"Meshpoint Manager", minimum splash display duration, removing the
spinner, trying to fix a "two screens" complaint on Android via a blank
native splash, discovering Android 12's SplashScreen API always falls
back to showing the launcher icon regardless, attempting a platform-
conditional gate). The user ended up running `git checkout` to discard
essentially all of it and said "we reverted to working boot screen :)".
Current real state: back to the original splash (icon + "Meshpoint
Fleet Manager" text + spinner, held only as long as `ServerStore.load()`
takes, no minimum duration, native Android/iOS splash shows the plain
icon via `flutter_native_splash.yaml`'s original `image`/`image_dark:
assets/icon/icon.png` config) -- i.e. everything from before this
sub-thread started. **Don't re-attempt any of this unprompted** -- if
asked again, start from a much smaller, single change verified on a
real device before layering another on top, rather than iterating
blind through several native-platform-config changes in a row.

### Node band label ("MHz" chip) was hardcoded to 868, wrong for non-EU users

User's friend tested from the US (915 MHz ISM band) and every node
showed "868 MHz" regardless. Confirmed by reading
`src/capture/concentrator_source.py` (backend, read-only -- user
explicitly said "not the meshpoint python", so no backend change made):
`capture_source="concentrator"` is a fixed literal stamped for every
concentrator-sourced packet regardless of its real RF region -- it
carries zero band information. `NodeSummary.bandLabel` (ported from
`frontend/js/node_cards.js`/`node_drawer.js`'s `_bandLabel()`) had
special-cased `capture_source == 'concentrator' -> '868 MHz'`, i.e. a
blanket guess baked from the original EU deployment, now proven wrong
by a real screenshot the user sent showing every single node card in
their own RAKV2 box uniformly labelled "868 MHz" regardless of node --
exactly the "always the same value, not real per-node data" signature
of a hardcoded fallback.

Fix, scoped to the Flutter app only per the user's explicit instruction
(web dashboard's own `node_cards.js`/`node_drawer.js` has the identical
bug, deliberately left untouched -- out of scope for this ask): removed
the `'concentrator' -> '868 MHz'` special case from
`lib/models/node_summary.dart`'s `bandLabel` getter. The `_433`/`_868`
suffix matching (`serial_868`, `meshcore_usb_433`, etc.) stays -- those
come from a deployer-set per-device `label` in `local.yaml`
(`SerialDeviceConfig.label`/`MeshcoreUsbConfig.label` in
`src/config.py`), a real asserted signal, not a guess. A concentrator
source (or any other unrecognized `capture_source`) now shows no band
chip at all rather than a confidently wrong one.

Real tests added: `test/node_summary_test.dart` gained a `bandLabel`
group -- labelled suffixes still resolve correctly, `'concentrator'`
now resolves to `null` (the exact regression this fixes), and a bare
`'serial'`/missing capture source also correctly shows nothing.
`flutter analyze` clean, `flutter test` passes (9 assertions total
now), `flutter build macos --debug` still succeeds.

### Bottom-nav restructuring: from a stacked-screens app to a persistent shell

User referenced their other Flutter app (`/Users/einstein/Software/flutter/dmr-database-app`, a `BottomNavigationBar` + body pattern) and asked for a bottom nav instead of the per-server top `TabBar`. Design converged over a short back-and-forth before building (per this session's own working style: discuss the idea, confirm, then implement):
- 5 bottom-nav tabs: **Meshpoints, Nodes, Packets, Settings, Info** (final names -- see the two rename passes below).
- Boot screen lands directly on the first tab (no separate "start screen" pushed as its own route).
- Tapping a meshpoint card opens a detail popup (reusing the `NodeDetailSheet` pattern) with a **"Switch to this meshpoint"** action, rather than losing the old per-server "Status" tab's content or auto-navigating away on tap.
- Nodes/Packets are *shared* tabs scoped to whichever meshpoint is "active," with their own "no active meshpoint" empty state pointing back to the Meshpoints tab.

**Architecture**: `ServerDashboardScreen` (one Scaffold per server, pushed via Navigator, owned its own `ApiClient`/`WebSocketService`/node list as local `State`) and `StartScreen` (the old top-level server list) were both deleted entirely and replaced with:
- `HomeShell` (new) -- persistent `Scaffold` with a bottom `NavigationBar` over an `IndexedStack` of the 5 tabs. `IndexedStack`, not `PageView`/route-per-tab, deliberately: Nodes/Packets both read live connection state that must survive tab switches, not reconnect every time.
- `ActiveMeshpointController` (new, `ChangeNotifier`) -- holds whichever single meshpoint is "active" plus its node list/live packet feed/websocket/15s reconciliation timer, ported directly from what used to be `ServerDashboardScreen`'s own `State` fields. Lives in `main.dart`'s `MultiProvider` (above `MaterialApp`, same placement lesson learned earlier this session for modal sheets) so it survives across tab switches. Deliberately does **not** own device status (uptime/firmware) -- that moved to...
- `MeshpointDetailSheet` (new) -- a `DraggableScrollableSheet`, opened on tapping any logged-in meshpoint card, doing its own one-off `getDeviceStatus()` fetch independent of which meshpoint (if any) is active. This is where the old "Status" tab's content actually lives now -- not lost, just relocated to where the user taps for it.
- `TabIndexController` (new, tiny `ChangeNotifier<int>`) -- lets `MeshpointDetailSheet`'s "Switch to this meshpoint" button and `NoActiveMeshpointNotice`'s "Go to Meshpoints" button jump the bottom nav from outside `HomeShell` itself.
- `MeshpointsTab`/`NodesTab`/`PacketsTab`/`SettingsTab`/`InfoTab` (new, `lib/screens/tabs/`) -- the 5 sections. `SettingsTab` is where the old AppBar theme-picker menu moved to (a `RadioListTile` list now, plus "log out of active meshpoint"). `InfoTab` is static app-info text -- deliberately no `package_info_plus` dependency added just for a version string (v1 scope, and this session already had enough native-package grief this session, see [[native-splash-verify-before-layering]]) -- keep the hardcoded version string in `info_tab.dart` in sync with `pubspec.yaml` by hand.
- `showMeshpointDetailSheet(context, meshpoint)` mirrors the existing `showNodeDetailSheet()` convention exactly, for the same reason: consistency the user explicitly asked for ("reuse the same pattern").

**Two full rename passes**, both user-driven, both done for real (files renamed, not just classes):
1. "a server is a meshpoint" -> renamed the bottom-nav's first tab from "Servers" to "Meshpoints" everywhere, including user-visible copy ("No meshpoints yet", "Add your first meshpoint", "Remove meshpoint", "Switch to this meshpoint", etc.) -- then, when asked "not only internal naming but also the files?", confirmed scope via AskUserQuestion (this session had *just* gotten explicit negative feedback about chaining unverified changes without checking in, so a rename touching nearly every file in the app got a real confirmation first) and renamed the files/classes too: `server_store.dart`/`ServerStore` -> `meshpoint_store.dart`/`MeshpointStore`, `active_server_controller.dart`/`ActiveServerController` -> `active_meshpoint_controller.dart`/`ActiveMeshpointController`, `servers_tab.dart`/`ServersTab` -> `meshpoints_tab.dart`/`MeshpointsTab`, `server_detail_sheet.dart`/`ServerDetailSheet` -> `meshpoint_detail_sheet.dart`/`MeshpointDetailSheet`, `no_active_server_notice.dart`/`NoActiveServerNotice` -> `no_active_meshpoint_notice.dart`/`NoActiveMeshpointNotice`, `add_edit_server_screen.dart`/`AddEditServerScreen` -> `add_edit_meshpoint_screen.dart`/`AddEditMeshpointScreen`.
   - **Deliberately NOT renamed**: `MeshpointServer`/`meshpoint_server.dart` (already had "Meshpoint" in the name), and `MeshpointStore`'s own `servers`/`addServer`/`removeServer` members (still read fine -- they operate on `MeshpointServer` objects, no actual "server" concept left to disambiguate). Most importantly: the **secure-storage key string stays `'meshpoint_servers_v1'` unchanged** -- that's persisted on-device user data; changing it would silently orphan every existing install's already-saved list on the next launch (a fresh read under a new key finds nothing). Flagged explicitly in a code comment on `_storageKey` so this doesn't get "cleaned up" by accident later.
2. "the live_tab should be called packets" -> `live_tab.dart`/`LiveTab` -> `packets_tab.dart`/`PacketsTab`, including the bottom-nav label itself ("Live" -> "Packets") and the tab's own AppBar title. User noted the packets tab's UI itself ("plain `ListTile` rows) will get real design attention later -- this pass was naming only, left a comment in the file saying so rather than scope-creeping into a redesign.

Verified for real after every mechanical step, not just trusted the renames: `flutter analyze` after each file (caught every broken import/reference immediately, used as the primary tool for sweeping up a rename this size), a `grep` sweep across `lib/`/`test/` afterward for any of the old symbol names flutter analyze wouldn't catch (stale doc-comment prose, not broken code), `flutter test` (10 assertions, including a new real test that taps the "Nodes" nav destination and asserts the *actual* empty-state widget appears, not just that some tab switched), and both `flutter build macos --debug` and `flutter build apk --debug` succeeding.

### Meshpoints tab icon -> the web dashboard's own "Hardware" sidebar glyph

User wanted the bottom-nav Meshpoints icon to be the exact same router
pictogram the web dashboard uses for its "Hardware" sidebar item
(`frontend/index.html`, a custom SVG -- source comment there notes it's
a generic router pictogram from svgrepo, exact license unconfirmed but
not a brand mark). No Material Icons glyph matches its shape, so:
- Added `flutter_svg` (`^2.0.10+1`, resolved to `2.2.3`) -- deliberately
  called out in `pubspec.yaml`'s own comment as pure-Dart rendering, no
  native platform config, unlike this session's other dependency
  additions (flutter_secure_storage, flutter_native_splash) that caused
  real Android/entitlements grief earlier.
- `assets/icons/hardware.svg` (new) -- the identical path data copied
  from `frontend/index.html`, `fill="currentColor"` preserved.
- `HomeShell`'s `_HardwareIcon` (new, private) wraps `SvgPicture.asset`
  with a `ColorFilter.mode(IconTheme.of(context).color, BlendMode.srcIn)`
  -- needed because (unlike a plain `Icon`) `SvgPicture` doesn't
  automatically pick up `IconTheme`'s color for `NavigationBar`'s
  selected/unselected tinting, so it's read explicitly. Used for both
  `icon`/`selectedIcon` (same single shape, no separate filled variant
  the way Material's outlined/filled icon pairs work).

Verified: `flutter analyze` clean, `flutter test` still passes 10/10
(would fail if the SVG asset were malformed/unloadable, since
`HomeShell` renders in the widget tests), `flutter build macos --debug`
succeeds and the built app launches without crashing (confirmed via
`ps aux`). **Could not visually confirm via screenshot** -- no
screen-recording permission in this environment (`screencapture` failed
with "could not create image from display") -- said so explicitly
rather than claiming a visual match I hadn't actually seen.

### Meshpoint detail sheet: action button was scrolled off-screen by default

User screenshot: opening a meshpoint's detail sheet showed only the
very top edge of "Switch to this meshpoint" cut off at the window's
bottom edge, requiring a manual drag-up to reach it -- reported as
"weird feeling." Root cause: the button was the last item *inside* the
scrollable `ListView` alongside the 7 status rows, and the sheet's
`initialChildSize: 0.5` wasn't tall enough to fit all of that without
scrolling -- so the one thing you actually came to this popup to do
(switch to the meshpoint) was the first thing pushed off-screen.

Fixed properly, not just by nudging the size up: restructured the
`Column` so the button is a fixed `Padding` sibling *after* the
`Expanded(ListView(...))`, not part of the scrollable content -- only
the status rows scroll now, the action button is always visible the
instant the sheet opens regardless of how tall it ends up. Also bumped
`initialChildSize` 0.5 -> 0.6 (`minChildSize` 0.35 -> 0.4) so the status
rows themselves need less scrolling too. `flutter analyze` clean,
`flutter test` passes 10/10, `flutter build macos --debug` succeeds.

**Follow-up, same sheet**: even after the fix above, user pushed back
with a real screenshot showing the sheet still felt "weird" -- all 7
rows + button were already fully visible with empty space below, yet
the sheet still let you drag/scroll it, which reads as broken ("why can
I scroll when there's nothing more to see?"). Asked for my take before
touching code (per this session's own established pattern of
discuss-then-confirm for anything past a one-line fix); diagnosis: the
whole `DraggableScrollableSheet` was the wrong tool here. It's right for
`NodeDetailSheet` because a node's info is genuinely variable-length
(optional hardware/signal/telemetry/position sections). A meshpoint's
info is always the same fixed ~7 rows -- there's nothing to
drag-resize or scroll, so offering that affordance was itself the bug,
not just the initial sizing.

Fix, once confirmed: dropped `DraggableScrollableSheet` (and its drag
handle) entirely for `MeshpointDetailSheet` specifically -- plain
`SafeArea > Container > ConstrainedBox(maxHeight: 85% of screen) >
SingleChildScrollView > Column(mainAxisSize: min)`. Sizes itself to its
actual content; the `SingleChildScrollView`/`ConstrainedBox` are a
quiet safety net only (kicks in on a genuinely tiny screen with a long
device name), not a visible/advertised affordance -- no handle bar, no
suggestion you can drag it. `showModalBottomSheet`'s own
`isScrollControlled: true` is what lets it size past the default ~50%
cap. `NodeDetailSheet` itself was deliberately left untouched -- its
variable-length content is exactly the case `DraggableScrollableSheet`
is right for.

`flutter analyze` clean, `flutter test` passes 10/10, `flutter build
macos --debug` succeeds. **Real gap, not silently glossed over**: no
test in this suite actually opens `MeshpointDetailSheet` at all --
`widget_test.dart` never adds a meshpoint, so the sheet is never
triggered. Verification here was analyze + build + the user's own
screenshots, not an automated assertion. Worth a real widget test if
this sheet gets touched again.
