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
| **#1** | esptool venv-symlink resolver | ⏭️ Skipped — works today, any failure is loud not silent | — | `src/api/firmware/esptool_binary.py` (upstream-only) |
| — | MeshCore radio preset apply, rename, channel sync, contacts, device info | ✅ Already have it, already has UI | — | `meshcore_usb_source.py`, `meshcore_tx_client.py`, `meshcore_card.js` |
| **#2a** | Contact picker (`/api/messages/contacts`) hits live USB bus, no cache | 🔲 Real bug | Small | `src/api/routes/messages.py:246` |
| **#2b** | `set_radio_params()` never verifies the preset actually stuck after reconnect | 🔲 Real gap | Small-medium | `meshcore_usb_source.py:564`, `meshcore_config_routes.py:331` |
| **#2c** | `CaptureCoordinator.start()` still aborts all sources if one throws | 🔲 Real bug | Small | `src/capture/capture_coordinator.py:32` |
| **#2d** | Meshtastic serial source has no retry/reconnect loop at all (unlike MeshCore's own, which already works) | 🔲 Real gap | Medium | `src/capture/serial_source.py:445` |
| **#3** | Flash reports success even when esptool fails | ✅ Fixed (scoped) | Small | `meshtastic_firmware_routes.py:439-461`, `meshcore_firmware_routes.py` |
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

- [ ] **#2** MeshCore/serial live-radio work. **Major correction, second
      pass**: my original assessment ("no equivalent found anywhere in our
      tree, a whole feature build") was wrong, and wrong for a specific,
      avoidable reason — I searched by filename (`find src/transmit
      -iname "*meshcore*"`) and treated "no file with that exact name" as
      "no equivalent capability," without ever opening
      `src/capture/meshcore_usb_source.py`/`src/transmit/meshcore_tx_client.py`
      to check what they actually contain. Opened them this pass. We
      already have live radio-preset apply, companion rename, channel
      sync, contacts, and device info — all wired to real dashboard UI,
      not just backend stubs. Confirmed by reading the actual code AND
      finding the frontend calls that use it:
      - `meshcore_usb_source.py`'s `set_radio_params()` — already reuses
        the companion's live connection (not a cold-reconnect CLI steal),
        with retry-on-timeout via `_trigger_reconnect()` (backoff + DTR
        reset pulse). `PUT /api/config/meshcore/companion-radio`
        (`meshcore_config_routes.py:331`) → `meshcore_card.js:465`. Real,
        working, already better UX than the standalone `meshpoint
        meshcore-radio` CLI per its own docstring.
      - `set_companion_name()` (rename) — `meshcore_card.js:943-970`,
        "Companion renamed" toast.
      - `meshcore_tx_client.py`'s `sync_channels()` —
        `PUT /api/config/meshcore/channels` → `meshcore_card.js:870`.
      - `get_contacts()`, `get_device_info()` — both present and wired
        (contacts also reachable via the Messages tab's contact picker,
        see the real gap below).
      So #2 is **not** "build MeshCore live radio config" — that already
      exists and works. What's actually missing, verified individually,
      is four separate, much smaller resilience gaps on top of an already-
      mature feature:

      - [ ] **#2a** `GET /api/messages/contacts` (`src/api/routes/messages.py:246`)
        calls `_meshcore_tx.get_contacts()` live, every single time the
        Messages tab's "new conversation" contact picker opens — no
        caching at all. Same bug class #6 already fixed, but a different
        endpoint #6 didn't touch (#6 was `message_name_resolver.py`'s
        per-message name lookups only). Small, same shape as #6: resolve
        MeshCore contacts from `node_repo` (SQLite) instead, matching how
        #6 already established that contact enrichment keeps
        `long_name`/`short_name` current there.

      - [ ] **#2b** `set_radio_params()` triggers a reconnect after
        applying a preset but never verifies afterward that the new
        params actually took (matches upstream's `e7a9297` "Retry MeshCore
        set_radio once after reconnect when preset did not stick" and
        `bf82ea2`/`dcff8b0`'s cross-band timeout recovery). The route
        (`meshcore_config_routes.py:331`) fires the command and returns
        `rebooting: true` immediately, telling the frontend to just show
        a "reconnecting" state — nothing re-checks the radio's actual
        state once it's back. Small-medium: needs a post-reconnect
        read-back-and-compare, with one retry if it didn't stick.

      - [ ] **#2c** `CaptureCoordinator.start()` (`src/capture/capture_coordinator.py:32`)
        still has no try/except around `await source.start()` — one
        source's exception aborts starting every other source (concentrator,
        unrelated companions, everything). Confirmed still unfixed as of
        this pass. Small, standalone, fully scoped already: wrap in
        `try/except Exception` (re-raise `ImportError`), log-and-continue.
        Note upstream's version of this file also removed a `sources`
        property and `all_sources_running()` — check nothing else here
        (status LED?) depends on those before touching this file.

      - [ ] **#2d** Meshtastic `SerialCaptureSource.start()`
        (`src/capture/serial_source.py:445`) has **no retry/background-
        reconnect logic of its own at all** — a busy/wrong port just
        raises straight up, permanently, with nothing to pick it back up
        later short of a manual service restart. This is real and
        MeshCore-specific code doesn't have this problem: `meshcore_usb_source.py`
        already has a proven `_reconnect_until_connected()` +
        `_health_check_loop()` pattern for exactly this. #2d is porting
        that already-working pattern from our own MeshCore module to our
        own Meshtastic one, not porting anything from upstream at all.
        Medium effort — needs care since `SerialCaptureSource` also
        carries live radio-setter methods (`set_region`/`set_bluetooth`/
        `set_modem_preset`/etc.) that assume `self._interface` is real;
        a background retry loop needs those to fail gracefully while
        disconnected, same as MeshCore's `connected` gating already does.

      Companion rename, channel sync, contacts (data model), device info,
      and installed-firmware display are **confirmed already built and
      already have UI** — no further action on those. `#2a`/`#2c` are as
      small and mechanical as #4-#6 were. `#2b`/`#2d` are real but
      significantly smaller than the original "whole feature cluster"
      estimate — a session each, not a whole-cluster rebuild. None of
      this needs upstream's actual files at all; it's entirely
      independent work on our own already-existing implementation.

## High priority — confirmed real bugs, verified against our actual code

Went back and actually read our `meshtastic_firmware_routes.py`/
`meshcore_firmware_routes.py` line-by-line against each upstream fix commit
instead of leaving these as guesses. All three land — same bug, present
verbatim, in both of our firmware route files.

- [x] **#3** FIXED (scoped down from the original plan). No "esptool actually succeeded" check before claiming the
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
  - **Done, scoped down**: added the `success` check with its own failure
    branch (matching upstream's "Flash failed... restoring USB capture"
    messaging) in both `meshtastic_firmware_routes.py` and
    `meshcore_firmware_routes.py` (the latter also needed the BLE-flavor
    branch reordered so a failed BLE attempt still tries to restore the
    still-in-place old firmware instead of assuming BLE-firmware-shaped
    non-reconnect). Deliberately did **not** solve the `write-flash`/
    `write_flash` esptool-version question here -- `_stream_subprocess`
    already correctly captures any non-zero exit (wrong subcommand or
    otherwise) as `success=False`, so the honest-fail-UI fix covers that
    failure mode too without needing esptool-version detection. That
    detection work (if ever needed) naturally belongs with #1's resolver
    instead. Syntax-checked (`py_compile`); no existing test file to run
    (`tests/test_firmware_flash_routes.py` doesn't exist here) --
    live-verify by actually flashing while something else holds the port
    (or by naming a wrong `--chip`/temporarily breaking the cmd) to force
    a real esptool failure and confirm the UI now says "Flash failed",
    not "reconnected."

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
      **Live-confirmed** on the real Pi (`rakv2-meshpoint`), in the real
      venv, not just simulated locally: added
      `test_meshcore_name_resolves_from_sqlite_without_a_live_bus` to
      `tests/test_message_name_resolver.py` and ran
      `/opt/meshpoint/venv/bin/python -m unittest tests.test_message_name_resolver -v`
      — 5/5 pass, including the new one.

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
