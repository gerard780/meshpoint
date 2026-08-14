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
| **#7** | GPS-receiver port picker warning (Configuration → Serial) | ✅ Fixed | Small | `usb_classifier.py`, `serial_card.js` |
| **#8** | "Installed" firmware version callout (Configuration → Firmware) | ✅ Fixed | Small-medium | `*_firmware_routes.py`, `*_firmware_card.js` |
| **#9** | MeshCore DM contact-refresh has no throttle at all, hammers the bus on every incoming DM | ✅ Fixed | Small | `src/api/server.py:_refresh_mc_contacts` |
| — | `serial_config_routes.py` | ✅ Have it (bigger) | — | 457 vs 141 lines |
| — | `stats_chart_host.js` | ✅ Have it | — | credited to us |
| — | Stats-tab / stats-reporter fixes | ✅ Ahead of upstream | — | `stats_tab.js`, `stats_reporter.py` |
| — | `database.py` WAL + packet_id index | ✅ Have it | — | credited to us |
| — | URL-hash-before-scripts flash fix | ✅ Have it | — | `index.html` |
| **#1** | esptool venv-symlink resolver | ⏭️ Skipped — works today, any failure is loud not silent | — | `src/api/firmware/esptool_binary.py` (upstream-only) |
| — | MeshCore radio preset apply, rename, channel sync, contacts, device info | ✅ Already have it, already has UI | — | `meshcore_usb_source.py`, `meshcore_tx_client.py`, `meshcore_card.js` |
| **#2a** | Contact picker (`/api/messages/contacts`) hits live USB bus, no cache | ✅ Fixed | Small | `src/api/routes/messages.py:246` |
| **#2b** | `set_radio_params()` never verifies the preset actually stuck after reconnect | ✅ Fixed | Small-medium | `meshcore_usb_source.py:564`, `meshcore_tx_client.py:216` |
| **#2c** | `CaptureCoordinator.start()` still aborts all sources if one throws | ✅ Fixed | Small | `src/capture/capture_coordinator.py:32` |
| **#2d** | Meshtastic serial source has no retry/reconnect loop at all (unlike MeshCore's own, which already works) | ✅ Fixed | Medium | `src/capture/serial_source.py` |
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

      - [x] **#2a** FIXED. `GET /api/messages/contacts` (`src/api/routes/messages.py:246`)
        called `_meshcore_tx.get_contacts()` live, every single time the
        Messages tab's "new conversation" contact picker opened — no
        caching at all. Same bug class #6 already fixed, a different
        endpoint #6 didn't touch. **Fixed differently than #6, and for a
        real reason found while implementing it**: #6 could switch
        entirely to `node_repo` because every MeshCore node it needed a
        name for already had a `nodes` row. This endpoint can't do the
        same — `sync_meshcore_contacts_to_nodes()`
        (`src/api/meshcore_contacts.py`) only *updates* existing `nodes`
        rows with `protocol='meshcore'`, it never inserts new ones, so a
        companion contact with no corresponding `nodes` row yet (paired
        but never heard as a real mesh packet) would have silently
        vanished from the picker if this had stopped calling the live
        bus entirely. Added a short (10s) in-memory cache around the
        live call instead — bounds it to ~1 round trip per picker-open
        instead of one per render, without dropping contacts the
        node-repo-only approach would have missed. Verified the caching
        algorithm in isolation (3 rapid calls -> 1 real bus hit; correctly
        re-fetches once the TTL expires) since the real module's import
        chain needs more of FastAPI stubbed than's worth it on this
        Mac's no-venv setup. `py_compile` clean.

      - [x] **#2b** FIXED — and turned out to need real research, not just
        a guessed design. Went and actually read upstream's real fix
        (`e7a9297`/`bf82ea2`/`dcff8b0`, `src/transmit/meshcore_radio_apply.py`)
        instead of working from commit-message summaries alone, on the
        user's prompt to go check "if he fixed it." Two real corrections
        that came out of that:
        1. My first pass verified-and-retried after **every** successful
           `set_radio_params()` call. Upstream's actual root cause is
           narrower: a CLEAN success is trusted immediately (trigger
           reconnect, return — no wait), matching
           `meshcore_config_routes.py`'s existing `rebooting: true`
           contract (frontend already shows "reconnecting", not an
           instant refresh). Only a **timeout** gets the verify+retry
           treatment — that's the real, specific, live-observed bug
           ("Cross-band EU to USA/Canada was timing out and coming back
           still on EU"). Verifying unconditionally would have added a
           real regression: blocking every ordinary radio change, that
           already worked fine, for up to a minute.
        2. Found a more fundamental gap while checking: our own
           `send_set_radio_params()` (`meshcore_tx_client.py`) treated the
           companion's `no_event_received`/`timeout` ERROR reason as a
           **clean rejection**, not a timeout — meaning the exact
           silent-cross-band-reboot case this whole fix targets would
           never even have reached the recovery path at all, regardless
           of what got added in `meshcore_usb_source.py`. Fixed first, per
           upstream's `dcff8b0`.
        Also ported: pausing companion auto-fetch before sending
        `set_radio` so it owns the command channel (`bf82ea2`), and
        upstream's real live-observed timing constants (75s reconnect-
        verify window, not a guessed 30s -- "first reconnect attempt + DTR
        retry path observed ~30s on a RAK V2", so 75s leaves real margin
        for a second attempt).
        Real test added (`tests/test_meshcore_radio_params_verify.py`,
        pure asyncio + mocked `send_set_radio_params`/`_trigger_reconnect`/
        `get_radio_info`, no aiosqlite/FastAPI dependency) — 6/6 pass:
        clean success never triggers a verify read-back; clean rejection
        returns immediately; not-connected short-circuits; a timeout that
        reconnects with matching params verifies as success with no
        retry; a timeout that reconnects on the OLD params retries
        exactly once live and succeeds; never-reconnecting reports
        failure without hanging (verified with a shrunk timeout, not the
        real 75s). Also re-ran `tests/test_meshcore_tx_client.py` (37
        tests, already existing, exercises `send_set_radio_params`
        directly) to confirm the `no_event_received` reclassification
        didn't break anything already covered there — all 37 still pass.

        **Superseded, 2026-08-14, by a49ef60's exclusive-lease approach**
        (found on a second recheck of the compare, after #7/#8 landed).
        The shared-handle design directly above — trust a clean success,
        verify+retry-once over the source's own connection on a timeout
        — is exactly what upstream *originally* shipped too (their own
        `e7a9297`/`bf82ea2`/`dcff8b0`, what this fork ported). But their
        own later real-hardware testing found it still insufficient:
        `a49ef60`'s commit message states plainly, "Live shared-handle
        set_radio failed for USA/Canada with no_event_received while
        cold exclusive access worked on the test Pi." They replaced it
        with: detach the capture source entirely (cancel its health/
        reconnect tasks, close its live connection), open a brand-new
        EXCLUSIVE connection, set the radio, reboot, cold-reconnect,
        verify, then reattach the source's own reconnect machinery —
        matching the standalone `meshpoint meshcore-radio` CLI's cold
        path instead of reusing the live connection at all. This now
        runs on *every* `set_radio_params()` call once bound to a
        source, not just as a timeout fallback — there's no way to know
        in advance which changes will hit the ambiguous no-response case.
        **Ported as the new primary path**, replacing the shared-handle
        design above entirely (this fork's own architecture differs from
        upstream's: `set_radio_params()` is a method on
        `MeshcoreUsbCaptureSource` itself, not a separate `MeshCoreTxClient`
        bound to one "primary" source via `self._source` — the port
        keeps upstream's real detach/cold-connect/verify/reattach logic
        but drops the `getattr(source, ...)` indirection layer that
        exists only because of that structural difference). New
        `src/capture/meshcore_dtr.py` (`pulse_dtr_reset()`, extracted
        from the existing private `_pulse_dtr_reset` instance method so
        both the source's own reconnect loop and this new exclusive
        cold-path can use it without a bound instance). `_wait_connected()`/
        `_verify_radio_params_after_reconnect()` (the old shared-handle
        verify machinery) deleted as dead code once nothing called them
        anymore. Reused `send_set_radio_params()`/`read_radio_status()`
        as-is on the fresh exclusive connections rather than
        reimplementing their validation/timeout-reclassification/parsing
        logic a second time.
        **Real trade-off, deliberately not hidden**: unlike the old
        shared-handle path (near-instant on the common same-band case),
        this now ALWAYS pays the full detach → cold-connect → set →
        reboot-wait (8s) → cold-reconnect → verify sequence, typically
        ~15-20s, since there's no way to know ahead of time whether a
        given change needs the recovery path or not. Confirmed this
        fits the existing UI contract without any frontend change needed
        — `meshcore_card.js`'s save button already shows a disabled
        pending state and its own copy already says "this can take up
        to a minute."
        Real test added (`tests/test_meshcore_exclusive_radio_apply.py`,
        replacing the now-obsolete `test_meshcore_radio_params_verify.py`
        which tested behavior that no longer exists — deleted) — stubs
        the `meshcore` package into `sys.modules` (not installed on this
        Mac, needed since the new code does `from meshcore import
        MeshCore` internally) — 7/7 pass: not-connected short-circuits
        without touching the port; a clean success detaches, cold-
        applies, verifies, and reattaches (asserted exactly 2 cold
        connections — apply + verify — and a real reconnect task
        scheduled after); a timeout with a matching post-reconnect
        readback still succeeds; a timeout with a mismatched readback
        reports failure; a clean rejection (e.g. out-of-range) never
        attempts reboot/verify at all; an initial cold-connect handshake
        failure still reattaches (via the `finally` in `set_radio_params()`);
        a verify-phase reconnect that never comes back reports a timed-
        out failure instead of hanging. One real test-harness bug caught
        and fixed along the way: the reattach step schedules a real
        background reconnect task, which without cancelling pending
        tasks after each test would retry forever on real multi-second
        backoff sleeps once the test's own mocked connect patches had
        already gone out of scope — fixed by cancelling pending tasks in
        the test's `_run()` helper instead of awaiting them to
        completion, same fix shape `test_serial_source_reconnect.py`
        already used for the same class of problem.
        Also re-ran `tests/test_meshcore_tx_client.py` (44 tests, since
        `send_set_radio_params()`/`read_radio_status()` are reused
        unchanged by the new exclusive path) — all still pass, confirms
        nothing broke in the function this now leans on more heavily.
        `tests/test_meshcore_usb.py` (general reconnect/lifecycle) and
        `tests/test_meshcore_companion_radio_route.py` (the
        `/companion-radio` route, unaffected — still only reads
        `result.success`/`result.error`, same `SendResult` contract as
        before) both need `Crypto`/`fastapi` respectively, neither
        installed on this Mac — syntax-checked only, confirmed neither
        references the removed methods by name. **Not yet live-verified
        on real hardware** — this is the single most important item to
        verify live, since it's specifically meant to fix a cross-band
        (EU→USA/Canada) failure that could only ever be confirmed on
        real MeshCore companion hardware in the first place.

      - [x] **#2c** FIXED. `CaptureCoordinator.start()` (`src/capture/capture_coordinator.py:32`)
        had no try/except around `await source.start()` — one source's
        exception aborted starting every other source (concentrator,
        unrelated companions, everything). Wrapped in `try/except`
        (re-raises `ImportError`, logs and continues on anything else).
        Checked before touching the file: `.sources` (used by
        `main.py`/`server.py`'s startup banner) and
        `.all_sources_running()` (used by `server.py`'s health/status LED)
        are both real, live-used elsewhere — left both untouched, upstream
        removing them doesn't apply here. Real test added
        (`tests/test_capture_coordinator_soft_fail.py`, pure asyncio/stdlib,
        no aiosqlite/FastAPI dependency so it actually ran on this Mac,
        not just simulated) — 2/2 pass: one source raising `OSError`
        doesn't stop the other two from starting; `ImportError` still
        aborts as intended.

      - [x] **#2d** FIXED (scoped down from the original plan). Meshtastic
        `SerialCaptureSource.start()` (`src/capture/serial_source.py`) had
        **no retry/background-reconnect logic of its own at all** — a
        busy/wrong port raised straight out of `start()`, permanently,
        with nothing to pick it back up later short of a manual service
        restart.
        **Scoped down from MeshCore's full pattern, deliberately**: ported
        only the "initial connect failed → retry in the background"
        half of `meshcore_usb_source.py`'s
        `_reconnect_until_connected()` (same base/max backoff values, 5s
        → 60s), not its `_health_check_loop()` half or its DTR-reset-pulse
        recovery. Two reasons: (1) the DTR pulse is documented as a fix
        for a specific ESP32-S3 companion USB-CDC wedge state, confirmed
        live on that hardware — nothing suggests a Meshtastic USB stick's
        separate serial stack has the same failure mode, so copying it
        would be an unverified assumption dressed up as a port; (2) a
        live-connection-goes-stale health check is a genuinely separate
        problem from what this item actually described ("no retry
        logic... a busy/wrong port just raises... permanently") — that
        text is about the *startup* failure case specifically, and adding
        a full ongoing-health-check rebuild on top would have been scope
        creep beyond a "medium effort" item.
        Also had to solve a problem MeshCore's own port didn't have:
        `meshtastic.serial_interface.SerialInterface(...)` is a
        **blocking** call (`StreamInterface.__init__` synchronously calls
        `waitForConfig()` before returning) — unlike MeshCore's async
        connect. A naive retry loop calling that directly from the
        reconnect task would freeze the *entire* server's event loop
        (every other capture source, the dashboard API) for however long
        each failed attempt takes to time out. Fixed by running each
        connection attempt (`_blocking_connect()`, extracted from the old
        `start()` body) via `asyncio.to_thread(...)`, both on the initial
        attempt and every background retry — so a wedged port only blocks
        its own worker thread, never the event loop.
        `start()` now: sets `_running = True` unconditionally (mirroring
        MeshCore's own "is_running != connected" semantics), tries once
        via the new `_attempt_connect()` helper, and — only if that fails
        with something other than `ImportError` — schedules
        `_reconnect_until_connected()` as a background task instead of
        raising. `ImportError` (missing `meshtastic` package) still
        propagates and aborts, same as before: a missing dependency isn't
        something worth silently retrying forever. `stop()` now cancels
        any in-flight reconnect task cleanly before closing the interface.
        The existing live radio-setter methods
        (`set_region`/`set_bluetooth`/`set_modem_preset`/etc.) needed no
        changes — they already gate on `self._interface is None or not
        self._connected`, and both stay falsy for the entire time a
        reconnect is in progress, exactly the state they were already
        written to handle.
        Real test added (`tests/test_serial_source_reconnect.py`, pure
        asyncio/stdlib with `_blocking_connect` mocked out — no real
        `meshtastic`/`pubsub` hardware dependency, `pubsub` itself is
        actually installed here so that part runs for real) — 4/4 pass:
        a clean initial connect schedules no reconnect task; `ImportError`
        still raises out of `start()`; a flaky port that fails twice then
        succeeds gets picked up by the background loop without `start()`
        ever raising or blocking; `stop()` cancels an in-progress
        reconnect loop cleanly.

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

## Status

All real gaps found across every pass (#2a–#2d, #3, #4, #5, #6, #7, #8,
#9) are now fixed — each as a clean reimplementation matching this
fork's own conventions, not a merge/cherry-pick (709 commits of
independent history on our side made a real merge impractical). Only #1
(esptool venv-symlink resolver) remains un-ported, deliberately: the
current hardcoded-PATH lookup fails loudly, not silently, when it's
wrong.

#2b/#2d needed real research into upstream's actual commits rather than
guessed designs — see their entries above for what changed after
checking. #2b was actually re-opened and re-fixed a second time (see its
"Superseded" note) after a second, more thorough recheck of the same
compare found upstream's own fix had moved on further than what this
fork had originally ported. #9 was found the same recheck, independent
of anything from upstream (a real bug in this fork's own existing code,
not a porting gap) and fixed the same day.

Three passes over the same 28-commit compare total now (initial audit,
first recheck → #7/#8, second recheck → #2b superseded + #9) — each
later pass found real things the earlier one(s) missed by relying on
commit-message summaries or file-existence checks instead of full
diffs. That's now the standing approach for any future recheck of this
compare, not a one-off correction.

## #9: MeshCore DM contact-refresh has no throttle -- FIXED 2026-08-14

Found alongside #2b's supersession, while checking `f6afe0f`/`c12da51`
(upstream's later MeshCore-messaging hardening, on the same files this
fork already touched for #2a/#6) — not part of what got ported this
session, since the user chose the #2b port first. Real, live,
**independent of anything ported from upstream** — this is a bug in this
fork's own existing code, just one upstream happened to also hit and fix
around the same time.

`src/api/server.py`'s `_refresh_mc_contacts()` (inside
`_setup_message_interception`) calls the live `meshcore_tx.get_contacts()`
(a ~5-10s USB round trip that holds the companion's serial command
channel) on **every single incoming MeshCore DM**, completely
unthrottled — confirmed by reading the actual call site
(`_save_and_notify()`'s `if is_mc_dm: ... await _refresh_mc_contacts()`,
no rate-limit/cooldown anywhere around it). If several DMs arrive close
together (multiple contacts messaging around the same time, or one
contact sending a quick back-to-back burst), this fires the live bus
call repeatedly, which is exactly the "bus hammering" / TX-starvation
bug class this whole audit has been chasing elsewhere (#2a, #6, #2b).

Upstream's own fix for the identical problem (`f6afe0f`'s `server.py`
hunk) added a 60s minimum interval between refreshes
(`_MC_REFRESH_MIN_INTERVAL_S`, `time.monotonic()`-gated) — small,
self-contained, same shape as #7/#8. Worth porting on its own regardless
of whether the rest of `f6afe0f`/`c12da51`'s much larger command-
serialization architecture (`_cmd_lock`, a proper `MeshcoreContactCache`
class with soft-fail cooldown, `_pause_auto_fetch`/`_resume_auto_fetch`
wrapped around *every* companion command) ever gets ported — this fork
currently has none of that broader infrastructure at all, confirmed by
grepping `meshcore_tx_client.py` for `_cmd_lock`/`MeshcoreContactCache`/
`_pause_auto_fetch` (none found).

**Fixed, same day, scoped to just the narrow throttle** (not upstream's
whole broader `_cmd_lock`/`MeshcoreContactCache`/pause-auto-fetch-around-
every-command architecture -- that's a much bigger, separate rewrite this
fork's current `meshcore_tx_client.py` structure doesn't need just to fix
this specific bug, and nothing else in this audit surfaced a live symptom
that architecture would additionally fix here). Added
`_MC_CONTACT_REFRESH_MIN_INTERVAL_SECONDS = 60.0` and a module-level-
closure `_mc_contact_refresh_state = {"last": 0.0}` dict (same
`time.monotonic()`-gated pattern upstream's own `f6afe0f` uses) right
before `_refresh_mc_contacts()`'s existing `if not meshcore_tx or not
meshcore_tx.connected:` guard -- stamps the timestamp *before* the live
`get_contacts()` call, not after, so a failing/slow companion doesn't
get hammered by an immediate retry storm either, matching the same
"stamp even on failure" reasoning upstream's own `MeshcoreContactCache.
note_soft_fail()` uses (this fork doesn't have that class, but the
principle applies at this simpler level too).
**Verification**: `_refresh_mc_contacts()` is a closure defined inside
`_setup_message_interception()`, itself deeply embedded in `server.py`
(needs real `coord`/`message_repo`/`config` objects to even construct,
and the whole module needs `fastapi`, not installed on this Mac) --  no
existing test file covers this function at all, and building one just
for this fix would need a disproportionate amount of fake-dependency
scaffolding. Instead verified the exact throttle logic (identical
comparison/stamp/early-return shape) in an isolated throwaway script: a
burst of 5 simulated DMs within the cooldown window produces exactly 1
live refresh call; a 6th call after the cooldown expires is allowed
through. `py_compile` clean on `server.py`. **Not yet verified on the
real Pi** -- next real check is watching `sudo journalctl -u meshpoint`
for repeated MeshCore DMs and confirming "MC contact refresh skipped:
within cooldown" now appears between refreshes instead of a live fetch
every time.

## Recheck, 2026-08-14 — found #7 and #8 by reading full diffs, not just messages

User asked to recheck the compare after #2d landed, to confirm nothing was
missed. `git fetch upstream main` + `git log --oneline main..upstream/main`:
still the exact same 28 commits as the original pass — nothing new landed
upstream. Two real things surfaced anyway, both from reading full commit
diffs instead of trusting a commit-message-level summary from the original
pass (same methodology lesson as [[code-ahead-of-tracking]], applied a
second time here):

- **#2c/#2d validated, not just re-confirmed**: `602361a`'s real diff
  matches this fork's own independent #2d implementation almost exactly —
  same `asyncio.to_thread`-wrapped blocking connect, same background
  retry loop shape, even the *same* 5s/60s backoff constants (coincidence,
  or both sides converging on the obviously-right numbers for this
  problem — either way, good validation that the independent design was
  right). `capture_coordinator.py`'s half of that same commit is also a
  byte-for-byte shape match to this fork's own #2c.

- **[x] #8 FIXED, same day.** `96c5c71` ("Show installed companion
  firmware on Configuration → Firmware") is **Co-Authored-By this repo's
  own git identity** — meaning it was probably worked on jointly at some
  point — but the actual code was never in this repo's tree at all
  (`src/capture/serial_firmware_info.py` doesn't exist here, no
  `firmware_version` reference anywhere in either `*_firmware_routes.py`).
  The original audit's "Firmware-flash cards/routes (existence)" row only
  checked that the files existed, not full feature parity — same class of
  mistake the user caught earlier in this whole effort (checking presence,
  not content). Real, useful gap: no way to see a board's currently-
  installed firmware version before flashing over it.
  **Fixed as a lighter-weight adaptation, not a literal port** — this
  fork already had the underlying data both sides need, upstream's
  version had to build it from scratch:
  - Meshtastic: `firmware_version`/`hw_model` are already read into each
    `SerialCaptureSource`'s own `_radio_info` at connect
    (`serial_source.py::_read_radio_info`, pre-existing). New
    `GET /api/config/serial/firmware/installed` just reads
    `src.get_radio_info()` for each configured source — no new
    `SerialFirmwareInfoReader` module needed, unlike upstream's from-
    scratch build.
  - MeshCore: `get_device_info()` already existed per companion source
    (cached after its first DEVICE_INFO round trip on connect,
    pre-existing) — new `GET /api/config/meshcore/firmware/installed`
    just calls it. Deliberately built to report **every** configured
    companion (not just one "primary" one the way upstream's route did,
    which read from `_tx_service._meshcore_tx` instead of per-source) —
    this fork already supports multiple MeshCore companions
    (`meshcore_config_routes.py`'s companion list), so the Meshtastic-
    side route's "list of all configured devices" shape was extended to
    match on the MeshCore side too instead of copying upstream's single-
    device assumption.
  - Frontend: both `*_firmware_card.js` gained an "Installed" callout in
    the card header (version, hw model/build date, short port name),
    refreshed on mount and again right after a successful flash — same
    UX upstream built, adapted to this fork's existing card structure
    rather than copied wholesale. New `.cfg-firmware-installed*` CSS
    rules in `configuration.css`, additive alongside the existing
    `.cfg-firmware-board-field` rule (upstream's diff happened to delete-
    and-replace that block; kept ours intact and just added alongside).
  Real test added (`tests/test_firmware_installed_routes.py`) — needs
  FastAPI to import the route modules so only syntax-checked
  (`py_compile`) on this Mac per this repo's standing convention; the
  exact same logic was additionally verified assertion-by-assertion in a
  throwaway dependency-free script on this Mac (connected source reports
  its cached version; disconnected source reports empty without touching
  `get_radio_info()`/`get_device_info()` at all — confirms the MeshCore
  route never fires an unnecessary live query against a companion that
  isn't even connected; empty source list returns an empty list) — all
  assertions passed. `node --check` clean on both edited JS files, CSS
  brace-balance clean (128/128). CHANGELOG bullet added under `v0.8.0`.
  **Not yet live-verified on the Pi** — next step is confirming the
  callout shows a real version/hw-model for both a connected Meshtastic
  stick and a connected MeshCore companion, and that it updates after a
  real flash.

- **[x] #7 FIXED, 2026-08-14.** The other half of `602361a` (bundled with
  #2d in the same upstream commit, but a genuinely separate feature):
  Configuration → Serial's port picker warns when a selected port looks
  like a GPS receiver — useful because `gpsd` often holds a GPS port, so
  pinning one for Meshtastic serial capture fails in a confusing way
  (the #2d background-retry loop just quietly retries forever against a
  port that was never going to work, rather than raising once).
  This fork already had all the detection infrastructure
  (`usb_classifier.py`'s `PortClass.GPS_KNOWN`, `UsbPortClassifier`,
  already used by `should_skip_for_meshcore_probe`) — the gap was purely
  in not surfacing it on the port-picker's own data path:
  - `StablePortInfo` gained a `port_class` field (default `UNKNOWN`, so
    every existing caller stayed source-compatible — checked all 9 other
    call sites of `list_serial_ports_with_stable_paths()`, none construct
    `StablePortInfo` directly). New `serial_port_held_hint(port_class)`
    returns the warning text for `GPS_KNOWN`, `None` otherwise.
  - `GET /api/config/serial-ports` (`system_config_routes.py`) now
    includes `port_class`/`held_hint` per port.
  - `serial_card.js`: GPS-classified ports get a `GPS` tag appended in
    the datalist option label (same join-with-dash pattern the existing
    "used by ..." suffix already uses); a new amber hint line
    (`.cfg-field__hint--warn`, reuses the existing `--brand-amber` token)
    appears under the Serial port field when the currently-typed/picked
    value resolves to one; saving with a GPS port selected asks for
    confirmation via the app's existing `window.confirmModal` helper
    (same `_confirm()`-with-native-fallback pattern already used by
    `metrics_card.js`) instead of upstream's plain `window.confirm`.
  - `docs/COMMON-ERRORS.md` gained a new "Meshtastic USB serial" section
    covering this.
  Real tests added to the existing `tests/test_usb_classifier.py` (pure
  stdlib + `pyserial`, no FastAPI needed, ran directly on this Mac) — 4
  new tests (GPS_KNOWN/UNKNOWN hint text, `port_class` carried through
  `list_serial_ports_with_stable_paths()` for both a GPS and a non-GPS
  port) — full suite 19/19 pass, including all pre-existing tests
  unaffected by the new dataclass field. `py_compile` clean on the
  backend route change; `node --check` and CSS brace-balance
  (all files) clean on the frontend changes. CHANGELOG bullet added
  under `v0.8.0`. **Not yet live-verified on the Pi** — next step is
  plugging in a real (or simulated-VID) GPS stick and confirming the
  `[GPS]` tag/warning/confirm dialog actually appear on Configuration →
  Serial.

- **Checked and ruled out, not a gap**: `2833f8c` ("Treat MeshCore
  get_contacts None/timeout as empty instead of crashing") looked
  adjacent to #2a/#6 at a glance, so it got a full-diff check too. This
  fork's existing `MeshCoreTxClient.get_contacts()` already wraps the
  whole `result.payload` dereference (including the `AttributeError` a
  `None` result from the library's own internal timeout would raise) in
  a broad `except Exception:` that already returns `[]` — no crash exists
  in the current code. The only real difference is log verbosity
  (`.exception()` full traceback vs. upstream's dedicated `.warning()`
  for the specific None-timeout case) — not worth a change on its own.
