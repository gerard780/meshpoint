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
