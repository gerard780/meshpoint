# Merge-todo: KMX415/meshpoint main vs ours

Compare: https://github.com/javastraat/meshpoint/compare/main...KMX415:meshpoint:main

- Common ancestor: `427f181` (2026-07-08, "Clarify one preset vs multi-SF RX in user-facing docs")
- Since then: KMX415 side = 54 commits (52 by KMX415, 2 by Sven-Christian Meyhoefer/Meyblaubaer), 102 files, +5533/-250
- Since then: our side = 485 commits, 466 files, +100473/-1877
- Full `git merge` of his 54 commits into our `main` produces **71 real conflicts** (verified with `git merge-tree`), mostly in the core serial/decode/routing pipeline and frontend — see "Serial/routing pipeline" cluster below, which is almost entirely convergent (we both built similar fixes independently).

Status legend: ✅ already covered on our side · 🆕 genuine gap, worth pulling in · ❓ unverified, needs a real diff to decide

Check items off as you confirm them (change `[ ]` to `[x]`) or add a note.

## Security (do this one first)

- [ ] 🆕 **`fdc5c1e`** — Require admin for config/message writes; redact PSKs for viewers.
  Adds `Depends(require_admin)` / `Depends(require_auth)` to `PUT /config/{transmit,identity,radio,channels,meshcore/channels}`, `POST /config/restart`, and `POST/DELETE` message routes; redacts `psk_b64` / MeshCore `key_hex` for non-admin `GET /config`.
  **Verified: our `src/api/routes/config_routes.py` has zero admin/role checks today** — sidebar-hiding is the only protection. Our auth infra (`src/api/auth/dependencies.py::require_admin/require_auth`, `src/api/auth/jwt_session.py::SessionClaims/ROLE_ADMIN`) already exists, so this should port cleanly. Commit is co-authored by us + says "From javastraat/meshpoint" — likely a patch we sent him that never landed back in our own main.
  Depends on new file `tests/auth_test_helpers.py` and `tests/test_viewer_write_lockdown.py` (both missing on our side).

## MQTT Map Report (genuine new feature)

- [ ] 🆕 **`12008bf`** — feat(mqtt): publish native Meshtastic map reports. New files `src/relay/map_report.py` (124 lines, missing on our side), hooks into `src/coordinator.py`, `src/config.py`, new `frontend/js/configuration/mqtt_card.js` UI, `docs/MQTT-AND-MESHRADAR.md`.
- [ ] 🆕 **`1fcb354`** — Require MQTT enabled for MapReport and harden publish RC check (depends on the above).
- [ ] 🆕 **`56f383b`** — Potential fix for pull request finding (small follow-up to the above, touches `src/coordinator.py`).

## Already covered — confirmed, no action needed

- [x] ✅ **`5cacaa2`** — Bound telemetry table growth with `max_telemetry_retained`. **We already have `max_telemetry_retained: 100000` in `config/default.yaml`.**
- [x] ✅ **`49d9ab0`** — Cache-bust dashboard JS/CSS URLs after restart. **We already have this** — `src/api/html_assets.py` docstring: "Cache-busting for the dashboard's static JS/CSS asset URLs."
- [x] ✅ **`8a907a5`** / **`f4f04d9`** — Downsample telemetry/signal history into time buckets. **We already have this**, our own implementation: `b10610a` "server-side downsampling for Repeater Trends and node-drawer telemetry charts, bounded regardless of history length." `src/storage/time_bucket.py` predates both forks (existed at common ancestor); both sides built bucketing on top of it independently.

## Serial/routing pipeline — convergent development, likely already covered (spot-checked one file)

We independently solved the same problems in `src/capture/serial_source.py` around the same time. Confirmed pairs so far:

- [ ] ❓ **`1fa123a`** Support multiple Meshtastic USB sticks via `capture.serial` list ↔ ours: `deda84b` "support multiple meshtastic usb sticks (capture.serial list, per-device labels)"
- [ ] ❓ **`1e04afc`** Route replies through the USB stick that heard the contact ↔ ours: `f6b2bcd` "replies route through the radio that heard the contact"
- [ ] ❓ **`0d224f9`** Route stick-local channel index by name, not OTA hash ↔ ours: `55950c8` "stop the 433 MHz stick's own channel-table index from being mistaken for a real OTA channel hash"
- [ ] ❓ **`4af1be6`** Drop serial self-telemetry polluting feed at -100 dBm ↔ ours: `db4de9f` "auto-detect a serial stick's own node id and drop its self-telemetry"
- [ ] ❓ **`0e2c6cd`** Stamp packets with stick LoRa freq/SF/BW from handshake ↔ ours: `77cdaa2` "serial capture reads the connected stick's real region/frequency/sf/bandwidth"

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
