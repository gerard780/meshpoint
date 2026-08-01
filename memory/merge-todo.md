# Merge-todo: KMX415/meshpoint main vs ours

Compare: https://github.com/javastraat/meshpoint/compare/main...KMX415:meshpoint:main

- Common ancestor: `427f181` (2026-07-08, "Clarify one preset vs multi-SF RX in user-facing docs")
- Since then: KMX415 side = 54 commits (52 by KMX415, 2 by Sven-Christian Meyhoefer/Meyblaubaer), 102 files, +5533/-250
- Since then: our side = 485 commits, 466 files, +100473/-1877
- Full `git merge` of his 54 commits into our `main` produces **71 real conflicts** (verified with `git merge-tree`), mostly in the core serial/decode/routing pipeline and frontend — see "Serial/routing pipeline" cluster below, which is almost entirely convergent (we both built similar fixes independently).
- Cross-checked against GitHub's own compare API (`api.github.com/repos/javastraat/meshpoint/compare/main...KMX415:meshpoint:main`): confirms `status: diverged`, `ahead_by: 54`, `behind_by: 486` (matches our count), `102 files changed` on his side. No renames in the file list — everything flagged "added" there is a genuinely new file on his side since the fork point (used this to catch and fix two errors below: the time-bucket note, and calling out `serial_radio_handshake.py` explicitly).

Status legend: ✅ already covered on our side · 🆕 genuine gap, worth pulling in · ❓ unverified, needs a real diff to decide

Check items off as you confirm them (change `[ ]` to `[x]`) or add a note.

## Security

## MQTT Map Report (genuine new feature)

- [ ] 🆕 **`12008bf`** — feat(mqtt): publish native Meshtastic map reports. New files `src/relay/map_report.py` (124 lines, missing on our side), hooks into `src/coordinator.py`, `src/config.py`, new `frontend/js/configuration/mqtt_card.js` UI, `docs/MQTT-AND-MESHRADAR.md`.
- [ ] 🆕 **`1fcb354`** — Require MQTT enabled for MapReport and harden publish RC check (depends on the above).
- [ ] 🆕 **`56f383b`** — Potential fix for pull request finding (small follow-up to the above, touches `src/coordinator.py`).

## Already covered — confirmed, no action needed

- [x] ✅ **`fdc5c1e`** — Require admin for config/message writes; redact PSKs for viewers. **We already have this**, our own commit `0c1cd41` "security lockdown for viewer" (2026-07-06). Verified: our `config_routes.py` gates `GET /config` with `require_auth` and `PUT /transmit,/identity,/radio,/channels,/meshcore/channels,POST /restart` with `require_admin`, `messages.py` gates `send/advert/delete_conversation/delete_all` with `require_admin` — identical route coverage, and the `GET /config` docstring wording matches his commit verbatim ("Channel secrets... are only included for admins; viewer sessions get the same shape with blanked keys"), so this is almost certainly the same original patch (his commit says "From javastraat/meshpoint"). Correction: earlier in this doc this was wrongly listed as a 🆕 gap — that was a shell-substitution bug during verification, not a real gap. Verified `nodeinfo_routes.py` (`update_nodeinfo`, `send_nodeinfo_now`), `position_broadcast_routes.py` (`update_position_broadcast`), and `telemetry_broadcast_routes.py` (`update_telemetry_broadcast`) — all already gated with `Depends(require_admin)` on our side, matching his commit exactly. This item is fully closed, no gaps anywhere in it.
- [x] ✅ **`5cacaa2`** — Bound telemetry table growth with `max_telemetry_retained`. **We already have `max_telemetry_retained: 100000` in `config/default.yaml`.**
- [x] ✅ **`49d9ab0`** — Cache-bust dashboard JS/CSS URLs after restart. **We already have this** — `src/api/html_assets.py` docstring: "Cache-busting for the dashboard's static JS/CSS asset URLs."
- [x] ✅ **`8a907a5`** / **`f4f04d9`** — Downsample telemetry/signal history into time buckets. **We already have this**, our own implementation: `b10610a` "server-side downsampling for Repeater Trends and node-drawer telemetry charts, bounded regardless of history length." Correction: `src/storage/time_bucket.py` did **not** predate the fork (GitHub's compare API flags it "added" on his side, and it's confirmed absent at the merge-base) — both sides independently created a same-named module after the fork point to solve the same problem. Convergent development, not shared history.

## Serial/routing pipeline — convergent development, likely already covered (spot-checked one file)

We independently solved the same problems in `src/capture/serial_source.py` around the same time. Confirmed pairs so far:

- [ ] ❓ **`1fa123a`** Support multiple Meshtastic USB sticks via `capture.serial` list ↔ ours: `deda84b` "support multiple meshtastic usb sticks (capture.serial list, per-device labels)"
- [ ] ❓ **`1e04afc`** Route replies through the USB stick that heard the contact ↔ ours: `f6b2bcd` "replies route through the radio that heard the contact"
- [ ] ❓ **`0d224f9`** Route stick-local channel index by name, not OTA hash ↔ ours: `55950c8` "stop the 433 MHz stick's own channel-table index from being mistaken for a real OTA channel hash"
- [ ] ❓ **`4af1be6`** Drop serial self-telemetry polluting feed at -100 dBm ↔ ours: `db4de9f` "auto-detect a serial stick's own node id and drop its self-telemetry"
- [ ] ❓ **`0e2c6cd`** Stamp packets with stick LoRa freq/SF/BW from handshake ↔ ours: `77cdaa2` "serial capture reads the connected stick's real region/frequency/sf/bandwidth". His side factors this into a **new standalone file `src/capture/serial_radio_handshake.py` (confirmed missing on our side)** — worth a real diff to see if his handshake-parsing approach catches cases ours doesn't, even though the end goal (real freq/SF/BW instead of placeholders) is already met on our side.

Not yet individually compared (same file cluster, probably same story, needs a real diff before assuming covered):

- [ ] ❓ **`2dfd813`** Ignore blank serial rows so multi-stick save can't double-open a port
- [ ] ❓ **`3df2e8f`** Fix serial USB decode: reconstruct MeshPacket frames, use pre_decoded
- [ ] ❓ **`8982245`** Enable replies when remote channel name differs but PSK matches
- [ ] ❓ **`f71b18c`** Route unmapped channel hashes to their own conversation buckets
- [ ] ❓ **`22e5d52`** Tag packets with capture source name, surface band on nodes
- [ ] ❓ **`ab6a517`** Make channel message sender names clickable via `source_id`
- [ ] ❓ **`872e42d`** Fix MeshCore name cross-contamination and sticky conversation titles

## Updates page UX — probably have our own version, needs a look

We've touched `update_panel_controller.js` (12 commits since base), `release_notes_view.js` (2), `src/api/update/install_status.py` (7), `release_notes.py` (3) — so we likely built equivalent Updates-page UX independently, but his side adds standalone new files we don't have at all:

- [ ] ❓ **`1fa053f`** Unify Updates commits into one NEW-marked timeline — new files `frontend/js/settings/update_commit_timeline_view.js`, `update_incoming_view.js`, `update_remote_commits_view.js`, `frontend/css/update_commits.css` (all missing on our side)
- [ ] ❓ **`982411d`** Show latest origin commits on the Updates card
- [ ] ❓ **`2566748`** List incoming commit subjects when Updates is behind origin
- [ ] ❓ **`91cde6d`** Group release-notes preview under CHANGELOG category headings
- [ ] ❓ **`a3210f4`** Add full release-notes modal — new `frontend/css/update_release_notes_modal.css`
- [ ] ❓ **`95a79cb`** Fix awkward Updates status copy after a successful check

## Low priority / infra

- [ ] ❓ **`0e7518c`** Pin CI ruff to 0.15.22 after 0.16.0 flooded lint — cheap, worth just checking our CI ruff pin and matching if we're getting the same lint flood.
- Skip: `f3dcb740` (release rollup commit, no unique content), `cc8777a` (his own CHANGELOG draft, not applicable to our CHANGELOG).

## How to verify a ❓ item

```
git show <hash> -- <file>              # see what his commit actually did
git log --oneline <base>..origin/main -- <file>   # see our commits on the same file
git diff <base> origin/main -- <file>  # see how far we've diverged from the shared starting point
```
Base commit: `427f181d94c229ba723f738733394d177e22a681`
KMX415 head: `67bf74dd8eb6cd6dd101f29d7c02dcd9b76aaf6c`

## LAST ITEM — run only once every item above is checked off

Once every 🆕 gap is ported and every ❓ is resolved (either confirmed already-covered or pulled in), close out the "54 commits behind" relationship with a no-op merge — records his `main` as an ancestor without changing any files, since by then everything worth taking has already been taken deliberately, commit by commit above:

```
git fetch https://github.com/KMX415/meshpoint.git main
git merge -s ours FETCH_HEAD -m "merge: absorb KMX415/meshpoint main history — everything worth taking already ported per memory/merge-todo.md"
git push origin main
```

This rewrites shared history and pushes to `origin/main` — do not run without explicit go-ahead at the time, even if this file is fully green.
