# Changelog

### Unreleased

- **MQTT broker TLS.** Transport TLS (`mqtts`, CA bundle, cert validation) is not implemented on `mqtt_publisher.py` (plain TCP only). Until then use plain port 1883 or a LAN broker without TLS.

### v0.7.9 (July 2026)

First tagged release of the javastraat/meshpoint fork. Adds LoRaWAN sniffing, multi-radio capture, an RTL-SDR web listener, and a dashboard self-update fix, on top of everything merged from upstream's v0.7.7 (backup/restore, RF Environment tab, mesh broadcast cadence, operator tools). Run `install.sh` when upgrading. **Boxes still on v0.7.6:** the dashboard's own updater can't fetch this release — run this once over SSH, then updates from the dashboard work again: `cd /opt/meshpoint && sudo git fetch origin main && sudo git reset --hard origin/main && sudo systemctl restart meshpoint`.

#### LoRaWAN sniffing (SX1302)

- **Passive LoRaWAN capture on EU868.** Listens on five LoRaWAN channels alongside Meshtastic, without interfering with it.
- **LoRaWAN MAC decoder.** Shows join and data-uplink frames (device IDs, frame counts); payloads stay encrypted since we don't have the session keys — this is listen-only.
- **LoRaWAN dashboard page.** New page for devices, recent packets, and stats.
- **Strict isolation.** LoRaWAN traffic is never relayed and never mixed into the mesh node list or telemetry.
- **CSV export on every protocol page.** Export buttons on LoRaWAN, Meshtastic, and MeshCore download the full packet or device history, not just what's on screen.
- **FPort/FCnt show up in the packets log.** These two LoRaWAN columns were always blank; fixed.
- **LoRaWAN packet-detail decrypt state now matches the live feed.** The packet detail popup and the live dashboard used to disagree about whether a packet was decrypted.
- **LoRaWAN packet detail keeps metadata visible when payload keys are missing.** Encrypted LoRaWAN packets without the right keys now still show their header info instead of hiding everything.
- **LoRaWAN Devices and Meshtastic Nodes tabs show a "(N of M)" count** next to the search box, matching MeshCore's Contacts tab. The count updates automatically as you narrow the list down with the search box.
- **Search added to the MeshCore Contacts tab**, matching the search already on LoRaWAN and Meshtastic. It matches against a contact's ID or name, rounding out search being available on all three protocol pages.
- **Fixed: the packet search box sometimes stayed visible on the wrong tab.** Switching from the Devices/Nodes tab back to Recent Packets could leave the search box stuck on screen, still filtering out packets underneath it.
- **MeshCore Contacts no longer paginates.** All contacts show in one list, like the other protocol pages.
- **Search filter added to LoRaWAN Devices and Meshtastic Nodes**, with a clear button and results that persist across auto-refresh. It was piloted on LoRaWAN Devices first, then rolled onto Meshtastic Nodes using the same search widget.
- **Fixed a channel-selection bug on the LoRaWAN service channel.** The Meshtastic service channel now picks its radio chain based on its actual frequency instead of always defaulting to the same one.

#### DAPNET (POCSAG companion)

- **New Networks → DAPNET page.** Captures pages from a connected DAPNET/POCSAG companion board, separate from the older RTL-SDR-based POCSAG decoder on the Listener tab.
- **DAPNET capcode filters.** Two new filter tiers hide routine network-housekeeping pages so real traffic isn't buried in noise; configurable from Configuration → POCSAG.
- **DAPNET only shows in the sidebar once its capture source is enabled.** This keeps the sidebar uncluttered for anyone who hasn't set up a DAPNET companion, matching how other optional features stay hidden until turned on.
- **DAPNET sidebar icon fixed.** The old icon looked like a briefcase, not a pager. It's now a proper pager shape, matching what the feature actually is.
- **Long DAPNET messages no longer get cut off** in the Recent Pages/Capcodes tables. They were being silently truncated mid-sentence by a table layout designed for short LoRaWAN identifiers, not free-text pages.
- **Fixed: the DAPNET page wasn't scrollable.** It was missing from the list of pages allowed to scroll independently, so long tables had no way to be seen in full.
- **`meshpoint logs` no longer shows a fake "perfect signal" for DAPNET**, and now includes the decoded message text. DAPNET pages have no real signal reading at all, but a missing value was defaulting to a number that displayed as a perfect signal bar.
- **Companion firmware and status: new topbar badge** showing each DAPNET companion's callsign, frequency, and board — the same style as the Meshtastic/MeshCore badges. It's hidden entirely until a POCSAG companion is actually configured, the same way the sidebar link only appears once one is set up.
- **Configuration → POCSAG shows live readouts per device** (callsign, frequency, hardware), matching the Serial/MeshCore pages. It shows fewer tiles than those cards on purpose, since POCSAG is fixed-frequency and has no bandwidth or spreading-factor settings to display.
- **Fixed: capcodes newly added to a filter still showed old, already-stored pages.** Adding a capcode to a filter now also purges its already-stored history.
- **Operator callsign is now settable from Configuration → POCSAG**, not only the companion's own web page. Nothing is stored on the Meshpoint side — the callsign lives entirely on the companion itself, the same as saving it directly there.
- **Readout tiles gained a "Web UI" link** straight to the companion's own dashboard. It links to the companion's IP address rather than its network name, since name-based lookup isn't always reliable from a browser.
- **DAPNET status now polls periodically**, showing TX count, last TX result, and uptime, not just a one-time snapshot. Previously this info was only fetched once when the companion first connected and never updated again.
- **The POCSAG companion's web dashboard password is now settable from Configuration → POCSAG.** The password is never shown or logged anywhere in Meshpoint itself, only relayed straight through to the companion.
- **New "Reset Callsign & Password" button** on Configuration → POCSAG for quickly clearing just those two settings. It leaves other companion settings, like screen timeout, untouched.
- **WiFi SSID/password and a reboot button** are now settable from Configuration → POCSAG too — lets a brand-new companion be fully set up without ever opening its own web page. Changing WiFi takes the companion off its current network until it reboots, so it's a separate, more deliberate action from the other quick settings.
- **The companion's own web dashboard gained Hardware and Connection info cards**, plus a callsign/hostname shown before login. These make it possible to confirm a serial-set WiFi change actually worked without ever leaving the companion's own page.
- **POCSAG readout tiles now also show the companion's WiFi network name.** This makes it easy to confirm a serial-set WiFi change actually took effect, right from the Meshpoint dashboard.
- **Fixed: the Web UI link turned an unreadable purple once clicked.** The link had its own default browser link color instead of matching the rest of the readout tile.
- **Fixed: DAPNET pages showed garbled sender/recipient info and had them backwards** in the Dashboard packet feed. Existing pages aren't fixed automatically — a cleanup script is available if needed.
- **Companion firmware can now be built and flashed straight from the dashboard.** A new "Companion firmware" card on Configuration → POCSAG compiles and flashes the DAPNET companion sketch with live progress output, no separate toolchain setup required.
- **`install.sh` now also installs a plain `esptool` command**, needed for flashing spare boards with official Meshtastic firmware. It's a separate, plain command on the system path, distinct from the copy already bundled privately inside the other toolchain install.
- **Configuration → Serial gained a "Meshtastic firmware" card** for turning a spare board into a Meshtastic USB stick straight from the dashboard, with live flash progress. No compiling is needed, since official Meshtastic firmware is already prebuilt upstream.
- **Configuration → Serial can set a connected Meshtastic USB stick's LoRa region**, most useful right after flashing a board fresh (it won't transmit until a region is set). Meshtastic ships with no region set by default, so a freshly flashed board stays silent until one is chosen.
- **Configuration → Serial can also set a stick's Bluetooth settings** (on/off, pairing mode, PIN). This leaves the choice up to whoever's setting up the stick, rather than forcing Bluetooth on or off automatically.
- **Configuration → Serial can also set a stick's modem preset and its own NodeInfo/telemetry broadcast intervals.** None of these are strictly required to get a stick working, but they give full control over a freshly flashed device without needing a separate app.
- **Fixed: the new Region/Bluetooth/Preset controls looked visually inconsistent** with the rest of the app; restyled to match. They'd each been wrapped in their own separate bordered box, unlike every other page in Configuration.
- **Configuration → Serial's per-device settings now sit in two clean sub-cards** ("Modem settings" and "Other settings") matching the rest of Configuration's look. This replaces the earlier flat-field layout with the same card structure used elsewhere in Configuration.
- **Configuration → MeshCore gained a "MeshCore firmware" card**, the same flash-from-dashboard feature as Serial's, for turning a spare board into a MeshCore USB companion. Like the Serial card, no compiling is needed since official MeshCore releases are prebuilt.
- **The MeshCore firmware card can now pick a specific version and flavor to flash, and flash any connected USB device, not just an already-configured companion.** Previously it always grabbed the newest official release, only offered the USB-connectable build, and only let you flash a board already added as one of this box's own companions. Now there's a version dropdown (defaulting to latest, useful for deliberately matching two companions to the same version) and a flavor dropdown (USB, for boards that connect to this dashboard; BLE, for a spare board headed to someone who wants to pair it with the official MeshCore phone app instead). The device picker now lists every currently-connected USB-serial device, so flashing a one-off or a friend's board no longer means adding it as a permanent companion first just to remove it again afterward.
- **The MeshCore firmware card moved to its own Configuration → Firmware page.** Flashing a spare board is a different kind of action than configuring an already-assigned companion's channels and radio settings, so it no longer sits buried inside Configuration → MeshCore's own settings -- it's now a standalone page under the Companions section, alongside the "spare board" workflow generally. Serial (Meshtastic) and POCSAG firmware flashing are expected to join it here later; for now it's just MeshCore's card, moved as-is. **Same-day fix**: the new page briefly showed "Admin access required" even when logged in as admin -- the frontend router's own allowed-routes list was updated for the new page, but a separate server-side list (`identity_routes.py`, what actually decides which sections a role can reach) still didn't know `configuration.firmware` existed. Added it there too. **Same-day expansion**: the Board field only offered this project's own 2 boards (Heltec V3, TTGO LoRa32). Now that flashing lives on its own page, it offers MeshCore's real board catalog instead -- searchable (type to filter, ~30 boards), refreshed live from whichever release+flavor is actually selected rather than a hardcoded list (only ESP32-family boards that ship a self-contained, esptool-flashable file even show up; the ~44 nRF52-family boards that need drag-and-drop UF2 flashing instead are correctly absent, since this route has no way to flash those at all). Also switched from a hardcoded per-board chip type to esptool's own `--chip auto` detection, removing a class of bug this project could never have fully caught anyway (verifying ~30 boards' real chip families would need owning all of them). **Same-day polish**: the Version/Flavor/Board/Device fields were still using the old card's narrow 140px width, clipping real values like board names and release tags; widened to 340px (scoped to this page, not the shared narrow-field style ~30 other fields elsewhere still use), and fixed the gap above the action buttons, which had stayed attached to the Board field after the field order changed instead of the actual last field (Device to flash). **Same-day addition**: both the release list and the USB device list are one-time fetches at page load, not kept live by a periodic poll -- added "↻ Refresh" (Version) and "↻ Rescan USB" (Device to flash) buttons so a MeshCore release published, or a board plugged in, while already on the page shows up without needing to reload it.
- **The Meshtastic firmware card also moved to Configuration → Firmware, under MeshCore's, and picked up the same version/board-search/rescan treatment** -- fulfilling the "expected to join it here later" note above, same day. One real difference from MeshCore, worth knowing: Meshtastic has no Flavor field. MeshCore ships separate BLE-only and USB-only builds per board; Meshtastic's per-board firmware already covers BLE+USB+WiFi together in one image, so there's nothing to pick there -- copying MeshCore's picker shape verbatim would have offered a choice that doesn't exist. The Board field is the same searchable-datalist idea, but pulls from Meshtastic's own real per-release manifest (confirmed live: 129 real board targets) rather than filename-pattern-matching release assets the way MeshCore's does, since Meshtastic ships one manifest file per release listing every board directly. Chip type was never a problem here in the first place -- the manifest's own per-board metadata already names the real MCU, so (unlike MeshCore, which needed `--chip auto` because no such manifest exists) this route always could and still does pass the real chip directly to esptool. Device-to-flash now accepts any connected USB-serial device instead of only an already-configured Serial device, matching MeshCore's card exactly.
- **The POCSAG companion firmware card also moved to Configuration → Firmware, under Meshtastic's** -- completing the plan noted above. Unlike the other two, this one still compiles from source (`extra/pocsag_companion` via arduino-cli) rather than downloading a release, so there's no Version/Flavor field and Compile stays its own step, separate from Flash. **Same-day fix**: the "Device to flash" picker only ever listed already-configured POCSAG companions, and silently defaulted straight to the sole one whenever there was only one — meaning Flash always targeted whatever board was already deployed unless you noticed the (usually hidden) picker and switched it. It's now the same any-connected-USB-device picker as the MeshCore/Meshtastic cards, with a "↻ Rescan USB" button, and always requires an explicit pick.
- **The Meshtastic and MeshCore firmware cards can now upgrade a board in place without erasing its settings.** Flash always ran esptool's `--erase-all`, so re-flashing your own already-configured node to pick up a new version wiped it back to factory defaults every time -- Meshtastic's littlefs partition (channels, module config, node database) and MeshCore's spiffs partition (identity, contacts, channels) both got erased right along with the app itself. A new "Erase everything" checkbox on each card, on by default (unchanged behavior for a spare/foreign board), can be turned off to skip `--erase-all` and leave that partition untouched -- matching the "keep settings" option in Meshtastic's own official web flasher. MeshCore never wrote its filesystem partition as a separate step to begin with (`*-merged.bin` only covers bootloader+partition-table+app, ending well under where its spiffs partition actually sits), so there was nothing extra to skip there beyond the one flag.
- **Configuration cards use more of the screen on phones.** The page and card padding, plus the Firmware page's 340px field cap, were sized for desktop and left a wide unused gutter on both sides of every card on a phone -- narrower now below 480px.
- **Fixed: a failed Configuration data fetch (e.g. the Firmware page's Version/Board lists) used to fail completely silently.** Found live when GitHub's unauthenticated rate limit (60 requests/hour/IP) got exhausted after a heavy firmware-testing session -- the Version/Board dropdowns just stayed empty with no visible error anywhere, since the shared request helper only ever toasted a failure for saves (PUT/POST/DELETE), never for a plain read. Reads now toast the real server error too (e.g. "Error: Could not fetch Meshtastic releases: HTTP Error 403: rate limit exceeded"), across every Configuration card, not just Firmware.
- **DAPNET's Recent Pages/Capcodes tables got two mobile fixes.** Message text no longer wraps awkwardly on narrow screens. Rows are now clickable for a full detail popup, like the other protocol pages already have.
- **Clicking a capcode now shows its full message history.** The Capcodes tab previously only showed the single most recent page per capcode; clicking a row now opens a popup listing every page that capcode has ever received. Clicking any page in that list opens the same full detail popup used everywhere else.
- **New Send tab on the DAPNET page** — sends a POCSAG alpha page through a connected companion straight from the dashboard, with a real success/failure result instead of a fire-and-forget guess. The companion firmware now replies with a definitive result for every serial-triggered send (previously only logged as a plain-text line the dashboard couldn't see), so the Send tab can show "Sent." or the real error (e.g. no callsign configured) rather than assuming it worked. Device picker only appears when more than one POCSAG companion is configured. **Fixed same day**: the Send tab always showed "POCSAG companion not connected" even on a live companion — it was reading the configured-device list from the wrong place (`config.pocsag_serial` instead of the real `config.capture.pocsag_serial`), so it could never actually find a match. **Also same day**: the Send tab is now hidden entirely for the viewer role (matches every other write action in the app — the send endpoint already required admin server-side, this just keeps a viewer from seeing a control they were never able to use).

#### Setup wizard

- **Setup wizard lets you skip upstreaming entirely.** You can now say no to sending data to meshradar.io without needing to enter an API key.
- **Setup wizard can set the device's network hostname to match its device name**, so it's reachable as `<name>.local`. Only offered on a fresh install, not on upgrades.

#### Multi-radio capture (5 networks at once)

- **Multiple MeshCore USB companions** can now be configured at once (up to 4), each labeled and tracked separately, editable from Configuration. Each companion's packets are tagged with its own label so you can tell which physical device captured what.
- **Fixed: labeling a MeshCore companion could silently disable its transmit/status.** The dashboard's lookup for "which companion is connected" only matched an exact name, which broke the moment a companion got a custom label.
- **MeshCore signal metadata** (frequency, bandwidth, spreading factor, hop count) now reported correctly per companion. Each companion now reports its own real connect-time radio settings instead of a shared or guessed value.
- **Simultaneous LoRaWAN + Meshtastic 868 + MeshCore 868/433 + Meshtastic 433** all run side by side on one box. Only Meshtastic traffic is ever relayed onward; every other network stays listen-only.
- **Chat header shows which physical radio a conversation is on** (e.g. "433", "868", "Concentrator"), including several follow-on fixes for missing styling, slow loading, and channel/broadcast conversations. This matters once a box has more than one radio on the same protocol and the usual protocol badge alone can't tell them apart.
- **Fixed: the Messages page headers were invisible** on real deployments — the whole panel was sized one topbar too tall. Opening a conversation would push both the chat header and sidebar header up out of view with no way to scroll back to them.
- **Channel pills are now per-channel, not shared across a whole protocol.** With two same-band companions, every channel used to show the same (sometimes wrong) badge.
- **Fixed: the topbar chip row didn't wrap on narrow/mobile screens**, so extra chips could run off-screen. A second MeshCore companion or Meshtastic stick's chip could end up completely unreachable on a small screen.
- **Fixed: concentrator Meshtastic transmissions were invisible to real Meshtastic radios** — a wrong radio setting meant sent messages, replies, and adverts never actually reached the mesh, even though everything looked fine locally. The dashboard showed messages as sent successfully the whole time, masking the problem until it was checked against a real radio.
- **Fixed a real regression caught by the test suite** after refactoring how companion names are stored and applied. The automated tests caught it before it ever reached a live deployment.
- **Fixed: a blank second serial-device row could crash startup.** Saving the Meshtastic USB serial list with an empty "Device 2" row persisted `serial_port: null`, which auto-detects on start — colliding with whatever port Device 1 already had exclusively locked and crashing the pipeline. Blank rows among 2+ configured devices are now dropped on save instead of persisted as an ambiguous auto-detect entry (a single device with no port is still valid auto-detect).

#### RTL-SDR web listener (Radio tab)

- **Browser radio via RTL-SDR dongle.** Stream live FM/AM/etc audio in the browser with tuning, squelch, gain, and level controls.
- **RDS on broadcast FM.** Shows station name, RadioText, and signal quality while tuned to FM.
- **Two radio faces.** A digital and an analogue skin, your choice persists per browser.
- **Preset stations.** Favorites, categories, and search across FM, PMR446, marine, airband, and ham presets.
- **Real-time VU meter.** It reads live audio levels straight in the browser, instead of polling a slower loudness estimate from the server.
- **Clean retunes.** Fixed a "device busy" error on fast channel switches.
- **P2000 and Pagers tabs.** Decode live Dutch emergency dispatch (P2000) and general pager (POCSAG) traffic. Since the dongle can only tune one frequency at a time, only one Listener tab can be active — the others clearly show which one is busy.
- **POCSAG tab.** A dedicated tab for POCSAG paging traffic on its own frequency.
- **Cleaned up the skin toggle and status indicators** so they only show on tabs where they're relevant, and busy/idle states read clearly. These controls previously kept showing on tabs like P2000 or POCSAG even though those tabs have no skin or on-air concept of their own.
- **Sidebar shows when the RTL-SDR dongle is in use**, from anywhere in the dashboard. A badge on the RTL-SDR sidebar item names which tab currently holds the dongle, so there's no need to open the Listener page just to check.
- **RTL433 tab.** Decodes weather stations, tire-pressure sensors, and hundreds of other short-range devices.
- **Fixed: frequency display was rounding away real precision** on some tabs; now consistently shows 4 decimal places everywhere. The POCSAG tab in particular was rounding its frequency down to 3 decimal places, silently losing a real digit.
- **Mini radio player in the sidebar.** While FM radio is playing, a compact player (station name, mute, stop) stays visible on every page, not just the Radio tab.
- **DAB+ tab.** Browser playback of Dutch DAB+ digital radio, with a channel/station picker, favorites, and live signal quality. Went through several rounds of live tuning to confirm the right channel presets for this location.
- **ADS-B tab.** Live aircraft tracking from 1090ES transponder signals, shown as a table and on a live map with flight trails, aircraft type/registration/route lookups, and photos where available.
- **Start-listening buttons now grey out once already running**, across P2000/Pagers/POCSAG/RTL433/ADS-B. Previously the button only disabled when a different tab held the dongle, so it stayed clickable while your own tab's listener was already active.
- **ADS-B flight detail popup**, showing registration, aircraft type, operator, route, and photo when available, plus flight trails on the map and aircraft dropping off the map once they go stale. The registration, type, and route lookups come from two free public aircraft databases, not from the radio signal itself.
- **`dab_channel_scan.py` now records each station's unique ID, not just its name**, fixing occasional failures to auto-play a favorited station. A station's broadcast name can carry small formatting differences between scans, but its ID stays stable, so matching by ID is far more reliable.
- **DAB+ Config page can now run a channel scan itself, with live output** — previously this required SSH access. A Full scan button covers every channel, or specific channels can be picked for a faster targeted rescan.
- **Clear button added to P2000, Pagers, POCSAG, and RTL433**, to clear the on-screen message history without stopping the listener. Previously the only way to get rid of old messages was to stop the listener entirely or reload the page.
- **"Hide idle frames" checkbox added to P2000, Pagers, POCSAG, and RTL433**, to filter out structural noise frames that aren't real messages. POCSAG in particular can flood the log with routine filler frames that carry no real message text.
- **DAB+ Config tab.** Shows every channel a scan has found content on, with an editable display name per channel; later extended to also list known stations per channel and support playing/favoriting them directly from this list.

#### Roles and access

- **Login page no longer prefills the username.** Both fields now start empty on every visit to the login page.
- **Role permissions now correctly cover LoRaWAN, Meshtastic, MeshCore, and RTL-SDR pages.** These sections were missing from the permission lists behind each role, which could affect how future access gating on those pages behaves.
- **SDR start/stop/tune actions are now properly admin-gated too** — previously any logged-in viewer could retune the dongle or stop a running decoder. This closes the gap across the RTL-SDR, DAB+, and pager listener tabs; the read-only status views stay open to viewers as before.

#### Hardware page and band spectrum

- **Band spectrum card on the RF Environment page.** Sweeps the whole radio band every 5 minutes and shows a spectrum chart with LoRaWAN/Meshtastic/MeshCore channel markers overlaid.
- **Fixed: spectrum scan sometimes reported peak signal below the median** on this hardware, throwing off the noise-floor reading. The scan data came back in the opposite order this code expected, which flipped which readings counted as the floor versus the peak.
- **Concentrator channel plan visible on the Hardware page.** A new card lists every radio channel's frequency, bandwidth, and settings.
- **Hardware page: Meshtastic settings unified into one card.** The separate Channels card is gone, and its channel list now lives inside the same Meshtastic Configuration card.
- **MeshCore Companion card shows firmware version**, with a hover for model and build date. Older companion firmware only reports a bare version number, while newer firmware also includes the model and build date.
- **"Check for updates" button next to the firmware readout** compares against the latest official MeshCore release. It's a manual, on-demand check rather than automatic background polling, since companion firmware only changes when the device is physically reflashed.
- **Serial (Meshtastic USB) card gains live readouts per device** — node ID, name, region, settings, firmware, hardware model. This mirrors the same live readouts the MeshCore Companion card already showed.
- **Serial and MeshCore Companion cards brought to near-parity**, so both show the same set of live readouts (frequency, bandwidth, TX power, firmware, hardware, etc). Region stays Serial-only, since MeshCore configures raw radio settings directly rather than using Meshtastic's named-region system.
- **Serial card gets a "Check for updates" button too**, matching MeshCore's. It checks each connected stick's firmware against the latest official Meshtastic release.
- **MeshCore's USB sources card now shows live readouts per companion**, not just the primary one — previously a second or third companion showed nothing. Each companion now reports its own connection state and radio info independently.
- **Every MeshCore companion can now be renamed and adverted independently**, not just the primary one. Previously only the first configured companion could be renamed at all.
- **Topbar now shows one MeshCore chip per companion**, matching how Meshtastic USB sticks already work, with several follow-on styling and ordering fixes. Meshtastic and MeshCore chips are now also grouped together by protocol instead of interleaved.
- **Meshtastic USB serial devices can now be renamed from the dashboard** — useful since these sticks have no Bluetooth app path for renaming. This is the only practical way to rename them, since the official Meshtastic app's usual Bluetooth path doesn't apply to a USB-only stick.
- **Meshtastic and MeshCore tabs' packet tables gain a Frequency column**, useful now that both protocols can run on two bands at once. This makes it possible to tell which physical radio a packet came from directly from the packet table, not just the Dashboard feed.
- **Serial port fields now suggest connected USB devices** and prefer stable, reconnect-proof device paths over ones that can shift around. Went through several rounds of refinement: filtering out unrelated onboard ports, clearer labels, and warnings when a port is already used by another device.
- **`install.sh` skips reinstalling tools that are already present**, speeding up repeat installer runs. This covers rtl_433, the DAB+ decoder, and the Meshtastic/MeshCore command-line tools, which previously reinstalled on every single run.
- **Fixed: MeshCore packets could be stored under the wrong companion's label**, masking which physical companion actually captured them. A hardcoded label meant every packet looked like it came from an unlabeled companion, even on boxes running two or more.
- **New Stray Frames card on the RF Environment page**, showing radio frames that don't decode as any known protocol, for diagnostics. Previously these frames simply vanished with no trace; now up to 500 recent ones are kept in memory for inspection.
- **Fixed: the "no scan yet" placeholder message on the channel histogram sometimes stayed visible after a real scan loaded.** It could overflow past its own box and spill into whatever card sat below it on the page.

#### Stats and node insights

- **Fixed: charts and node history could silently stop updating once a device's history grew large enough.** Long-running charts now always show the full history, evenly sampled, instead of quietly truncating.
- **Mesh topology graph.** A new Topology page draws the mesh as a live, interactive graph — nodes colored by protocol, edges from real traceroutes/receptions/neighbour reports — with a map view, filters, and click-through to node details. Updates live as new data comes in.
- **Recent packets shown in the node drawer**, for both Meshtastic and MeshCore nodes. Opening a node now shows its last several packets alongside its existing metrics history.
- **Near-field packets no longer skew signal stats.** Readings from a node sitting right next to the antenna no longer distort the "best signal" figures.
- **Network totals no longer capped at 500 nodes.** The Stats page and CLI report were both silently under-counting nodes, positions, and packets on larger installs.
- **Total Packets tile now shows 24h / total**, matching the Nodes Discovered tile's style. This pairs the last day's activity with the all-time count in one glance.
- **Fixed: "Farthest Direct Signal" could show an imported repeater** instead of a genuinely direct reception. Historical data imported from a repeater's own neighbour list was being counted as if this box had heard it directly itself.
- **Range card subtitles now say more precisely what they measure.** One subtitle in particular was easy to misread as protocol-specific when it actually combines every network this box listens to.
- **Fixed: "Farthest Direct Signal" could miss genuinely direct Meshtastic contacts**, and in one case showed an implausible 743 km "direct" reading. It's now based purely on live session data, which is more conservative but honest — it can read "--" right after a restart until a real direct reception comes in.
- **Fixed: a node with no GPS fix could win "Farthest via Meshtastic".** A node that hasn't gotten a GPS lock yet reports position (0, 0) instead of no position at all, which looks exactly like a real reading at "Null Island" off the coast of Africa — thousands of km from any real deployment, so it was winning the farthest-node record by default. All three "farthest" stats (Direct Signal, via Meshtastic, MeshCore Contact) now reject that (0, 0) sentinel and share the same distance sanity cap, instead of each one having its own inconsistent checks.
- **Fixed: the "Avg Signal Quality" donut on the Stats page never showed its actual number**, just an empty ring. The dBm reading was being computed correctly the whole time; the chart code just never had the piece that draws text in the middle of the ring, unlike the two other donuts on the same page, which already did.
- **Fixed: mains/USB-powered Meshtastic nodes (like this concentrator itself) could show a nonsensical "101%" battery reading.** Meshtastic firmware uses `battery_level: 101` as a documented sentinel meaning "externally powered, no battery attached," not a real percentage — now shown as "🔌 Powered" on node cards, the node drawer, the packet feed, and the packet detail modal, and excluded from the battery history chart so a powered node doesn't draw a spike above the 100% axis.
- **Fixed: node cards showed a magnifying-glass icon for low battery, and reused the plug icon for "medium" charge.** Both were bugs: the low tier's emoji codepoint was an off-by-one typo unrelated to batteries, and the medium tier's plug icon collided with the new "Powered" chip above once both existed in the same file. Battery now uses the same green/amber/red severity-color chips signal strength already does (>50% / 26-50% / ≤25%), with a proper low-battery icon at the bottom tier — 🔌 is now used only for "Powered."

#### Configuration and server

- **Named, revocable API keys for read-only status endpoints**, so tools like Home Assistant or Prometheus can authenticate without a full dashboard login. Each key is scoped to just metrics/status data, never configuration changes.
- **Fixed: fresh installs could crash on the config page** due to a blank config value being treated as invalid. A brand-new install's config file could have an empty value that the settings page didn't know how to handle.
- **Installer now installs all the build dependencies needed for fan/LED/button support**, so a fresh install no longer fails partway through. These packages were previously documented in the troubleshooting guide but missing from the installer itself.
- **Installer sets up RTL-SDR support end to end** — driver conflicts, permissions, and the RTL-SDR library are now all handled automatically. Previously this all had to be done manually on every box, including working around a kernel driver that would otherwise claim the dongle before Meshpoint could use it.
- **Installer builds redsea**, giving the FM listener RDS station/radio-text decoding. This is what lets the Radio tab show station names and scrolling text while tuned to FM.
- **Installer sets up mDNS**, so a fresh box is reachable as `meshpoint.local` without knowing its IP. Previously an IP address was the only way to reach a brand-new box before it had a fixed address.
- **Fixed a rare channel-hash mismatch** that could route messages to the wrong channel when config was reloaded in a different order. The inbound and outbound hash calculations could disagree about which hash belonged to which channel, depending on load order.
- **Installer builds multimon-ng**, the decoder behind the POCSAG/pager tabs. It's built from source rather than an outdated package, since the project's older build system is no longer available in current Raspberry Pi OS repositories.
- **Installer installs rtl_433**, a generic short-range sensor decoder (dashboard integration not yet built). It covers weather stations, tire-pressure sensors, and hundreds of other short-range devices, though there's no dedicated dashboard tab for it yet.
- **Installer installs the Meshtastic and MeshCore CLI tools**, handy for admin debugging from the Pi's own shell. Meshpoint itself doesn't use these tools directly; they're just there for manual troubleshooting.
- **Installer adds a system-info banner on login.** Every SSH or console login now shows a quick splash of OS, uptime, CPU temperature, and memory info instead of a plain prompt.
- **Quieter boot log.** MeshCore contact sync no longer floods the log with the full roster on every boot.
- **Startup banner now shows one line per capture source**, with each radio's real frequency plan. Previously the banner only showed a single frequency, even when several radios were actually running.
- **Web server port is now set in config**, rather than hardcoded, with a safe fallback if the configured address can't be used. If the configured address can't be bound for any reason, the dashboard falls back to a default address instead of failing to start.
- **Relay burst size and RSSI filters are now editable from Configuration → Transmit.** These settings previously required hand-editing the config file even though the underlying feature already existed.
- **MeshCore channel limit raised from 7 to 40.** This matches the number of channel slots a MeshCore companion can actually hold.
- **Removed a handful of unused API endpoints** that nothing in the dashboard or CLI actually used. These were left over from earlier versions of features that have since been replaced by other endpoints.
- **Prometheus metrics gets its own Configuration page**, no more hand-editing config files to turn it on. This was the last major settings section without its own page in the dashboard.
- **Configuration sidebar reorganized into labeled groups**, and a new POCSAG companion config page was added. The previously flat list of config pages is now split into Companions, Network, Hardware, and System groups.
- **Configuration → MeshCore can now change a companion's radio frequency/bandwidth/settings directly from the dashboard.** It offers the same list of official MeshCore region presets as the command-line tool, without needing to stop the whole service to apply a change.
- **Fixed: a MeshCore companion whose command channel silently died could get stuck "connected" forever**, blocking every dashboard action against it until a manual unplug. Ongoing reception could mask the problem, since the health check skipped its own recovery step whenever there'd been recent activity.
- **Fixed: MeshCore reconnect attempts could sometimes run twice at once**, causing extra radio resets. Two separate triggers could each start their own reconnect at the same time, both resetting the same physical connection.

#### CLI

- **`meshpoint report` works again.** It had been broken since login was added to the API.
- **`meshpoint report` now covers all networks**, not just the primary radio. It now shows packet counts, node counts, and frequency/status for every configured protocol and capture source, not just one.
- **`meshpoint report` now also lists Meshtastic USB serial sticks.** Previously a connected serial radio produced no line at all in the report, even though the dashboard already knew about it.
- **`meshpoint report` no longer merges two physically separate Meshtastic networks into one stat line** (e.g. a concentrator and a USB stick on different frequencies). Each radio now gets its own line, since two sticks on different frequencies are really separate meshes that can't talk to each other.
- **`meshpoint meshcore-radio` now offers the full official list of MeshCore region presets** (20 regions), instead of just three. The list is transcribed directly from the official MeshCore app's own picker, so the presets match what a real MeshCore user would choose.
- **`meshpoint report` now lists the DAPNET/POCSAG companion too**, matching the treatment MeshCore and Meshtastic serial sticks already got — packet count and unique capcodes in PROTOCOLS, and USB port/connection state/callsign/board in CAPTURE SOURCES. Previously a connected pager companion produced no line at all, even though its packets already counted toward the RX Traffic totals.

#### Dashboard and UI

- **Node names now show in the Meshtastic packets feed**, instead of bare IDs; matched the page layout and packet-type colors across all three protocol pages. The MeshCore and LoRaWAN pages already showed names this way; this brings the Meshtastic feed in line with them.
- **Fixed: the "Add to Home Screen" app icon looked smaller than every other icon next to it.** Also added proper Android/Chrome home-screen support, not just iOS.
- **Fixed: reloading on any page other than Dashboard briefly flashed the Dashboard page before jumping to the real one.** This happened because the Dashboard page was the only one that started visible by default, while every other page waited for the rest of the app to finish loading before showing itself.
- **Tab switch added to all protocol pages** — one panel with Recent Packets / Contacts / Nodes / Devices tabs instead of two stacked tables. Both views keep refreshing in the background, so switching between them is instant.
- **Messages tab now shows overheard DMs by default**, so a repeater-only box's Messages tab doesn't look empty. A box mostly used as a repeater or observer sees almost entirely overheard traffic, which previously stayed hidden until manually toggled on.
- **Favorite channels in the Messages tab.** Star a channel to pin it to the top of your own view.
- **MeshCore channel order is now editable from Configuration → MeshCore.** Up/down arrows next to each channel let you reorder them, with Public always staying first.
- **Packet detail popup everywhere.** Clicking any packet row, on any page, opens a full breakdown (radio info, routing, decoded payload) — with cleaner formatting for MeshCore, LoRaWAN IDs, and MeshCore advertisement node types, and an expandable details view for less-common fields.
- **Consistent signal-strength colors** across the dashboard feed and all protocol pages — the same signal used to show a different color depending on which page you were looking at. The Dashboard feed used a stricter color scale than the protocol pages, so identical signal readings could show green on one page and amber on another.
- **Topbar chips unified** to a consistent style, and all three now clearly show "Reconnecting…" when the dashboard connection drops, instead of quietly showing stale data. Previously one of the three chips kept displaying old values with only a small lamp-color change when the connection actually dropped.
- **Sidebar regrouped** into Networks / Radio / Ops sections; the old "Radio" page is now called Hardware. The new grouping makes it clearer which pages relate to network protocols versus physical radio hardware versus operational tools.
- **Inline modals instead of browser popups** for confirmations throughout the app. This replaces plain browser confirm dialogs with modals styled to match the rest of the dashboard.
- **Dates now shown on packet feeds** for packets from previous days. Today's packets still keep the shorter time-only display.
- **Home button on the node map**, to quickly recenter on your own location. It sits next to the existing expand button and doesn't disturb the map's own remembered zoom and pan position.
- **Theme toggle in the topbar**, cycling between the three dark themes. It stays in sync with the same theme option already available from the command palette.
- **Incoming-message notifications.** A toast (with an optional sound) pops up when a message arrives, with separate on/off switches per browser.
- **24-hour clock everywhere.** Packet feeds, panels, the node drawer, charts, and messaging all switched from 12-hour AM/PM display to a 24-hour format.
- **24-hour clock, three more stragglers** — the packet detail popup and MQTT config timestamps were missed on the first pass; also fixed a repeater date that was locked to US formatting. These three spots had quietly slipped through the original sweep.
- **Metric units by default** for new browsers (Celsius, kilometers); existing imperial choices are kept. This only affects browsers that haven't already chosen a unit preference.
- **Meshtastic and MeshCore sidebar icons are now their real marks**, not generic placeholders — Meshtastic's official "M-Powered" badge (greyed out until you're on the Meshtastic page, then shows full color) and MeshCore's own "M" glyph. Topology picked up MeshCore's old icon, freed up by the swap.
- **DAPNET moved up in the sidebar**, right under MeshCore instead of after Topology — groups the four protocol pages (LoRaWAN, Meshtastic, MeshCore, DAPNET) together ahead of the cross-protocol views (Messages, Stats, Topology). Still only shows once a POCSAG companion is configured, unchanged.
- **Hardware sidebar icon changed to a proper router glyph** (svgrepo.com), replacing the generic wifi-wave icon it used to share with Meshtastic (which now has its own real badge, see above).
- **RTL-SDR sidebar icon changed to a USB dongle glyph**, replacing an abstract antenna icon — RTL-SDR is literally a USB stick, so this reads clearer.
- **Repeaters sidebar icon changed to a base-station/tower glyph**, replacing the old broadcast-arcs icon.
- **Configuration → System subgroup dissolved.** Metrics moved under Configuration → Network (next to MQTT/Repeater Poll, since it's a network-exposed endpoint too); Advanced moved under Settings as an interim home. Removes the confusing "System" showing up as both a Configuration subgroup and a separate Settings page.
- **"Radio (advanced)" (spectral scan interval, SX1261 SPI path) split out of Settings → Advanced and moved onto Configuration → Radio**, between the main Radio card and NodeInfo — it's a radio-hardware setting, not a host-management one, so it belongs with the rest of the radio config. Settings → Advanced now holds only Storage retention.
- **Configuration → Radio card order fixed**: NodeInfo and Telemetry Broadcast edit forms now sit together, followed by both their status cards — previously edit/status pairs were interleaved per-feature instead of grouped by input-then-output.
- **Settings → Advanced renamed to Settings → Storage**, matching what it actually holds now that Radio (advanced) moved out. In-app hints pointing at the old spectral-scan location were also fixed to say Configuration → Radio instead. The rename is complete end to end — URL route (`settings/storage`) and permission key (`settings.storage`, its own key rather than the generic Settings bucket, same pattern as `settings/dangerous`) now match the sidebar position, not just the visible label.
- **Fixed malformed SVG path data on the Meshtastic sidebar badge, the Repeaters icon, and the Settings gear icon** — a missing separator between adjacent decimal numbers (e.g. `.57.81` instead of `.57,.81`) that some browsers logged as a console error while rendering.
- **Fixed: Settings → Storage never actually loaded**, staying stuck on "Loading…" forever. A leftover route-prefix check in `app.js` (added before Storage moved under Settings) silently blocked the page's mount call before it ever ran.


#### Import and maintenance scripts

- **Contacts + neighbours import.** Imports MeshCore contacts and neighbour data from an existing companion export.
- **Repair and backfill tools** for fixing bad timestamps and old rows missing frequency/SF data. These are one-off scripts meant to be run manually against a database that has old or incomplete data.
- **`scripts/edit_contact.py`.** Interactive tool to correct a node's stored name or location.
- **`scripts/dab_channel_scan.py`.** Standalone tool that scans all DAB+ channels to find which ones carry real content at your location, used to build the dashboard's DAB+ channel presets. Went through several rounds of refinement: merging results across multiple scan runs instead of overwriting, cleaner ensemble labels, and a more reliable retest for channels that came back empty.

#### SenseCap M1 hardware

- **SenseCap M1 onboard LED/button/fan GPIO probe tool**, used to identify which pins drive the board's onboard peripherals (no public schematic exists for them). It was used to confirm exactly which GPIO pin drives each of the LED, button, and fan on this specific board.
- **Configuration → Peripherals page**, for editing the fan/LED/button settings from the dashboard instead of hand-editing config files. Each peripheral gets its own form, including its specific tuning options like the fan's temperature curve.
- **Temperature-driven fan control.** The onboard fan now ramps speed with CPU temperature instead of running flat-out or not at all; off by default since not every board has this fan.
- **User button support.** Short press sends an advert on every connected radio; holding it for 3 seconds restarts the service — useful when the dashboard itself is unreachable.
- **Status LED support.** Steady on = healthy, blinking = a capture source is down, off = service not running, with a brief flicker per captured packet.

#### MeshCore repeaters

- **Fixed: the Sensors card could blank out after a restart** even though the last real reading was still valid. A poll that succeeded but returned no telemetry yet (the companion still settling after a restart) was overwriting the previously stored readings instead of keeping them.
- **MeshCore repeater monitoring.** Periodically polls repeaters you operate for battery, uptime, airtime, packet counts, and sensor telemetry, shown on a new Repeaters page with health, sensor, history, and trend cards. Off by default since it's active two-way radio traffic.
- **Repeater neighbours list is now clickable**, opening a popup with each neighbour's signal and resolved name where known. Clicking a neighbour with a known name opens its regular node details, the same as anywhere else in the dashboard.
- **Removed a redundant "polled Xm ago" footer** from the repeater card. The same information was already shown once at the top of the Repeaters page, so the per-card copy was pure duplication.
- **Live repeater neighbour polls now feed the main node list**, and each repeater card shows its own farthest-neighbour reading. Previously this data only ever showed on the Repeaters page itself and never reached the node roster.
- **Repeater polling gets its own Configuration page**, instead of requiring hand-edited config files (including passwords). Passwords are handled the same way as other secrets in the dashboard — the page only ever shows whether one is set, never the value itself.
- **MeshCore packet feed no longer buried under old bulk-imported telemetry history.** A historical import could write dozens of near-identical telemetry rows per timestamp, which drowned out genuinely recent activity in the feed.
- **Fixed: repeater login could get permanently stuck after a mesh topology change**, even after a full reboot. Took a few rounds to track down and fully resolve, with added diagnostic logging along the way.

#### Self-update system

- **Fixed: dashboard "Check for updates" failed with a permissions error** after a prior fix changed how git commands were run. A new safety flag added to every git command no longer matched the exact rule the system had been granted permission to run without a password.
- **Fixed a related git ownership issue on upgraded boxes.** Boxes that had been upgraded rather than freshly installed were missing a setting that fresh installs already had.
- **Release channel picker trimmed to this fork's actual branches.** Branches that only exist upstream and never existed on this fork have been removed from the picker.
- **Update source now points at this fork** instead of upstream. This is what made update checks fail to find this fork's own releases in the first place.
- **"Check for updates" now shows what's coming** — the incoming commit messages, so you can see what an update would bring before applying it. Up to ten recent commit messages are listed, with a count of anything beyond that.
- **Updates page now lists the last five commits** on the current branch. This replaces an earlier list that only showed past dashboard button presses rather than what had actually changed upstream.
- **Automatic background update checks, plus a sidebar pill** when an update is available — no need to remember to check manually. The pill sits right under the device name at the very top of the sidebar, and clicking it jumps straight to the Updates page.
- **Release notes are now grouped by category** in the "What's new" preview. Previously every bullet ran together in one flat list with no section headings.
- **"Read full release notes" link**, opening the complete changelog for the installed version. The preview only shows a short teaser of each bullet; this link opens the full text in a modal without leaving the page.
- **Fixed: update checks failed on developer checkouts** with a confusing sudo password prompt. A checkout owned by the current user now runs plain git commands instead of always trying to use sudo.
- **Fixed: applying an update could leave your browser running old cached code** until a hard refresh. Assets now refresh automatically after every update.
- **Fixed a file-ownership issue that could break "Check for updates"** after certain other fixes ran. The dashboard's own files could end up owned by the wrong system user, which then blocked the git commands used to check for updates.
- **Self-update now points at whatever fork you actually cloned**, not a hardcoded repo — so forks update themselves correctly with zero configuration. It reads the repository straight from the local git configuration, falling back to the main project if that can't be determined.

#### Backup and restore

- **Settings → System backup and restore.** Download a full backup, or restore from one — useful for recovering after a mistake or moving to new hardware. Not encrypted, so keep the file private.
- **Disaster recovery docs**, covering fresh-install recovery, off-box backup storage, and SSH-based recovery fallbacks. They cover recovering onto a completely fresh install, storing backups somewhere other than the box itself, and a manual SSH-based fallback if the dashboard itself is unreachable.

#### Mesh broadcast cadence

- **Position and telemetry broadcast interval controls**, editable from Configuration → Radio and Configuration → GPS, with live countdowns and no restart needed. Each interval can be set independently, or set to zero to pause that broadcast entirely.

#### Dashboard and operator tools

- **RF Environment tab.** Spectral scan and noise-floor telemetry, supported on this fork's hardware.
- **Fixed: the RF tab's histogram chart could grow the page without bound.** The chart's container had no fixed height, so real scan data could make it grow taller and taller instead of staying contained.
- **Chart.js is now bundled locally** instead of loaded from the internet, so charts still work on offline/air-gapped boxes. Previously a box with no outbound internet access silently lost these charts entirely.
- **Thermals card on the Hardware page**, showing 6 hours of CPU temperature and fan speed history. It only appears when fan control is actually enabled, matching the existing Fan stat tile's own visibility rule.
- **Operator status strips** on Dashboard, RF, and MQTT configuration pages. These give an at-a-glance summary of key numbers without needing to dig into a full page of detail.
- **Quick Deploy QR code**, for exporting channel settings as a scannable code. This makes it easy to hand channel settings to a field device without typing them in by hand.
- **Prometheus `/metrics` endpoint**, with packet, node, relay, and system counters. It can be turned on and secured from the Configuration → Metrics page rather than needing a config file edit.
- **Fixed: Meshtastic channel hashes could drift out of sync after saving channel changes.** This could leave MQTT topics and packet decoders looking at the wrong channel after an edit.
- **Terminal quick-command for running the full installer**, added and then later removed after it was found to sometimes kill its own terminal session — running the installer from a real SSH session still works fine. The installer's own final step restarts the dashboard service, which also happens to be what runs the web Terminal, so triggering it from there cut off the very session running it.
- **Terminal quick-commands: 3 new DAB+ scan shortcuts**, for common scan scenarios. They cover a full scan, a full scan with a longer timeout for weak signal areas, and a fast targeted rescan of just the channels already confirmed to work at this location.

#### Docs

- **Home Assistant cookbook**, for MQTT discovery and sensor wiring. It walks through setting up MQTT discovery so Meshpoint's sensors show up automatically in Home Assistant.
- **Complete API endpoint reference.** A full route audit found the README's table only covered about half of the app's real routes; a new dedicated doc lists every route and what access level it needs.

### v0.7.8 (July 2026)

Our own `src/version.py` jumped straight from 0.7.7 to 0.7.9 and never cut a v0.7.8 tag, so this section didn't exist until now. It's added retroactively to keep the written history accurate: KMX415's fork ([`docs/CHANGELOG.md`](https://github.com/KMX415/meshpoint/blob/main/docs/CHANGELOG.md)) bundled this same functional scope under its own "v0.7.8 (July 2026)" release, and the section below is organized to match his grouping for easy cross-reference. Full audit trail in `memory/merge-todo.md`. This section is not shown by the dashboard's live release-notes preview, which matches the installed version exactly.

#### MQTT and community map

- **Opt-in publishing to the official Meshtastic map.** A new "Official map" toggle in Configuration → MQTT publishes this Meshpoint's own identity (name, approximate location, firmware, region, modem preset) as a public, unencrypted MQTT MapReport — separate from the existing packet-relay gateway, MQTT-only, no LoRa airtime used. Off by default; requires MQTT itself to be enabled. Interval (minimum 3600s, matching the Meshtastic minimum) and position precision (12–15 bits, default 14) are both configurable.

#### Settings and Updates

- **Release-notes preview grouped by CHANGELOG category.** The Updates page's release-notes preview groups bullets under their CHANGELOG "#### Category" headings instead of one flat list, so operators can scan a sprint by area before applying.
- **Full release-notes modal on the Updates page.** A "Read full release notes" link opens the complete, untruncated CHANGELOG section for the selected channel, instead of just the trimmed preview.
- **Unified Updates-page commit timeline.** The two separate "incoming commits" and "latest commits" lists on Settings → Updates are now one timeline: a connector rail marks each commit, unseen ones get a glowing "NEW" pill, and the header badge reads "N commits waiting" or "Up to date" at a glance. The Apply button now pulses gently whenever there's something ready to apply.

#### Dashboard and storage

- **Dashboard JS/CSS cache-busting after restart.** Static asset URLs now carry a per-restart cache-busting token, so applying an update no longer leaves open browser tabs on stale cached JS/CSS until a hard reload.
- **Telemetry history is now auto-pruned**, closing the one database table that could grow without bound. A real deployment was found to grow its database by over 20 MB in just three days before this was fixed.
- **Server-side telemetry chart downsampling.** Repeater Trends and node-drawer telemetry charts downsample into time buckets, bounded regardless of how much history exists — the newest buckets win once history exceeds the chart's limit.

#### Auth and viewers

- **Viewer role fully locked down server-side.** Every settings-changing action now requires admin; viewers get a clean "not allowed" message instead of it silently going through (or, previously, sometimes being silently accepted with no real effect).
- **Channel secrets hidden from viewers.** Encryption keys are no longer sent to viewer sessions.
- **Admin links stay in place for viewers.** Clicking an admin-only link no longer navigates away; a message explains admin access is needed.
- **Blocked message sends now show a toast** instead of leaving a failed message in the chat. A viewer trying to send now sees a clear notice that admin access is required, rather than a message that silently fails to appear.
- **Upstream's new broadcast-interval settings are now properly admin-gated.** These settings had no role check at all when they were first merged in, so a viewer could technically change them.

#### Serial Meshtastic and messaging

- **Multiple Meshtastic USB sticks** can now be configured at once too (e.g. one on 433 MHz, one on 868 MHz), also editable from Configuration. Also fixes a bug where packets from different sticks could get mixed up.
- **Fixed: a serial Meshtastic USB stick would crash the whole capture pipeline**, and was silently dropping packets it couldn't decrypt. The stick's library always hands back a raw packet object rather than plain bytes, and packets it couldn't decrypt itself were being discarded instead of being handed to Meshpoint's own decoder.
- **Fixed: serial Meshtastic packets the stick decrypted itself always showed as "Unknown" type.** They now decode and show their real content.
- **Band tag on node cards.** Nodes now show a "433 MHz" / "868 MHz" chip so a multi-stick setup is easy to read at a glance.
- **Serial Meshtastic sticks now report their real region/frequency/settings.** Previously every packet was stamped with a fake placeholder frequency and settings regardless of the stick's actual configuration. Also added a topbar badge showing each connected stick's status.
- **Serial Meshtastic sticks no longer capture their own self-reports as noisy, confusing packets.** A cleanup script is available for old rows already affected.
- **Chat replies now go out over whichever radio can actually reach the contact**, instead of always the "primary" one — fixes replies silently failing to arrive on a multi-radio box. A contact heard only on one companion's frequency physically can't receive a reply sent out on a different one.
- **Fixed: a 433 MHz Meshtastic USB stick could misroute channels**, both receiving and sending, due to confusing its own internal channel numbering with the real on-air channel identity. This meant a reply could go out on the wrong channel, or an incoming message could get filed under the wrong conversation entirely.
- **Meshpoint can now reply correctly on a channel whose key it has under a different local name**, instead of refusing to send. Live-verified.
- **Fixed: messages on a channel this box doesn't recognize used to silently blend into the main channel's history**, and briefly became invisible entirely partway through the fix. They now show up in their own "Unmapped" section, and replying to them was disabled until it could be done safely.
- **Clicking a node name in Messages now opens its node details**, for both direct messages and channel/broadcast messages. Direct-message sender names already worked this way; channel and broadcast messages needed a small backend fix first, since the server was resolving a sender's display name without keeping track of their actual node ID.
- **Fixed a real data-integrity bug where MeshCore node names could cross-contaminate between different physical nodes.** A one-time cleanup script fixes already-affected data; new devices are unaffected going forward.

### v0.7.6 (June 2026)

Meshtastic mesh participant release on `main` (merge `feat/v0.7.6`). Edge-only, pure Python, no concentrator recompile. **Upgrade:** Settings → Updates → **Stable**, or the full SSH block in `docs/COMMON-ERRORS.md` (`git fetch`, `checkout main`, `pull`, `scripts/install.sh`, `restart`). Required this release: new `cryptography` dependency for PKI and an updated `meshpoint.service` unit (RAK V2 reset fix). Pull-only upgrades can miss both. Witness-tested on RAK V2. Settings → Updates RC picker now points at **v0.7.7** on `feat/v0.7.7`.

#### Meshtastic mesh participant

- **PKI (2.5+ clients).** X25519 keypair in `data/keys.yaml`, `public_key` in NodeInfo, AES-CCM encrypt/decrypt for DMs when peers advertise keys. Meshtastic apps show a closed lock instead of Shared Key-only mode.
- **DM routing ACKs.** Inbound `want_ack` TEXT to our node_id triggers a routing ACK on the same channel.
- **Periodic telemetry and position TX.** `device_metrics` and POSITION broadcasts when configured; position source and privacy are separate from the Meshradar registration pin (see GPS below).
- **Traceroute replies.** Answer unicast traceroute requests with preserved inbound route/SNR, populated `route_back`/`snr_back`, and `request_id` so the app does not show `? dB` on direct hops.
- **Telemetry request response.** Answer unicast `TELEMETRY` probes (Signal quality / `local_stats`) with matching variant, `request_id`, `Telemetry.time`, and `LocalStats.noise_floor`.
- **PKI + channel reply encryption.** Unicast replies (routing ACK, traceroute, telemetry) use PKI only when the inbound packet has `channel_hash == 0`. Channel-based requests stay on channel AES even when the peer pubkey is known.
- **Relay vs inbound replies.** Skip relay for unicast packets addressed to our node; run inbound auto-responders before relay evaluation so replies are not delayed behind relay airtime on the SX1302.

#### Dashboard and updates

- **Public channel sender names.** Channel TEXT from other nodes shows the resolved node name in Messages and the packet feed, not the literal "Broadcast" label ([#38](https://github.com/KMX415/meshpoint/pull/38) sender-name regression).
- **Map Direct/Relayed filters.** Node map markers stay in sync with the Direct and Relayed filter pills.
- **Apply finish reliability.** Dashboard Apply uses a detached `apply_finish.sh` so `pip install` and `post_update.sh` complete before restart; fixes crash loops when new dependencies land on RC branches.
- **Messages startup fix.** Resolves `MessageNameResolver` crash on boot when the message store initializes before the node roster is ready.
- **MeshCore offline copy.** When Native TX is disabled, Configuration and Radio explain that USB capture can still work while the companion card shows `transmit_disabled` instead of a generic disconnect.

#### Configuration, GPS, and config hygiene

- **Location split: Meshradar pin vs mesh POSITION.** Registered coordinates in `device.latitude/longitude` are always sent to Meshradar upstream and are not overwritten by live gpsd fixes. Meshtastic POSITION on the LoRa mesh is configured under **Configuration → GPS → Mesh position broadcasts** (registered pin vs live GPS, with approximate/precise/hidden privacy). MQTT `location_precision` remains independent.
- **Message display names.** Outbound and inbound chat bubbles resolve sender names from the live node roster instead of stale or cross-protocol fallbacks.
- **Unknown `local.yaml` keys.** Config loader logs a single `WARNING` listing keys it could not apply (typos, mistyped sections) instead of failing silently ([#63](https://github.com/KMX415/meshpoint/pull/63)).

#### Hardware and experimental tracks

- **RAK Hotspot V2 reset robustness.** Systemd `ExecStartPre`/`ExecStopPost` concentrator reset uses `+` prefix so root-owned reset runs reliably on sensitive RAK7248 carriers ([#62](https://github.com/KMX415/meshpoint/pull/62)).
- **WisMesh Node experimental channel.** Settings → Updates adds an optional **WisMesh Node (RAK6421 HAT)** track on `feat/wismesh-hat` (not for standard SX1302 gateways). See `docs/WISMESH-NODE.md`.

### v0.7.5.1 (May 2026)

Patch release on `main`. Edge-only. **Upgrade:** Settings → Updates → **Stable**, or `git pull` on `main` plus `systemctl restart meshpoint`. No concentrator or HAL changes.

#### Dashboard apply

- **Lightweight apply finish.** Settings → Updates runs `git fetch` / checkout / reset, then a detached `scripts/apply_finish.sh` that stops the service, runs `pip install -r requirements.txt`, `post_update.sh`, and restarts. Avoids crash loops when the next release adds new Python dependencies before the service boots the new code.
- **Live update progress.** Apply and rollback streams show command output in a terminal panel; step labels match the backend (`upgrade` instead of stale `install.sh` / `restart service` keys).
- **SSH upgrade path.** `install.sh` on upgrade (`IS_UPGRADE=1`) refreshes the venv before apt/HAL work so manual upgrades get the same pip-first safety net.

### v0.7.5 (May 2026)

Companion polish, live GPS, and local dashboard UX. Edge-only, pure Python, no concentrator recompile. **Upgrade:** `git pull` on `main` (or Settings → Updates → **Stable**) plus `scripts/install.sh` when crossing from older releases so gpsd packages and sudoers stay in sync. Settings → Updates RC picker now points at **v0.7.6** on `feat/v0.7.6`.

#### GPS and location

- **Live GPS via `gpsd`.** Pluggable `location.source` (`static` | `gpsd` | `uart`). Configuration → GPS ships a skyplot (az/el/SNR, constellations, fix lamp, DOP, last fix). `install.sh` installs gpsd + USB hotplug config idempotently. Live fixes update device coordinates and the local map marker. UART path remains a placeholder for RAK onboard GPS.
- **MeshCore USB skips u-blox GPS.** `UsbPortClassifier` excludes VID `0x1546` from MeshCore serial probing so a GPS stick and Heltec companion can coexist.

#### MeshCore

- **Companion set-name from the dashboard.** `PUT /api/config/meshcore/companion-name`, editable name on Configuration → MeshCore, optional re-apply from `local.yaml` after USB reconnect.
- **Channel keys (extends v0.7.4 editors).** Slot 0 = Public (locked); user channels on slots 1–7; **hashtag** channels with empty key map to the 16-byte zero secret; Messages send/RX use the same slot index as Configuration.
- **Zero-key length fix.** Empty hashtag saves previously wrote 64 hex digits and blocked later **Save Channels**; legacy yaml normalizes on read/save.

#### Configuration and MQTT

- **Custom preset on Configuration → Radio.** Restore **Custom** chip with SF/BW/CR inputs when modem params do not match a named preset.
- **MQTT Home Assistant state topics.** Retained publishes on `meshpoint/{node_id}/telemetry` and `meshpoint/{node_id}/position` when HA discovery is enabled.

#### Dashboard map and nodes

- **Map:** remember zoom/view across reload; node popup **Last heard** line; MeshCore nodes render as **diamond** markers (Meshtastic stays circles).
- **Node grid:** sort (last heard / signal / hops / name) and filter (all / direct / relayed), persisted in localStorage.
- **Favorite nodes:** star on cards and drawer, amber map border, **Favorites only** filter.

#### System metrics and fixes

- **Load average on the system stats row.** `GET /api/device/metrics` returns `[1m, 5m, 15m]` from `/proc/loadavg`; new **Load Avg** dashboard card. [PR #61](https://github.com/KMX415/meshpoint/pull/61) merged to `main` after v0.7.4; ships in this release (no separate patch version).
- **Stats CPU temperature** honors Settings → Meshpoint °F/°C preference.
- **Terminal:** quick-command insert no longer steals focus from the shell.

### v0.7.4 (May 20, 2026)

Major dashboard release on `main` (merge `56d4f7c`). Builds on v0.7.3 auth: every page and API call stays behind the login cookie. Edge-only, pure Python, no concentrator recompile. **Upgrade:** use the idempotent block in `README.md` and `docs/COMMON-ERRORS.md` (`git fetch`, `checkout main`, `pull`, `scripts/install.sh`, `systemctl restart`) so jumps from v0.6.x or v0.7.2 pick up venv deps, stale `.so` cleanup, and sudoers. No new Python packages beyond v0.7.3 (`bcrypt`, `PyJWT`). After upgrade on `main`, Settings → Updates defaults the channel picker to **Release candidate (v0.7.5)** for early testers.

#### Dashboard shell and navigation

- **New sidebar IA.** Persistent nav for Dashboard, Messages, Stats, Radio (read-only RF telemetry), Terminal, Configuration (Identity / Radio / Channels / MeshCore / Transmit / MQTT / GPS), and Settings (Updates / Auth / Meshpoint). FLIP accent bar, `g`+letter shortcuts, tablet click-outside-to-collapse, and a larger framed Meshpoint logo with a websocket status pip.
- **Top bar chrome.** Connection lamp, device identity, live radio summary chip, build stamp, and sign-out control stay visible on every route.
- **Polish layer (Sprints A–D).** Sidebar noise-floor sparkline and reconnect storyboard; live browser-tab title; per-page init checklist and route fade-ins; Ctrl+K command palette and `?` keymap overlay; optional sound engine; high-contrast and sunlight themes; terminal ASCII splash and "since you last looked" delta line.
- **Responsive fixes.** Stats section scrolls on tablet; map keeps zero page-level horizontal scroll; KPI strip scrolls inside its card; packets feed height is bounded so live traffic no longer buries the map; phone landscape keeps map + node panel visible; mobile drawer scrolls end-to-end with `100dvh` and safe-area padding so Sign Out clears the iOS Safari toolbar.
- **Sidebar badges.** Radio shows a live NodeInfo TX countdown; Messages counts **unread DMs only** (not channel chatter), seeds from the server, and clears when you open a conversation.
- **Node list online dot.** Green/grey indicator now uses a **2-hour** "recently heard" window (Meshtastic-style) instead of 15 minutes, so nodes at "18m ago" are not mislabeled offline while the timestamp still looks fresh. UTC-safe parsing for SQLite timestamps without a `Z` suffix.

#### Auth (extends v0.7.3)

- **Settings > Auth.** Change admin password (rotates JWT secret and forces re-login), sign out everywhere (bumps session version), enable/configure viewer read-only login, tune failed-login lockout attempts and cooldown, and adjust session lifetime from the dashboard.
- **Audit trail.** Admin actions append JSON lines to `data/admin_audit.jsonl` (config saves, auth changes, dangerous invokes, terminal commands, update apply). Sensitive fields are redacted.

#### Configuration and MQTT

- **Configuration editors.** Identity (names + pinned node ID), Radio (region, preset, MHz/slot via Meshtastic firmware formula, hop limit), Channels (PSK table with per-channel delete ([#38](https://github.com/KMX415/meshpoint/pull/38))), MeshCore (USB source, channel keys, Send Advert, Refresh contacts), Transmit (TX power, duty, native TX enable, relay limits), MQTT (broker, topic root, region segment, encryption, publish allowlist, JSON mirror, HA discovery, location precision), **Advanced** (upstream Meshradar URL/key/reconnect, device placement, storage paths, radio-advanced, MeshCore USB tuning), and GPS (placement UI; `PUT /api/config/gps` still deferred). Top-level **Radio** tab is observational only; all edits live under Configuration.
- **MQTT API wired.** `PUT /api/config/mqtt` and enriched `GET /api/config` map dashboard fields to `local.yaml`. Service restart required for the publisher to reconnect.
- **Hierarchical MQTT topic paths** ([#35](https://github.com/KMX415/meshpoint/pull/35)): `topic_root` and `region` segment combine per the Meshtastic spec (`<topic_root>/<region>/2/e/<channel>/<gateway>`) with live preview in Configuration → MQTT. Avoids the double-region footgun (`msh/US/FL/US/...`).
- **Preset save hot-reload.** Saving a modem preset updates in-memory config immediately; observational Radio tab and top-bar preset readout refresh on the next poll without a hard browser refresh.

#### Web terminal, updates, and Meshpoint actions

- **Web terminal.** Browser-based shell (xterm.js) with Connect/Disconnect, command guide drawer (`?`), search overlay, and admin-only access. Commands are audited; dangerous invocations use a confirm modal (typed confirmation removed in favor of a simpler Confirm/Cancel flow).
- **In-dashboard updates.** Settings > Updates lists installed version, git branch, and last check; **Check for updates** reports commits behind the selected channel; **Apply** runs fetch/checkout/install/restart with streamed progress. Release channel picker: **Stable (main)**, **Release candidate (v0.7.5)** (`feat/v0.7.5`), and custom branch. Gateways on `main` at v0.7.4+ default to the v0.7.5 RC in the picker. Rollback restores a prior SHA after apply (watchdog auto-rollback is follow-up work).
- **Settings > Meshpoint** (formerly "Dangerous"). Confirm modal before restart service, clear local database, wipe phantom nodes, force NodeInfo broadcast, or in-process concentrator restart. Service restart uses a detached `systemctl` handoff so the API no longer reports failure while the process is exiting. `GET`/`PUT` transmit config correctly round-trips nested **relay** settings.

#### MeshCore

- **MeshCore channel configuration** ([#53](https://github.com/KMX415/meshpoint/pull/53)): dashboard editors for companion channel keys, synced from the USB path.
- **Faster peer discovery** via `NEW_CONTACT` events ([#55](https://github.com/KMX415/meshpoint/pull/55)).
- **Friendly repeater names** instead of pubkey placeholders ([#54](https://github.com/KMX415/meshpoint/pull/54)): wider advert name aliases, placeholder cleanup migration, and throttled contact-list enrichment from the USB companion.
- **MeshCore nodes on the local map** ([#51](https://github.com/KMX415/meshpoint/pull/51)): advertisement and position packets write lat/lon into the node table so MeshCore contacts appear on the dashboard map with RSSI/SNR on adverts, not only DMs.
- **Contact roster at startup.** Deferred ~20s retry after USB connect logs the full peer list and syncs friendly names into SQLite when the first fetch returns zero rows.
- **`get_contacts()` robustness.** Tolerates mixed-type companion payloads without crashing the sync path.

#### Relay and RF telemetry

- **Native onboard relay (experimental).** Meshtastic packets can be re-broadcast through the onboard SX1302 with identity preserved (`hop_limit` decrements, sender and ciphertext unchanged). Decoder now retains `raw_app_payload` so the relay path is not silently empty. See [docs/CONFIGURATION.md#smart-relay](docs/CONFIGURATION.md#smart-relay).
- **Noise floor.** Sidebar telemetry uses a rolling minimum of `rssi - snr` (fixes endless "calibrating" on rural single-neighbour links). Optional SX1302 spectral scan when `radio.sx1261_spi_path` is set (off by default on RAK/SenseCap: SX1261 is not on a Pi-visible SPI bus). UI tooltips describe whether the readout is packet-derived or spectral-scan sourced.

#### Sign-off polish and UX

- **Top bar protocol chips.** Meshtastic and MeshCore grouped chips with connection dots (no separate ONLINE/OFFLINE text). MeshCore shows companion name, frequency, and primary channel when configured.
- **Node drawer metrics charts.** `GET /api/nodes/{id}/metrics_history` for battery, voltage, channel/air util, temperature, and RSSI over 1H / 6H / 24H / All.
- **Display unit preferences.** Settings > Meshpoint: browser-local °F/°C and miles-feet vs km-m for node cards, drawer, and packet feed.
- **Node card temperature.** Telemetry stored in Celsius from Meshtastic; dashboard converts for display instead of mislabeling Celsius values as °F.
- **Messages empty-state copy.** Plain instructions (pick a conversation, use All/MT/MC filters) instead of internal jargon.
- **Sidebar scroll and accent bar.** Nav column scrolls when Configuration submenus expand; green route indicator tracks the active nav item, not the bottom of the sidebar column.
- **GPS configuration page crash.** Fixed template-literal typo in the GPS card that broke the page on load.
- **Top bar MeshCore offline state.** Companion chip shows amber when the API or WebSocket path is down, not only when USB is unplugged.
- **Terminal copy shortcut.** Ctrl+Shift+C uses `preventDefault` in the terminal pane so browser copy works reliably.
- **Updates rollback persistence.** Pre-update SHA captured with `sudo git` on the Pi and stored under `data/update_rollback.json`; rollback button stays usable after Apply + reload.
- **Check for updates commit counts.** `git rev-list` allowed in `config/sudoers-meshpoint` with `git log --oneline` fallback when `rev-list` is denied.
- **`data/` ownership on service start.** systemd `ExecStartPre` chowns `data/` for the `meshpoint` service user so rollback and audit files remain writable after upgrade.

#### Not in this release

- MQTT broker TLS (`mqtts`), gpsd save API, watchdog auto-rollback on failed Apply, MeshCore companion rename from the dashboard (planned for v0.7.5).

#### Internal

- New routes for auth config, terminal PTY, update apply, MQTT/upstream/device config, meshcore contact enrichment, spectral scan, and admin audit. Release channel registry advances RC to `feat/v0.7.5` on `main` at v0.7.4+. Test suite **700+** passing. Optional LAN smoke: `scripts/smoke_v074_api.py` when `MESHPOINT_PASSWORD` is set.

### v0.7.3.1 (May 13, 2026)

Hotfix on top of v0.7.3 the same day. Reported by Willard on Discord ~3h after release: dashboard stuck on "Reconnecting..." with no data after upgrading. Two compounding bugs in the new auth path; a stale browser tab against an auth-required server is enough to trigger both.

- **WS auth close frame now actually reaches the browser.** `src/api/server.py` was calling `await websocket.close(code=4401)` *before* `await websocket.accept()`, which causes Starlette to fail the WebSocket handshake with HTTP 403 instead of completing the handshake and sending a close frame. Browsers translate that to close code `1006` (Abnormal Closure) on the JS side, and our `frontend/js/websocket_client.js` only special-cases `4401` for the redirect-to-/login path -- so unauthenticated WS connections fell through to the generic reconnect loop and stuck forever. Fix: `accept()` first, then `close(code=WS_AUTH_CLOSE_CODE)`. Validated end-to-end on .141 (cookie cleared, dashboard refreshed → bounces to /login as intended).
- **Dashboard root (`/`) now redirects unauthenticated requests to `/login`.** The `StaticFiles(directory=..., html=True)` mount on `/` was serving `index.html` to everyone with no auth check, so a stale browser tab could load the new SPA JS and immediately fight the now-auth-required `/ws`. New explicit `@app.get("/")` route registered ahead of the static mount: 302s unauthenticated requests to `/login` (or `/setup` if no admin password is set yet), serves `index.html` for valid sessions. Static asset paths (`/css`, `/js`, `/assets`, etc.) still fall through to the existing mount.
- **Client defense in depth.** `frontend/js/websocket_client.js` now tracks whether the socket reached the `open` state. If `onclose` fires *without* a prior `onopen`, the handshake failed before the close frame could be delivered. The client probes an auth-gated endpoint (`/api/device/status`); the global 401 interceptor in `app.js` then handles the redirect if it's an auth-shaped failure, while real network blips fall through to the existing reconnect schedule. Belt-and-suspenders coverage so a future server-side regression in the close-code path can't strand users again.
- **Internal:** new `tests/test_dashboard_root_route.py` (unauthenticated GET `/` → 302 to `/login`; GET `/` with no admin password yet → 302 to `/setup`; GET `/` with valid cookie → 200 + index.html). New `tests/test_websocket_auth_close_code.py` asserts the WS handshake completes and the close frame's code is exactly `4401` for both no-cookie and bad-cookie cases (regression for the `accept()`-before-`close()` requirement). 403 tests passing, ruff clean.

### v0.7.3 (May 13, 2026)

Local-dashboard authentication, dashboard branding polish, and the second-leg phantom-node leak fix. Auth lands as a hard requirement on every Meshpoint: existing devices upgrading from v0.7.2 will be prompted to set an admin password the first time the dashboard is opened after the upgrade. Pure-Python where it counts; `install.sh` re-run picks up two new dependencies (`bcrypt`, `PyJWT`).

- **Local dashboard authentication.** First-visit redirects to `/setup`, where you set an admin password (bcrypt-hashed, never stored in plaintext, never logged). Subsequent visits land on `/login`. Sessions are stateless JWTs in an HttpOnly + SameSite=Lax cookie; the JWT secret is auto-generated on the device and persisted to `local.yaml` only when `/setup` completes (a fresh-SD install with no admin password yet leaves `local.yaml` untouched, so the existing setup wizard's "Existing config found" detection still works). All `/api/*` routes, the dashboard pages, and the `/ws` WebSocket are now behind `Depends(require_auth)`; unauthenticated calls return 401 (HTTP) or close code 4401 (WebSocket) and the dashboard JS auto-redirects to `/login?next=...`. Failed-login lockout (`web_auth.lockout_attempts`, default 5; `web_auth.lockout_cooldown_minutes`, default 5) is per-username, in-memory, and surfaces a live countdown on the login page via the `Retry-After` header. Optional viewer role for read-only access via `web_auth.viewer_password_hash` + `web_auth.allow_read_only: true`.
- **`meshpoint reset-password` recovery.** New CLI command for the "I forgot the dashboard password" path. Hashes the new password, rotates `web_auth.jwt_secret`, bumps `web_auth.session_version`, and writes everything to `local.yaml` in one operation: every existing browser session is invalidated and the new credentials work immediately. Run via SSH (`sudo /opt/meshpoint/venv/bin/python -m src.cli.main reset-password <new-password>`); requires no service restart.
- **Sign-out in the topbar.** Door-out icon at the far right of the dashboard header. Clicking it POSTs `/api/auth/logout`, the cookie is cleared, and the browser redirects to `/login`. Hover tints accent-cyan; safe under network failure (still redirects, the global 401 interceptor catches any lingering authenticated call).
- **Auth pages get the radar treatment.** `/setup` and `/login` ship a slowly rotating cyan sweep over a deep-navy radar disc with a live identity strip (device name, firmware version, online dot) so you can confirm you're talking to the right Meshpoint before entering credentials. Same `--bg-primary` / Inter / JetBrains Mono palette as the dashboard, single `auth-` BEM prefix, full reduced-motion support. The radar's blip layer is intentionally unwired in v0.7.3: blips are reserved for real concentrator RX events once a deliberately-public scrubbed feed lands in v0.7.4, rather than ship cosmetic randomness today.
- **Dashboard branding.** Topbar now carries the actual Meshpoint logo (40px, rounded-tile gradient mark) where the placeholder trigram glyph was, plus a 256x256 favicon used on `/`, `/setup`, and `/login`. iOS home-screen icon (`apple-touch-icon`) keeps the rounded-tile mark for nicer bookmark rendering. Establishes `frontend/assets/` as the canonical asset folder.
- **Phantom-node leak: drop `STAT_NO_CRC` and unknown-status packets at the HAL boundary.** v0.7.2 closed the `STAT_CRC_BAD` leg of the leak but `STAT_NO_CRC` packets still flowed into the decoder, where the random bytes after the LoRa header parsed as a "valid" Meshtastic packet and produced a phantom node row in the local SQLite (one packet, no name, no role, never heard again). Fleet diagnostics on a high-traffic Meshpoint (nopemesh, v0.7.2 baseline) measured 4 NO_CRC packets per 30 minutes alongside 108 CRC_BAD and 72 CRC_OK, with the resulting rows accumulating into a 92%-phantom local node table (~72k of ~78k total nodes). `SX1302Wrapper.receive()` now drops `STAT_NO_CRC` with a counted WARNING (`RX NO_CRC if=N sf? bw=? rssi=? snr=? size=? (total NO_CRC: N)`) and additionally drops any packet whose status is neither `CRC_OK`, `CRC_BAD`, nor `NO_CRC` so that future HAL revisions introducing a new status code cannot silently re-open the leak. New `no_crc_count` and `unknown_status_count` properties on the wrapper for observability.
- **Defense in depth: drop Meshtastic headers with `hop_limit > hop_start`.** A Meshtastic packet originates with `hop_limit == hop_start` and decrements `hop_limit` at each relay while `hop_start` stays fixed, so `hop_limit > hop_start` is mathematically impossible for an honestly-originated packet. `MeshtasticDecoder._parse_header()` now returns `None` for that combination so the corrupted bytes never reach the storage layer. Caught two of the five fresh phantoms on the kmax test Pi and four of four on nopemesh in fleet diagnostics, independent of the wrapper-level status filter. Zero false-positive risk by construction.
- **Hardware-validated three ways.** Fresh-SD install (Meshpoint-MNTD-RAKV2 .49) exercises the full `install.sh` path with `bcrypt` + `PyJWT` deps and the bootstrap → `/setup` → `local.yaml`-creation flow end to end. Upgrade from v0.7.2 (Sensecap M1) confirms the existing `local.yaml` is preserved untouched on service start, and the `web_auth` block is appended atomically when the user completes `/setup`. RAK V2 .141 confirms the upgrade-on-top-of-RC path. All three flows green; no phantom rows observed on the upgraded high-traffic device since the no-crc fix landed.
- **Internal:** new `requirements.txt` deps `bcrypt>=4.2.0` and `PyJWT>=2.10.0`. New `src/api/auth/` package: `password_hasher`, `jwt_session`, `lockout_tracker`, `auth_service`, `auth_bootstrap`, `dependencies`, `ws_guard`. New routes `src/api/routes/auth_routes.py` and `src/api/routes/identity_routes.py`. New CLI `src/cli/reset_password_command.py`. New frontend `frontend/auth/{setup,login}.html`, `frontend/css/auth.css`, `frontend/js/auth.js`, `frontend/js/signout_controller.js`. New tests: `test_password_hasher`, `test_jwt_session`, `test_lockout_tracker`, `test_auth_service`, `test_auth_dependencies`, `test_auth_routes`, `test_auth_page_serving`, `test_auth_bootstrap`, `test_identity_route`, `test_protected_router_wiring`, `test_reset_password_command`, plus the no-crc test additions in `test_sx1302_wrapper.py` and the new `test_meshtastic_decoder_header_validity.py`. `tests/test_relay_node_header.py` default `flags` byte moved from `0x03` (hop_limit=3, hop_start=0, structurally impossible) to `0x63` (hop_limit=3, hop_start=3, valid direct packet) so existing relay-node tests pass under the new validity check. 401 tests passing, ruff clean, bandit clean.

### v0.7.2 (May 5, 2026)

Two-fix bundle on top of v0.7.1. One small UX feature for hop-chain debugging, one quiet-but-important correctness fix that was inflating node counts on the cloud catalog and producing intermittent garbled-but-readable text on the local mesh. Both ride together because they touch the same RX path. Pure-Python, no recompile needed.

- **Drop `STAT_CRC_BAD` packets at the HAL boundary instead of forwarding them to the decoder.** `SX1302Wrapper.receive()` was logging the diagnostic WARNING for CRC-failed packets but still appending them to the returned packet list, with `crc_ok=False` set on the `ConcentratorPacket`. No downstream code (`concentrator_source`, `packet_router`, decoders) ever read the `crc_ok` field, so RF-corrupted bytes flowed into `MeshtasticDecoder.decode()` where the source-ID was extracted directly from the corrupted header. Three observable downstream symptoms produced by this: (1) **phantom node IDs** registered in the local SQLite node table and propagated up to the cloud DynamoDB node catalog, where a single bit-flip in the source-ID field creates a new "node" sharing all-but-one bit with a real source ID; (2) **false ENCRYPTED packet attribution** when the channel-hash byte was corrupted and stopped matching the LongFast hash; (3) **garbled-but-readable text** when AES-CTR XORed corrupted ciphertext with the keystream, producing mostly-correct plaintext with a few mangled characters. Hardware-validated on RAK V2: 14 historical phantoms in the local DB matched the bit-flip fingerprint of legitimate neighbors (`7d8b98a9`, `a0dd8936`, etc.), and zero new phantoms have entered the database since the fix. Cloud-side `active_nodes_24h` count is expected to drop sharply over the 24-48h after fleet rollout. Closes [#34](https://github.com/KMX415/meshpoint/issues/34).
- **Relay-node visibility on the dashboard.** Surfaces the Meshtastic header `relay_node` byte (the lowest byte of the last relay node's ID) through the decoder → `Packet` model → SQLite schema (with idempotent `ALTER TABLE` migration for existing installs) → WebSocket payload → dashboard packet feed. Source cells in the packet feed now read `!source ↝ !relay` whenever the packet was relayed, with full short-ID resolution when the relay byte matches a known node in the local registry. Clicking a relayed packet draws a line on the map between the source marker and the relay marker so you can trace the hop chain visually. Direct (non-relayed) packets render as before. Real-world utility: tracing a hop chain back to a rooftop node and confirming its ERP from the RSSI/SNR pattern.
- **`hop_limit` on outbound TX now honors `TransmitConfig` instead of being hardcoded to 3.** Two paths (`send_text_message` and the NodeInfo broadcaster) were ignoring the configured hop limit and using a hardcoded `3` regardless of what was set in `local.yaml`. Behavior is unchanged for installs running the default (still 3); fixes the silent "I set `hop_limit` in my yaml and it didn't take" gap. The dashboard's per-packet HOPS column (`hop_used / hop_limit`) now reflects the actual configured ceiling.
- **Internal:** new `tests/test_sx1302_wrapper.py` covers the CRC_BAD drop contract (synthetic `STAT_CRC_BAD` input is dropped, `crc_bad_count` increments, the WARNING fires, the decoder is not reached). New `tests/test_relay_node_header.py` covers `relay_node` header byte parsing and `Packet.relay_node` population. `tests/test_database_migration.py` extended for the `packets.relay_node` ALTER TABLE path. 297 tests passing, ruff clean.

### v0.7.1 (April 30, 2026)

Polish bundle on top of the v0.7.0 source-publication release. Edge-only, no cloud changes. Touches radio tab UX, branding, and a handful of small upgrade-path papercuts. Pure-Python, no recompile needed.

- **Radio tab redesign.** Reworked the Radio tab with an SDR-console aesthetic: status lamps, readout cards, an analog-style duty-cycle gauge, a new NodeInfo Broadcast card, and a sticky restart banner that floats at the top while you scroll instead of getting buried at the bottom of the page. Channels table behavior is unchanged.
- **NodeInfo broadcast is now configurable from the dashboard.** New card on the Radio tab shows live telemetry (next broadcast countdown, last-sent timestamp, current interval, status lamp), exposes preset chips (`Off / 5m / 30m / 1h / 3h / 6h / 12h / 24h`) plus a free-form 5-1440 minute input, and a `Send Now` button that fires an immediate NodeInfo packet without waiting for the next scheduled tick. `interval_minutes: 0` pauses periodic broadcasts; non-broadcast TX (DMs, replies) is unaffected. New telemetry keys (`last_sent_at`, `next_due_at`, `running`) on `GET /api/config/nodeinfo`. New `POST /api/config/nodeinfo/send` endpoint.
- **Interval changes hot-reload without a service restart.** Saving a new NodeInfo interval immediately wakes the broadcast loop and re-anchors the next-due time, including during the initial 60-second startup delay window. Pausing (`interval=0`) cleanly idles the loop; resuming fires the next broadcast right away if one was already overdue. Only `startup_delay_seconds` changes still require a restart, and the UI says so.
- **Pending-changes cue on Save buttons.** When the displayed NodeInfo interval differs from the saved value, an amber notification dot pulses at the top-right of the Save button so unsaved work is hard to miss. Clears automatically on save or page refresh.
- **Save NodeInfo card auto-refreshes after a broadcast fires.** Previously the countdown got stuck on "broadcasting..." until you reloaded the page.
- **Send Advert button on the MeshCore Companion card now actually works.** Previously it POSTed to the text-message endpoint with empty body, got rejected by the empty-text validation, and surfaced "Advert failed" with nothing in the logs. Added a dedicated `POST /api/messages/advert` endpoint that calls `MeshCoreTxClient.send_advert()` directly. Reported by iceice400.
- **Branding consistency pass.** All user-facing prose and log lines now read "Meshpoint" and "Meshradar" (one word, capital M) instead of "Mesh Point" and "Mesh Radar". Most importantly, the default Meshtastic NodeInfo `long_name` broadcast over RF now reads `Meshpoint`, so the device shows up correctly on `meshmap.net`, the Meshtastic phone app, and neighbor MQTT envelopes. Other surfaces touched: dashboard header, browser tab title, FastAPI auto-docs, CLI prose (`meshpoint setup`, `meshpoint status`, `wizard_meshcore`), installer prose, systemd unit descriptions, and module docstrings. Code identifiers (CLI command name, Python module names, YAML keys) are unchanged: branding rule applies to prose only.
- **Duty cycle default now auto-derives from your region.** Previously hardcoded to `1.0` (the EU 1% etiquette ceiling) regardless of where you were. New `resolve_max_duty_percent()` reads `radio.region` and applies a conservative regional default (US: 10%, EU 868: 1%, ANZ: 10%, IN: 1%, KR: 1%, SG 923: 10%) unless `relay.max_duty_percent` is explicitly set in `local.yaml`. Source surfaced in the Radio tab duty gauge as `region_default` vs `user_override`. See `docs/RADIO-CONFIG-EXPLAINED.md` for how to override.
- **Mobile responsive polish.** All four dashboard tabs (Dashboard, Stats, Messages, Radio) render cleanly on phone-width viewports. Validated with the official Playwright MCP at iPhone 14 Pro and Galaxy S24 viewports.
- **Header `Meshradar` brand link.** The "Meshradar" portion of the dashboard header is now a link to `meshradar.io` (opens in new tab). The "Meshpoint" portion stays plain text. Requested by Parker WEST.
- **Setup wizard preserves your existing coordinates.** Example coordinates in the location prompt now show neutral NYC values (`40.7128, -74.0060`) instead of a developer-specific location. Existing `device.latitude` / `device.longitude` in `local.yaml` are still preserved as the prompt default, so re-running `meshpoint setup` does not overwrite them.
- **`install.sh` upgrade-aware banner.** When run on a Meshpoint that already has an existing install (detected via `config/local.yaml` presence or `meshpoint.service` enabled), the closing banner now reads "Meshpoint upgrade to vX.Y.Z complete: restart the service" instead of the spurious "Reboot to apply SPI/UART changes" message that was misleading users on every v0.7.0+ upgrade. Fresh installs still see the full first-run flow.
- **MQTT topic clarification in `default.yaml`.** Added inline comments explaining that `mqtt.topic_root` and `mqtt.region` are concatenated to form the full Meshtastic spec topic (`<topic_root>/<region>/2/e/<channel>/<gateway>`), and that `mqtt.region` is independent of `radio.region`. Avoids the double-region footgun (`msh/US/FL/US/...`) where users assume `topic_root` is the complete prefix.
- **FastAPI app version follows `__version__`.** The auto-generated `/docs` Swagger header was hardcoded to `0.1.0` since v0.1.x. Now reads from `src.version.__version__` so it matches the running release.
- **Internal:** new `tests/test_messages_advert_route.py` (5 tests, FastAPI TestClient pattern), `tests/test_nodeinfo_broadcaster.py::TestNodeInfoBroadcasterHotReload` (10 tests covering hot-reload, pause, resume, startup-delay interruption), `tests/test_duty_cycle_resolver.py` (region resolution + override semantics). 254 tests passing, ruff clean.

### v0.7.0 (April 28, 2026)

Distribution architecture change: the eleven core SX1302/MeshCore modules are now shipped as Python source files in `src/{hal,capture,decode,transmit}/` instead of pre-compiled `.cpython-*.so` binaries. Behavior is identical to v0.6.8; the change is purely about distribution format. Closes issue #32.

- **Source published.** All eleven modules (HAL wrapper, channel-plan builder, GPS reader, concentrator capture source, SX1262 SPI source, AES-CTR crypto service, Meshtastic and Meshcore decoders, portnum handlers, packet router, Meshtastic packet builder) ship as plain `.py` files under the existing AGPL-3.0 license. Auditability and portability to non-aarch64 hardware become trivial.
- **Upgrade path uses `install.sh`.** `scripts/install.sh` now removes any `.cpython-*.so` left behind by previous installs before the venv is set up. After `git pull`, run `sudo /opt/meshpoint/scripts/install.sh` followed by `sudo systemctl restart meshpoint`. A `git pull` alone is not sufficient on existing v0.6.x devices: Python's import machinery would prefer the stale binary over the new source.
- **Boot-time stale-`.so` detection.** A startup WARN fires (and lists the offending files) if compiled binaries somehow re-appear in `src/`. Surfaces in `meshpoint logs` so you can fix the install before behavior freezes at v0.6.x.
- **RX diagnostic logging.** Every CRC_BAD packet on the SX1302 concentrator now logs a WARNING with the IF chain, SF, BW, RSSI, SNR, size, and a running CRC_BAD counter. Useful for diagnosing rapid-fire packet loss caused by overlapping LoRa transmissions on the same demodulator. Per-packet RX traces are also available via the new `MESHPOINT_DEBUG_RX=1` environment variable (off by default).
- **Internal:** retired the Cython build pipeline that produced the per-release `.cpython-*.so` artifacts since it's no longer needed.

### v0.6.8 (April 26, 2026)

Pure-Python follow-up to v0.6.7. No core module recompile required: just `git pull` + `systemctl restart`. Fixes two user-visible regressions surfaced after v0.6.7 shipped, plus the long-standing `PRIVATE_HW` labeling on community maps.

- **Auto-derived Node ID is now persisted to `local.yaml` on first boot.** v0.6.7 added stable Meshtastic identity but only displayed the derived value on the dashboard if you happened to also save the Radio settings page; until then the API kept returning `node_id_hex: ""` and the field rendered blank. Reported by Parker WEST. The Meshpoint now writes the derived value to `transmit.node_id` automatically the first time it falls back to the `device_id` derivation, then treats it as a normal pinned config value on every subsequent restart. Hint text on the Radio tab tracks the source ("Pinned in local.yaml. Edit to override." vs "Random fallback (no device ID configured).") so you can tell at a glance where the value came from. End-to-end validated on RAK V2 with a fresh derive → persist → reload cycle.
- **Hardware model now reports as `PORTDUINO` (37) instead of `PRIVATE_HW` (255).** Reported by holmebrian. Other Meshpoints, MQTT gateways, and `meshmap.net` were displaying every Meshpoint as the generic "private hardware" label even though Meshtastic has had a `PORTDUINO` enum value for Linux-based nodes since 2.4. New `HW_MODEL_PORTDUINO` constant alongside the existing `HW_MODEL_PRIVATE_HW`, threaded through `NodeInfoBroadcaster` as the default. Verified on a witness Meshtastic phone after the broadcast cycle (60 s after restart, then every 30 min). Existing nodes will pick this up automatically on their next NodeInfo decode.
- **Local Stats tab "Network" section now actually renders.** The Hardware Models donut on the local dashboard was hidden for everyone, even though the underlying SQLite query was returning data (143 of 458 nodes had a populated `hardware_model` column on the test RAK). Two bugs: (1) the section was section-level hidden until **roles** had data, but the deferred edge decoder bug filters role 0 (= `CLIENT`, the most common role) out at decode time, so roles is effectively always empty on v0.6.x; (2) the `HW_NAMES` lookup table on the frontend had drifted from the upstream Meshtastic `HardwareModel` enum, so any model that DID render was getting the wrong label. Fixed both: each chart now hides itself independently, the section appears as long as either has data, and `HW_NAMES` is regenerated from `mesh.proto` (covers 0..129 plus 255). The Device Roles chart will start populating once the v0.7.0 core module bundle ships the deferred decoder fix.
- **Internal:** new `node_id_source` property on `TxService` ("config" / "derived" / "random") for API + dashboard introspection. New `persist_derived_node_id` constructor flag for test isolation. Eight new tests covering source-tracking and the auto-persist path (success, no-op when pinned, no-op when random, swallowed PermissionError). Two new tests on `NodeInfoBroadcaster` for the PORTDUINO default + override.

### v0.6.7 (April 25, 2026)

Stable Meshtastic identity, NodeInfo broadcasts, and a clutch of small reliability fixes. **Core module recompile required.** Fixes Meshtastic DMs sent from a Meshpoint never arriving at recipients, even though the dashboard showed "Sent". Reported by Max_Plastix.

- **Stable `source_node_id` per Meshpoint.** Previously the Meshtastic node ID was randomly chosen on every service restart unless the user manually set `transmit.node_id` in `local.yaml` or via the dashboard radio tab. Recipients ended up seeing a brand new "ghost" Meshpoint each restart and never built a stable contact, so direct messages had nowhere to thread to. Resolution priority is now (1) `transmit.node_id` in config, (2) deterministic SHA-256 derivation from the provisioned `device.device_id` UUID (stable across reboots), (3) cryptographically random fallback with a startup WARN if neither is set. Reserved IDs (`0x00000000`, `0xFFFFFFFF`) are explicitly skipped. Existing manually-set node IDs are preserved.
- **Periodic NodeInfo broadcasts.** New `NodeInfoBroadcaster` advertises the Meshpoint's identity (long name, short name, node ID, hardware model `PRIVATE_HW`) on the mesh 60 seconds after startup and every 30 minutes after that. This is what makes recipient nodes (T-Beam, Heltec, etc.) form a contact for your Meshpoint so they can route DMs back to it. Same `source_node_id` is used for both NodeInfo and outbound DMs/text so recipients see one consistent identity.
- **Setup wizard surfaces the resolved identity.** The `meshpoint setup` Device step now prints the device ID, derived node ID, long name, and short name with their origin (`existing config` vs `auto-generated`) so you can see exactly what will be advertised on the mesh before saving.
- **Setup wizard preflight check.** `meshpoint setup` now verifies write permission to `config/local.yaml` and the existence of the `config/` directory **before** asking any of the eight questions, so it bails immediately with an actionable message instead of failing 60 seconds in after you've filled in the whole form. Hit by holmebrian during initial setup.
- **Wizard config preservation (carried over from disk).** Untouched sections of `local.yaml` (e.g. `meshcore_usb`, `mqtt`) are now preserved when re-running `meshpoint setup`, instead of getting wiped out by the wizard overlay. New `_deep_merge` helper handles nested merges. 13 unit tests cover the merge semantics.
- **Relay marked experimental, log noise tamed.** Relay TX has never worked end-to-end (see ROADMAP.md). When `relay.enabled: true` you now get a one-line WARN banner at startup making this explicit. The per-packet `Relay TX: no payload available` warning now fires only once per process and drops to DEBUG for every subsequent skip, so logs stay readable while the v0.7.0 relay completion is in flight.
- **Cross-protocol sender-name leak in DMs fixed.** Meshtastic inbound DMs were showing arbitrary MeshCore contact names ("Guzii_RedV4" leaking into a Meshtastic conversation, etc.) because the unscoped fallback in `_save_and_notify` grabbed the first available `mc:%` node row regardless of the inbound packet's protocol, then **persisted that wrong name back to the Meshtastic node row** so it stuck across reconnects. Each fallback is now scoped to its own protocol, and a parallel Meshtastic source-id lookup now runs for inbound MT direct messages (mirroring the existing broadcast path). Found mid-validation while testing the v0.6.7 NodeInfo fix.
- **Auto-cleanup of pre-v0.6.7 contamination.** New idempotent startup migration in `DatabaseManager` repairs Meshtastic node rows whose `long_name` was overwritten by a MeshCore contact name in earlier versions. Affected rows have their `long_name` reset to NULL on first restart of v0.6.7; the next NodeInfo broadcast from the real node repopulates the correct name automatically. Migration is a no-op on clean databases. (Previously-stored corrupted message rows in the `messages` table are not auto-repaired since they're an immutable per-message snapshot; delete the affected conversation if the historical naming bothers you.)
- **`docs/COMMON-ERRORS.md`** gains entries for "Meshtastic DM shows Sent but recipient never gets it" (now fixed in v0.6.7) and "Two Meshpoints with the same node ID breaking the mesh" (only happens if you `dd` clone an SD card without re-running `scripts/provision.py`).
- **`docs/RADIO-CONFIG-EXPLAINED.md`** documents the three identity sources (dashboard / wizard / yaml), their resolution priority, and the fact that identity changes require a service restart.
- **Internal:** new tests for `_resolve_node_id` (8 cases), `NodeInfoBroadcaster` (8 cases), `build_nodeinfo` round-trip through the decoder (8 cases, private repo), wizard preflight (4 cases), and the relay no-payload dedup (4 cases). 32 new tests total, all green.

### v0.6.6 (April 25, 2026)

MeshCore reliability patch. Small follow-up to v0.6.5 cleaning up rough edges around the MeshCore USB companion. No edge concentrator changes, no cloud changes.

- **Companion connects cleanly on `systemctl restart meshpoint`.** ESP32-S3 boards (Heltec V3/V4 etc.) need 6-10 seconds to be USB-ready after a reboot, but the underlying meshcore library was giving up after 5. Bumped the handshake window so cold connects work the first time instead of needing a manual USB unplug.
- **Background reconnect with DTR soft-reset.** When the initial handshake does miss anyway, the source now schedules a background reconnect with exponential backoff and pulses DTR low to soft-reset the chip on the second attempt onwards. Recovers in 30-50 seconds without user intervention. On boards where DTR is wired to RESET (the common case for ESP32 dev boards) this is a real hardware reset; on others it's a harmless no-op.
- **Health check tuning.** The MeshCore health check (in place since March) was sometimes treating slow but healthy responses as a dead connection and triggering a full reconnect cycle. We caught it on the RAK during this round of testing: every 2-3 minutes the source would tear down and rebuild, costing 15-20 seconds of MeshCore RX downtime each time. Whether this was happening on other Meshpoints in production is unknown; it was never surfaced as a user-visible symptom. The health check now passes a proper command timeout, skips the active probe when inbound events have arrived recently (proof of life), and tolerates a single transient miss before declaring the connection dead.
- **Dashboard radio tab now shows real values.** The MeshCore Companion card was stuck on `Name: Unknown / Frequency: ? MHz / SF: SF? / TX Power: ? dBm` for everyone. Dashboard was reading from the wrong source. It now reads from the same place the `meshpoint meshcore-radio` CLI does, which has always shown correct values.
- **Smarter `meshpoint meshcore-radio` CLI.** Now prompts for a full Pi reboot after applying new radio settings instead of doing a service restart that races the still-recovering USB CDC stack. Reboot is the reliable path; restarting the service mid-USB-enumeration leaves MeshCore in a half-connected state where messages don't flow.
- **Heltec V4 ACM-shift fix.** The companion would temporarily move from `/dev/ttyACM0` to `/dev/ttyACM1` during the post-config reboot, get pinned into your `local.yaml`, then become unreachable after the next Pi reboot when the kernel re-assigned it back to `/dev/ttyACM0`. The CLI now switches your config to `auto_detect: true` whenever it sees the port shift, so the companion is found wherever it lands across reboots.
- **`docs/COMMON-ERRORS.md`** gains entries for the MeshCore handshake-failed log message and spurious health-check reconnects.
- **Demoted `No MeshCore USB device found` from WARNING to INFO** with friendlier wording (it's an expected state if the source is enabled but no companion is currently plugged in, not an error).
- **Internal:** fixed deprecated `asyncio.get_event_loop()` pattern in `tests/test_message_repository.py` so the suite remains compatible with newer test files using `IsolatedAsyncioTestCase`.

### v0.6.5 (April 22, 2026)

- **Network watchdog reliability fix:** the watchdog no longer triggers an infinite reboot loop on networks where the gateway blocks ICMP. Gateway pings now fall back to `8.8.8.8` before a check is counted as a failure, and **auto-reboot is disabled by default** (`REBOOT_THRESHOLD = 0`). Stage 1 recovery (interface restart at 3 consecutive failures) is unchanged. To re-enable automatic reboots, edit `scripts/network_watchdog.py` and set `REBOOT_THRESHOLD` back to `6`. Startup banner now logs the active thresholds so you can confirm the policy at a glance. Thanks to first-time contributor [@dotchance](https://github.com/dotchance) for catching this and shipping the fix. ([#27](https://github.com/KMX415/meshpoint/pull/27))
- **Support documentation expansion:** new `docs/FAQ.md`, `docs/HARDWARE-MATRIX.md`, `docs/COMMON-ERRORS.md`, `docs/RADIO-CONFIG-EXPLAINED.md`, and `docs/MQTT-AND-MESHRADAR.md`. README "Support and documentation" section reorganized into Setup / When-something-goes-wrong / Project groups.
- **SX1302 minimum bandwidth documented:** `docs/HARDWARE-MATRIX.md` and `docs/RADIO-CONFIG-EXPLAINED.md` now explain that the SX1302 concentrator cannot tune below 125 kHz, which is why MeshCore (62.5 kHz) requires a USB companion radio for RX.

### v0.6.4 (April 16, 2026)

- **Meshtastic broadcast sender names:** received messages on public channels (LongFast, etc.) now show the sending node's long name, short name, or hex ID. Previously the UI showed the conversation key (`broadcast:meshtastic:0`) in place of the sender because the backend never resolved the source node for Meshtastic broadcast text packets. The v0.6.2 sender-name fix only covered MeshCore; this finishes the job for Meshtastic. ([#19](https://github.com/KMX415/meshpoint/issues/19))
- **Defensive frontend filter:** chat UI no longer renders strings starting with `broadcast:` as a sender label if they ever slip through.

### v0.6.3 (April 16, 2026)

- **TX channel hash fix:** messages sent from the dashboard were going out with hash 0x02 (invisible to the mesh) instead of the correct 0x08. The primary channel name defaulted to blank, producing the wrong hash. Now defaults to "LongFast" matching Meshtastic firmware. ([#21](https://github.com/KMX415/meshpoint/issues/21))
- **Primary channel editable:** channel 0 can now be renamed and saved from the Radio settings page. Previously edits reverted on refresh. ([#13](https://github.com/KMX415/meshpoint/issues/13))
- **Channel display cleanup:** Radio settings shows the actual channel name (e.g. "LongFast") instead of "Primary (LongFast)".

### v0.6.2 (April 16, 2026)

- **MQTT channel name fix:** MQTT topics now use the actual channel name (LongFast, MediumFast, ShortFast, etc.) instead of `chXX` hashes. New `ChannelResolver` maps all 8 standard Meshtastic presets and supports user-configured channel keys. ([#20](https://github.com/KMX415/meshpoint/issues/20))
- **Chat sender names:** received messages now show the sender's node name or hex ID. Previously there was no way to tell who sent what. ([#19](https://github.com/KMX415/meshpoint/issues/19))
- **Chat day dividers:** messages from different days are separated by date labels (Today, Yesterday, or the date) in the chat window.
- **Espressif USB udev rule:** installer adds a udev rule so Heltec V3/V4 and T-Beam ESP32-S3 USB serial devices are accessible to the meshpoint service user without manual group changes. ([#12](https://github.com/KMX415/meshpoint/issues/12))

### v0.6.1 (April 11, 2026)

- **Local stats dashboard:** new Stats tab on the local dashboard with 12 live Chart.js charts: protocol split, packet types, RSSI distribution, signal quality, direct vs relayed, active nodes, device roles, hardware models, relay decisions, rejection reasons, and traffic timeline. All generated locally, no cloud needed.
- **Enriched heartbeat:** edge accumulates per-packet stats in memory and sends a batched summary to Meshradar in each heartbeat instead of the cloud processing every individual packet. Same data, significantly fewer backend operations. Savings scale with fleet size.
- **Local topology layer:** map tab gains a "Topology Links" toggle showing lines between nodes with RSSI/SNR tooltips.
- **Farthest direct tracking:** tracks the farthest direct (0-hop) node heard, with distance and signal strength, visible on the stats page.
- **Relay rejection tracking:** relay engine now records why packets are rejected (duplicate, rate limited, type filtered, signal bounds), visible in local stats.

### v0.6.0 (April 8, 2026)

- **Native mesh messaging:** send and receive Meshtastic messages from the browser. Broadcast to LongFast, talk on custom channels, DM individual nodes. MeshCore messaging via USB companion. SX1302 transmits with correct sync word and encryption.
- **Chat UI:** conversations organized by channel and contact. Signal info on every received bubble. Duplicate badge for relayed messages. History persisted locally.
- **Radio config from dashboard:** region, modem preset, frequency override, TX power, duty cycle, custom channels with PSKs, and TX toggle. All configurable from the Radio tab without SSH.
- **Node discovery:** live node cards with name, ID, protocol, hardware model, signal, battery, last seen. Detail drawer with signal history. DM from node card.
- **Dashboard overhaul:** messaging tab, node cards grid, radio settings page, frequency and SF columns in packet feed.
- **CLI operational report:** `meshpoint report` command with full-screen terminal dashboard: RX stats, traffic breakdown, signal averages, system metrics, health status.
- **Setup wizard improvements:** unique random Meshtastic node ID per device (no collisions), MeshCore companion as its own wizard step.

### v0.5.5 (April 2, 2026)

- **MQTT hotfix:** shipped missing MQTT runtime files (publisher, formatter, pipeline wiring) that were absent from v0.5.4. MQTT config and docs were present but the code was not, so `mqtt.enabled: true` had no effect. Update and restart to activate MQTT publishing.

### v0.5.4 (March 30, 2026)

- **MQTT gateway:** dual-protocol MQTT publishing for Meshtastic (protobuf ServiceEnvelope) and MeshCore (JSON). Publishes to community maps (meshmap.net, NHmesh.live) and Home Assistant. Two-gate privacy model: MQTT is off by default, and only public channel traffic is published unless you explicitly allowlist a private channel. Each Meshpoint gets a unique node-format gateway ID that integrates natively with the Meshtastic ecosystem, appearing on meshmap.net, Liam Cottle's map, and other community tools. Optional JSON mirror for HA/Node-RED, auto-discovery sensor configs, and configurable location precision.
- **Packet type filter (cloud):** filter the Meshradar cloud packet feed by type (traceroute, position, text, etc.) and protocol (Meshtastic/MeshCore). Dropdown filters in the packets tab header.
- **Setup wizard MQTT step:** `meshpoint setup` now includes an MQTT opt-in prompt with broker selection and HA integration toggle.

### v0.5.3 (March 31, 2026)

- **Multi-key decryption:** packets on private Meshtastic channels now decrypt when channel keys are configured in `local.yaml`. Previously only the default key was tried. ([#5](https://github.com/KMX415/meshpoint/issues/5))
- **Heartbeat optimization:** reduced upstream heartbeat interval for lower cloud costs.

### v0.5.2 (March 31, 2026)

- **Core module binary fix:** v0.5.1 shipped updated source but stale compiled `.so` files. This release includes the correctly compiled binaries.

### v0.5.1 (March 30, 2026)

- **Non-LongFast preset fix:** `ConcentratorChannelPlan.from_radio_config()` no longer ignores spreading factor and bandwidth when using the region's default frequency. EU_868 MediumFast (SF9/BW250), ShortFast, and other presets now work correctly. Previously, any preset at the default frequency was silently overridden to LongFast (SF11/BW250). ([#4](https://github.com/KMX415/meshpoint/issues/4))

### v0.5.0 (March 29, 2026)

- **Multi-region frequency support:** 6 Meshtastic regions (US, EU_868, ANZ, IN, KR, SG_923) with auto-tuning concentrator and setup wizard region selector.
- **Preset tuning:** service channel SF and BW are configurable via `local.yaml`. Supports MediumFast, ShortFast, ShortTurbo: not just LongFast.
- **Frequency override:** set `frequency_mhz` in `local.yaml` to tune to a non-default slot within your region.
- **Full portnum decoding:** position speed/heading/altitude, power metrics, routing errors, NEIGHBORINFO, TRACEROUTE payloads.
- **`meshpoint meshcore-radio` CLI:** switch MeshCore companion frequency without re-running the full wizard. Presets (US/EU/ANZ) or custom entry.
- **Startup banner accuracy:** boot log shows the actual radio config, not just the region default.
- **Config stability:** empty YAML sections no longer crash the service on startup.

### Earlier (March 2026)

#### Early March
- **Real-time packet streaming:** cloud dashboard receives packets instantly via WebSocket. Live animated lines trace packets from source nodes to your Meshpoint on the map.
- **Cloud map overhaul:** marker clustering, signal heatmap layer, topology lines from neighborinfo data, and a live Recent Packets ticker panel.
- **SenseCap M1 support:** auto-detects SenseCap M1 carrier board via I2C probe during setup. Flash an SD card and go.
- **14 Meshtastic portnums decoded:** TEXT, POSITION, NODEINFO, TELEMETRY, ROUTING, ADMIN, WAYPOINT, DETECTION_SENSOR, PAXCOUNTER, STORE_FORWARD, RANGE_TEST, TRACEROUTE, NEIGHBORINFO, MAP_REPORT, plus encrypted packet tracking.
- **Device role extraction:** node table shows CLIENT, ROUTER, REPEATER, TRACKER, SENSOR, and other roles from NodeInfo packets.
- **Smart relay engine:** deduplication, token-bucket rate limiting, hop/type/signal filtering, independent SX1262 TX path.

#### Mid March
- **Live dashboard UX:** color-coded packet feed, decoded payload contents, 24h active node counts, version-based update indicator, and enlarged map view.
- **Cloud dashboard tabs:** tabbed layout with fleet view, interactive map controls, device-scoped filters, unified packet cards with signal strength bars, and public activity stream for visitors.
- **MeshCore USB capture:** new capture source for USB-connected MeshCore companion nodes. Auto-detects the device, configures radio frequency via the setup wizard (US/EU/ANZ presets or custom), with auto-reconnect and health monitoring. Startup banner shows all active sources.
- **Custom frequency tuning:** configurable SX1302 channel plan via `local.yaml`. Validated on live hardware with LongFast (SF11/BW250). Dual-protocol HAL patch for simultaneous Meshtastic and MeshCore sync words.
