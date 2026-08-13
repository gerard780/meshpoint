# Upstream sync — KMX415/meshpoint TODO

Compares `main` against `upstream/main` (added as a git remote:
`https://github.com/KMX415/meshpoint.git`, fetched 2026-08-13 — read-only,
nothing merged). **Important methodology note**: a plain `git diff
main...upstream/main` (three-dot) only compares the *merge-base* against
upstream — it does NOT know what we've built independently since diverging,
so it flags files as "different" even when we already have equivalent or
better code under the same path. Every item below was checked against our
actual current `main`, not just the raw diff stat, before being marked
either way. `git log --oneline main..upstream/main` shows 28 commits we
don't have; `main` has 709 commits since the merge-base upstream doesn't
have — this is not a simple "behind," it's two actively diverging forks
(upstream's own commit messages literally say "Port javastraat MeshCore
reconnect/live radio..." — they're pulling *from* this fork too, and at
least one fix commit (`d6ad99e`) is Co-Authored-By this repo's own git
identity).

## Summary table

| # | Item | Status | Scope | Key file(s) |
|---|------|--------|-------|--------------|
| — | Bearer-token login (`X-Meshpoint-Client`) | ✅ Have it | — | `auth_routes.py` |
| — | `meshtastic_hw_names.js` | ✅ Have it | — | credited to us |
| — | Firmware-flash cards/routes (existence) | ✅ Have it | — | `*_firmware_routes.py`, `*_firmware_card.js` |
| — | `serial_config_routes.py` | ✅ Have it (bigger) | — | 457 vs 141 lines |
| — | `stats_chart_host.js` | ✅ Have it | — | credited to us |
| — | Stats-tab / stats-reporter fixes | ✅ Ahead of upstream | — | `stats_tab.js`, `stats_reporter.py` |
| — | `database.py` WAL + packet_id index | ✅ Have it | — | credited to us |
| — | URL-hash-before-scripts flash fix | ✅ Have it | — | `index.html` |
| **#1** | esptool venv-symlink resolver | 🔲 To port | Small | `src/api/firmware/esptool_binary.py` (new) |
| **#2** | MeshCore/serial live-radio rewrite | 🔲 To port | Large | `src/transmit/meshcore_*.py`, `src/capture/serial_*.py` (new cluster) |
| **#3** | Flash reports success even when esptool fails | 🔲 Real bug | Small | `meshtastic_firmware_routes.py:439-461`, `meshcore_firmware_routes.py` |
| **#4** | Reconnecting capture source not stopped before flash | ✅ Fixed | Small | `meshtastic_firmware_routes.py:423`, `meshcore_firmware_routes.py:447` |
| **#5** | Port matching is exact-string, not alias-aware | ✅ Fixed | Small | `meshtastic_firmware_routes.py:385`, `meshcore_firmware_routes.py:408` |
| **#6** | MeshCore name lookup hits live USB bus, not SQLite | ✅ Fixed | Small | `src/api/message_name_resolver.py` |
| — | Their release/docs/RC-channel commits (7) | ⏭️ Skip | — | `README.md`, `docs/plans/*`, merge commits |

## Confirmed — already have equivalent, no action needed

- [x] Bearer-token login for non-browser clients (`X-Meshpoint-Client`
      header → token in login response body). `src/api/routes/auth_routes.py`
      is functionally byte-for-byte identical to upstream's — only comment
      wording differs (`git diff main upstream/main -- src/api/routes/auth_routes.py`).
- [x] `frontend/js/meshtastic_hw_names.js` — upstream's copy literally
      credits us in its own header comment ("Credit: javastraat/meshpoint
      39910a0"). Only the comment was reworded; the actual `HW_NAMES` table
      is identical.
- [x] Meshtastic/MeshCore firmware-flash dashboard cards + routes
      (`src/api/routes/meshtastic_firmware_routes.py`,
      `meshcore_firmware_routes.py`,
      `frontend/js/configuration/meshtastic_firmware_card.js`,
      `meshcore_firmware_card.js`) — we already have all four files at the
      same paths. Implementation isn't identical (see the esptool item
      below), but the feature itself already exists here.
- [x] `src/api/routes/serial_config_routes.py` — we already have this file,
      and ours is **457 lines vs upstream's 141** — ours is the more
      complete implementation, not a gap.
- [x] `frontend/js/stats_chart_host.js` — credits us too ("Credit:
      javastraat/meshpoint fc92680"), extracted-refactor of chart code we
      already wrote. Not a gap.
- [x] `stats_tab.js`'s "Protocol Split/Packet Types preferring empty
      heartbeat counters" fix (`076881a`) — checked our own `stats_tab.js`:
      we don't have the same `live.protocols || traffic.X || {}` bug
      pattern at all, because our version already has a different (more
      capable) session-vs-all-time architecture
      (`_protoAlltime`/`_protoSession`, a UI toggle) that upstream doesn't
      have. Similarly `stats_reporter.py`'s `best_rssi`/`best_snr` +
      near-field-ceiling filtering exists on our side and *not* upstream's
      — we're ahead here, not behind.

## Medium priority — genuinely new, worth reviewing to port

- [ ] **#1** `EspToolBinaryResolver` (`src/api/firmware/esptool_binary.py`,
      new upstream-only file) does venv-sibling esptool lookup (checks next
      to `sys.executable` before falling back to PATH) with a real fix for
      symlinked venvs (Co-Authored-By this repo's identity — `d6ad99e`,
      "Fix venv esptool lookup when python is a symlink into /usr/bin").
      Our own `meshtastic_firmware_routes.py`/`meshcore_firmware_routes.py`
      just hardcode `_ESPTOOL_BIN = "esptool"` (plain PATH lookup, no venv
      resolution at all) — simpler, but doesn't handle esptool only being
      installed inside an unactivated venv. Worth porting
      `EspToolBinaryResolver` and wiring both firmware route files to use
      it instead of the hardcoded string.
  - Upstream: `src/api/firmware/esptool_binary.py` (+ `esptool_stream.py`,
    `github_http.py` — shared streaming/release-fetch helpers, check
    whether our two firmware route files duplicate this logic inline and
    would benefit from sharing it too).

- [ ] **#2** MeshCore/serial live-radio rewrite — the one genuinely
      substantial thing that's fully new, not just reworded. No equivalent
      found anywhere in our tree under any filename. **Correction from an
      earlier pass on this file**: I originally split this into two items
      ("MeshCore radio cluster" and a small separate "soft-fail busy
      serial" fix) — wrong. `git diff main upstream/main -- src/capture/serial_source.py`
      is a 654-line rewrite (removed `send_nodeinfo()`/`connected`
      property/constructor name params; added `SerialRadioHandshake`,
      `SerialSelfOriginFilter`, reconnect backoff) that the "soft-fail"
      behavior is actually built on top of — they're the same underlying
      effort, not separable pieces. Full file list:
      - `src/transmit/meshcore_radio_apply.py` — apply MeshCore radio
        presets live (retry-after-reconnect, cross-band timeout recovery).
      - `src/transmit/meshcore_exclusive_radio.py` — exclusive serial lease
        while applying config.
      - `src/transmit/meshcore_channel_sync.py`,
        `meshcore_companion_rename.py`, `meshcore_contacts.py`,
        `meshcore_device_info.py` — channel sync, companion rename, contact
        list, device info (this is also where "show installed companion
        firmware" — `96c5c71` — lives: `MeshcoreDeviceInfoQuery` +
        `SerialFirmwareInfoReader`, confirmed via `tests/test_installed_firmware_info.py`).
      - `src/capture/serial_source.py` (rewritten), `meshcore_dtr.py`,
        `serial_firmware_info.py`, `serial_self_origin.py`,
        `serial_radio_handshake.py`, `serial_device_config.py`,
        `usb_classifier.py` (+12 lines) — supporting capture-layer helpers,
        including the busy/wrong-port soft-fail + background-retry
        behavior (previously: a held serial port aborted FastAPI startup
        entirely) and self-origin packet filtering.
      - `src/capture/capture_coordinator.py` — the one **cleanly separable**
        piece: `start()` currently lets one source's exception abort
        starting every other source. Small (`try`/`except Exception`
        around each `source.start()`, re-raise `ImportError`), low-risk,
        portable on its own without the rest of #2 — but note upstream's
        version of this file also *removed* `sources` property and
        `all_sources_running()` (used by our status LED?) — check we don't
        depend on those before touching this file.
      - `frontend/js/configuration/meshcore_radio_settings.js`,
        `serial_radio_controls.js`, `serial_card.js` (GPS-port-pick
        warning) — the dashboard UI panels for all of the above.
      - Tests: `tests/test_meshcore_radio_apply.py`,
        `test_meshcore_contacts.py`, `test_meshcore_reconnect.py`,
        `test_meshcore_radio_presets.py`, `test_serial_device_config.py`,
        `test_serial_soft_fail.py`, `test_serial_config_routes.py`,
        `test_usb_stable_ports.py`, `test_installed_firmware_info.py`.
      This is a real feature addition (live MeshCore radio/channel
      configuration from the dashboard + serial-source startup
      robustness), not a quick port — worth its own dedicated session.
      **Exception**: the `capture_coordinator.py` try/except is small
      enough to pull as a standalone quick win if wanted, independent of
      the rest.

## High priority — confirmed real bugs, verified against our actual code

Went back and actually read our `meshtastic_firmware_routes.py`/
`meshcore_firmware_routes.py` line-by-line against each upstream fix commit
instead of leaving these as guesses. All three land — same bug, present
verbatim, in both of our firmware route files.

- [ ] **#3** No "esptool actually succeeded" check before claiming the
      flash worked (`525883c`). Confirmed at
      `meshtastic_firmware_routes.py:439-461` and the equivalent block in
      `meshcore_firmware_routes.py`: `success` is captured from the
      streamed esptool result but the `if released:` block right after —
      "Waiting for the board to finish rebooting…", the reconnect attempt,
      "{source.name} reconnected on {port}." — runs **unconditionally**,
      never checking `success` first. If esptool exits non-zero for any
      reason, the UI still says it rebooted and reconnected, and the board
      is silently left on its old firmware. Compounding cause also
      confirmed: our code hardcodes the esptool 5+ `write-flash` (hyphen)
      subcommand (`meshtastic_firmware_routes.py:437`,
      `meshcore_firmware_routes.py:461`) with no check for which esptool
      version is actually installed — `scripts/install.sh:626` always
      `pip install --upgrade esptool`, so a fresh install is fine, but any
      Pi with an older 4.7.x esptool already on it (upgraded before that
      line existed, or a `pip install` that didn't reach the interpreter
      FastAPI actually runs under) would hit exactly this: `write-flash`
      doesn't exist on 4.x (only `write_flash`, underscore), esptool exits
      non-zero, and our UI reports success anyway.
  - Fix shape: check `success` before the reconnect-messaging block (own
    branch for the failure case, matching upstream's "Flash failed... USB
    capture restored" messaging); either detect the installed esptool's
    real subcommand spelling or vendor upstream's `WRITE_FLASH_SUBCOMMAND`
    + `EspToolBinaryResolver.missing_install_hint()` approach.

- [x] **#4** FIXED. A capture source mid-reconnect-loop doesn't get stopped before
      flashing (`39bd92f`). Confirmed at both
      `meshtastic_firmware_routes.py:423` and
      `meshcore_firmware_routes.py:447`: `released = source is not None
      and source.connected`. A source that's actively background-retrying
      a broken connection (holding the serial port open, but
      `connected == False` because the handshake hasn't succeeded yet)
      skips `source.stop()` entirely — esptool then fights the reconnect
      loop for the same port. Fix: `released = source is not None` (always
      stop when a source is matched, regardless of `.connected`).

- [x] **#5** FIXED. Port matching is exact-string-only, not alias-aware
      (`9a0425f`). Confirmed at `meshtastic_firmware_routes.py:385`
      (`if d.serial_port == port`) and `meshcore_firmware_routes.py:408`
      (`if c.serial_port == port`). `port` comes from the browser's
      `<select>` value, which is always the port's current `stable_path`
      (confirmed: `src/hal/usb_classifier.py`'s
      `list_serial_ports_with_stable_paths()` always populates
      `stable_path`, `stable = path_path or id_path or info.device`, so
      it's never empty — the `p.stable_path || p.device` half of
      upstream's matching JS fix is a genuine no-op for us, not a gap).
      But if a companion's *configured* `serial_port` in `local.yaml` was
      pinned under a different alias (e.g. `/dev/ttyUSB0`, set before
      `by-path` symlinks existed on that box) than what `stable_path`
      currently resolves to for the same physical device, the exact match
      fails silently — #4's stop-before-flash logic never even triggers
      because `source` stays `None`, and flash proceeds straight into a
      port already held by the running capture source. Fix: port upstream's
      `_port_aliases()` (resolves every known alias — `device`,
      `stable_path`, `by_id`, `by_path` — for the requested port, then
      checks config against the whole alias set, not one exact string).
      Note the *other* half of `9a0425f` (JS `.filter((p) => p.vid)`) is
      also already a no-op for us — our backend (`system_config_routes.py:168`)
      already filters to `p.vid is not None` before the port list ever
      reaches the frontend.

- [x] **#6** FIXED. MeshCore message-name resolution hits the live USB bus on every
      lookup, not SQLite (`c12da51`, `f6afe0f`). Confirmed: our
      `src/api/message_name_resolver.py`'s `_lookup_meshcore()` calls
      `self._meshcore_tx.get_contacts()` — a live companion round trip, up
      to ~10s, cached for only 10s (`_CONTACTS_CACHE_TTL_S`). Opening the
      Messages tab resolves every conversation's name, so a page load can
      fire many of these back to back, each holding the serial command
      channel — upstream's own commit message cites a live-observed
      symptom ("10 sec to load the channels... 15 sec to load the chats")
      and a worse one: it can race an actual outgoing send into a
      `Send timed out` reconnect loop. Fix (already have everything it
      needs — no dependency on the missing `meshcore_contacts.py` module):
      resolve from `self._node_repo.get_by_id(...)` instead — contact
      enrichment already writes `long_name`/`short_name` onto `nodes` rows
      elsewhere, so there's no need to hit the live bus just to display a
      name. Small, self-contained, cleanly separable from #2.

## Verification pass complete

Went back through all 28 commits individually (not just by filename
pattern) to answer "do we have them all now" honestly — every one is now
either in a numbered item above, in "confirmed no action needed," or in
"skip" below with a reason. Nothing left unexamined.

## Skip

`docs/plans/v0.7.9-release.md` (their internal planning doc), version
bump/changelog/README/RC-channel commits, merge commits.

## Not yet done

Nothing has been merged, cherry-picked, or ported yet — this file is the
result of the investigation only. Next step is picking an item above and
deciding whether to port it as a clean reimplementation (matching this
fork's own conventions) or attempt a real `git merge`/cherry-pick, which
would need real conflict resolution given 709 commits of independent
history on our side.
