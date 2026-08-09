# Band Plan (SX1302 Concentrator Channel Config)

Reference for the concentrator's predefined channel plans — one per supported
region, defined in [`src/hal/concentrator_config.py`](../src/hal/concentrator_config.py)
(`ConcentratorChannelPlan`). This is about the **onboard SX1302's own receive
channels** (what physical frequencies the concentrator listens on), not the
Meshtastic radio's own frequency-slot selection — see
[RADIO-CONFIG-EXPLAINED.md](RADIO-CONFIG-EXPLAINED.md) for that (a Meshtastic
node's own TX frequency, US slot map, custom frequency slots).

Two CSVs alongside this file, generated directly from the source (not
hand-transcribed) so they can't silently drift from the code:

- [`bandplan-channels.csv`](bandplan-channels.csv) — all 9 channels × 6
  regions (54 rows): frequency, bandwidth, spreading factor, protocol, RF
  chain, sync word, enabled.
- [`bandplan-sx1261-sweep.csv`](bandplan-sx1261-sweep.csv) — the SX1261
  companion chip's band-sweep range per region (see
  [SX1261 spectral scan](#sx1261-spectral-scan--band-sweep) below).

## Hardware shape

Every plan configures the same physical layout:

- **2 RF chains** (`radio_0_freq_hz`, `radio_1_freq_hz`) — analog front-end
  anchor frequencies.
- **8 multi-SF channels** (ch0–ch7) — 125 kHz BW, demodulate SF5–SF12
  simultaneously. Each is anchored to one of the two RF chains and must sit
  within **±490 kHz** of that chain's frequency (a hard SX1302 IF-engine
  limit).
- **1 single-SF channel** (ch8, the "service channel") — configurable
  bandwidth (125/250/500 kHz), one spreading factor at a time. This is the
  channel a region's Meshtastic default (e.g. LongFast, SF11/250 kHz) runs on.
- 1 FSK channel (not used by Meshpoint).

**RF chain assignment isn't fixed per channel index** — it's computed per
channel at configure time (`sx1302_wrapper.py`'s `_configure_if_channels()`):
`RF0 if channel_freq_hz <= radio_0_freq_hz + 500_000 else RF1`. In practice
this splits each region's 8 multi-SF channels roughly 6/2 or evenly across
the two chains depending on how close the primary sits to the band edge —
see the `rf_chain` column in
[`bandplan-channels.csv`](bandplan-channels.csv) for the exact split per
region rather than assuming a fixed ch0–3/ch4–7 divide.

## Supported regions

| Region | Default (primary/service channel) | Band limits |
|---|---|---|
| `US` | 906.875 MHz | 902.0 – 928.0 MHz |
| `EU_868` | 869.525 MHz | 863.0 – 870.0 MHz |
| `ANZ` | 919.875 MHz | 915.0 – 928.0 MHz |
| `IN` | 865.875 MHz | 865.0 – 867.0 MHz |
| `KR` | 922.875 MHz | 920.0 – 923.0 MHz |
| `SG_923` | 917.875 MHz | 917.0 – 925.0 MHz |

`ConcentratorChannelPlan.for_region(region)` picks the factory method below
for each. Selected automatically by `meshpoint setup`'s Region step, or via
`radio.region` in `local.yaml`.

---

## EU_868 — the odd one out: LoRaWAN + Meshtastic simultaneously

`eu868_lorawan()` — the only plan that isn't Meshtastic-only. Splits the two
RF chains between two protocols entirely, because the Meshtastic LongFast
channel (869.525 MHz) sits 1.025–1.625 MHz above the LoRaWAN uplink band —
too far for one RF chain's ±490 kHz IF window to cover both.

```
radio_0 = 868.300 MHz  →  ch0–ch4: LoRaWAN (5 TTN uplinks, sync word 0x34)
radio_1 = 869.525 MHz  →  ch8:     Meshtastic LongFast (sync word 0x2B)
                           ch5–ch7: disabled (nothing useful within
                                    ±490 kHz of radio_1)
```

| Channel | Name | Frequency | BW | SF | Protocol | RF chain | IF offset |
|---|---|---|---|---|---|---|---|
| ch0 | LoRaWAN 1 | 867.900 MHz | 125 kHz | SF7–12 | LoRaWAN | RF0 | −400 000 Hz |
| ch1 | LoRaWAN 2 | 868.100 MHz | 125 kHz | SF7–12 | LoRaWAN | RF0 | −200 000 Hz |
| ch2 | LoRaWAN 3 | 868.300 MHz | 125 kHz | SF7–12 | LoRaWAN | RF0 | 0 |
| ch3 | LoRaWAN 4 | 868.500 MHz | 125 kHz | SF7–12 | LoRaWAN | RF0 | +200 000 Hz |
| ch4 | LoRaWAN 5 | 868.700 MHz | 125 kHz | SF7–12 | LoRaWAN | RF0 | +400 000 Hz |
| ch5–ch7 | — | — | — | — | disabled | RF1 | — |
| ch8 | Meshtastic | 869.525 MHz | 250 kHz | SF11 | Meshtastic | RF1 | 0 |

TTN channels covered: 868.1, 868.3, 868.5 (the 3 mandatory ones) plus 867.9
and 868.7. Out of reach from this RF0 anchor: 867.1/867.3/867.5/867.7.

There's a second, unused EU868 factory, `meshtastic_eu868_default()`
(Meshtastic-only, 2 multi-SF channels at 869.4625/869.5875 MHz) — defined but
never wired into `for_region()`, which always returns `eu868_lorawan()` for
`EU_868`. Kept in the source as a documented alternative, not dead by
accident.

## EU_868 alternate — Reticulum instead of LoRaWAN (`radio.band_plan: "reticulum"`)

`eu868_reticulum()` — unlike `meshtastic_eu868_default()` above, this one
**is** live and selectable, via `radio.band_plan` (Configuration → Radio's
"Band plan" dropdown, EU_868-only). `from_radio_config()` checks `band_plan`
before anything else: `"reticulum"` returns this plan regardless of the
requested frequency/SF/BW.

The trade this makes explicit: ch0–ch7 share **one** sync-word register
across all 8 channels (`SX1302_REG_RX_TOP_FRAME_SYNCH0/1_SF7TO12_PEAK1/2_
POS_SF7TO12` in the real HAL register map — genuinely one shared front-end,
not 8 independent ones), so it's LoRaWAN *or* Reticulum on that register,
never both. `eu868_reticulum()` repoints it to
[Reticulum](https://reticulum.network/)'s own sync word `0x12` instead of
LoRaWAN's `0x34` — real LoRaWAN reception stops entirely while this is
selected. `radio_0`/`radio_1` both anchor to 869.525 MHz (same as ch8) since
Reticulum's real network parameters (869.463 MHz / SF8 / BW125 / CR5,
confirmed against `microReticulum_Firmware`'s own source, see
`extra/heltec_v4_reticulum_bron/`) sit only 62 kHz away — comfortably inside
the ±490 kHz IF window.

```
radio_0 = radio_1 = 869.525 MHz  →  ch0:     Reticulum (869.463 MHz, sync word 0x12)
                                     ch1–ch7: PAPA/DELTA/TWO/ECHO/MIKE/CHARLIE/SIERRA
                                              (spare, same 0x12 sync word)
                                     ch8:     Meshtastic LongFast (sync word 0x2B, unchanged)
```

ch1-ch7 are real, enabled, listening channels — not disabled placeholders —
but with no protocol of their own, free spectrum for a future custom
LoRa-chirp experiment. Names are placeholders (a phonetic-alphabet spelling
of the operator's own callsign, plus one extra) -- easy to rename, no other
code depends on the exact strings. The usable window here is genuinely
tight (869.035-870.000 MHz: capped on one side by the ±490 kHz IF limit, on
the other by EU_868's own 870.000 MHz region ceiling — 965 kHz total, with
ch0/ch8 already sitting in the middle of it), so the 7 spare frequencies
are hand-picked for real guard band rather than evenly auto-spaced: 4 fit
below the ch0/ch8 pair, 3 above.

| Channel | Name | Frequency | BW | SF | Protocol | RF chain | IF offset |
|---|---|---|---|---|---|---|---|
| ch0 | Reticulum | 869.463 MHz | 125 kHz | SF7–12 | Reticulum | RF0 | −62 000 Hz |
| ch1 | PAPA | 869.055 MHz | 125 kHz | SF7–12 | Papa | RF0 | −470 000 Hz |
| ch2 | DELTA | 869.155 MHz | 125 kHz | SF7–12 | Delta | RF0 | −370 000 Hz |
| ch3 | TWO | 869.255 MHz | 125 kHz | SF7–12 | Two | RF0 | −270 000 Hz |
| ch4 | ECHO | 869.355 MHz | 125 kHz | SF7–12 | Echo | RF0 | −170 000 Hz |
| ch5 | MIKE | 869.665 MHz | 125 kHz | SF7–12 | Mike | RF0 | +140 000 Hz |
| ch6 | CHARLIE | 869.765 MHz | 125 kHz | SF7–12 | Charlie | RF0 | +240 000 Hz |
| ch7 | SIERRA | 869.865 MHz | 125 kHz | SF7–12 | Sierra | RF0 | +340 000 Hz |
| ch8 | — | 869.525 MHz | 250 kHz | SF11 | Meshtastic | RF0 | 0 |

`multi_sf_protocol="auto"` here (unlike every other plan's plain string
literal) — instead of one fixed word for the whole ch0-7 group,
`config_routes.py`'s `_derive_channel_protocol()` uses each channel's own
`name`, lowercased, as its displayed protocol. That's what actually
distinguishes ch0 ("Reticulum") from a spare channel ("Papa", "Delta", ...)
in the Concentrator Channels table — "protocol" alone couldn't, since the
whole group shares one physical sync word. `eu868_lorawan()` stays on its
plain `"lorawan"` literal (not `"auto"`) — its 5 real channels don't need
individual protocol labels, only individual names for the table.

(Both RF chains anchor to the same frequency here, so `_configure_if_channels()`'s
`RF0 if freq_hz <= radio_0 + 500_000 else RF1` rule puts every channel on
RF0 — not a bug, just what happens when there's only one real anchor.)

Meshtastic (ch8, its own genuinely independent sync-word register) and Pager
(ch9, separate FSK silicon) are **unaffected either way** — this plan only
changes what's on the shared ch0-7 register. If a second custom LoRa-chirp
protocol gets built for one of the spare channels, it would need to
also use sync word `0x12` to be received here (fine for something you
design yourself — not for an existing protocol with its own fixed required
sync word).

**This only gets the concentrator physically receiving correctly-framed
Reticulum RF** — there is no `Protocol.RETICULUM` decoder in
`src/decode/packet_router.py`, so received frames aren't decoded/labeled as
Reticulum content on the dashboard yet. See
[Configuration → Radio](CONFIGURATION.md#eu868-band-plan--lorawan-vs-reticulum)
for the config reference.

## US, ANZ, IN, KR, SG_923 — Meshtastic-only wide-band plans

The other five regions have ≥2 MHz of usable band and use
`_build_wide_band_plan()`: 8 multi-SF channels spaced 200 kHz apart starting
700 kHz below the primary frequency, plus the single-SF service channel at
the region default.

| Region | Primary (ch8) | RF0 | RF1 | Multi-SF base (ch0) |
|---|---|---|---|---|
| `US` | 906.875 MHz | 906.800 MHz | 907.400 MHz | 906.200 MHz |
| `ANZ` | 919.875 MHz | 919.800 MHz | 920.400 MHz | 919.200 MHz |
| `IN` | 865.875 MHz | 865.800 MHz | 866.400 MHz | 865.200 MHz |
| `SG_923` | 917.875 MHz | 917.800 MHz | 918.400 MHz | 917.200 MHz |

Multi-SF channels for these four: `base + i × 200 kHz` for `i` in `0..7` (all
8 enabled).

**`KR` is hand-rolled, not via the shared helper** — its 3 MHz band is
narrower and the primary sits near the top, so multi-SF coverage is
deliberately limited to the lower/middle portion to stay within `radio_0`'s
IF range:

```
radio_0 = 922.400 MHz, radio_1 = 921.400 MHz
ch8 (primary) = 922.875 MHz
ch0–ch5 = 921.800 MHz + i × 200 kHz  (6 enabled channels)
ch6–ch7 = disabled
```

## Custom frequency / SF / BW (not a region default)

`ConcentratorChannelPlan.from_radio_config(region, frequency_mhz, sf, bw)` is
what actually runs at startup — it only returns the hardcoded region plan
above when the frequency **and** SF11/250 kHz (LongFast) match the region
default exactly. Any other combination (a custom slot, a different modem
preset) instead builds a plan around the requested frequency:

- **`EU_868`** (a "narrow band" region) → `_build_narrow_plan()`: single-SF
  channel at the custom frequency/SF/BW, only 2 multi-SF channels
  (±62.5 kHz), the remaining 6 disabled.
- **Everything else** → `_build_centered_plan()`: single-SF channel at the
  custom frequency, `radio_1` at `+800 kHz`, 8 multi-SF channels spread
  ±700 kHz around it in 200 kHz steps.

A frequency outside the region's band limits is rejected outright (`from_radio_config`
raises `ValueError`), unless it happens to exactly match *another* region's
default — in that case it logs a warning and silently falls back to the
configured region's own default instead of erroring.

---

## Sync words — why the 8 multi-SF channels rarely help with Meshtastic

The board is configured with `lorawan_public = True` unconditionally
(`sx1302_wrapper.py`, `_configure_board()`), which makes `lgw_start()`
program **all 8 multi-SF channels (ch0–ch7) to the public LoRaWAN sync word
`0x34`** — for every region, not just `EU_868`. Only the single-SF service
channel (ch8) gets overridden to Meshtastic's `0x2B` via a direct register
write (`set_syncword()`).

`ConcentratorCaptureSource.start()` now also calls a second, analogous
override, `set_multi_sf_syncword()`, right after `lgw_start()` — a no-op for
every plan except `eu868_reticulum()` (see above), which repoints ch0-ch7 to
`0x12`. Same register-write technique as `set_syncword()`, just the shared
multi-SF register pair (578/579) instead of the service channel's (932/933).

Practical effect: **only ch8 (the single primary/service channel) can ever
decode Meshtastic traffic**, on every region. The 8 multi-SF channels are
genuinely useful for `EU_868` (real TTN LoRaWAN uplinks live there) but on
the other five regions they're only listening for LoRaWAN-sync-word traffic
that may not exist in that band at all — they do **not** give extra coverage
of alternate Meshtastic presets or slots, despite what the unused
`meshtastic_eu868_default()` docstring implies. See
[`concentrator_source.py`](../src/capture/concentrator_source.py)'s
`_MESHTASTIC_EU868_FREQS_HZ` comment for the same note in code.

---

## SX1261 spectral scan & band sweep

The concentrator module's SX1261 companion chip (not a USB radio, not
present/enabled on every board) is a **separate radio used only for RF power
measurement, not packet demodulation**. It's what powers both RF Environment
features:

- **Noise floor** ([`src/api/telemetry/spectral_scan_service.py`](../src/api/telemetry/spectral_scan_service.py)) —
  a spectral scan every `radio.spectral_scan_interval_seconds` (default 60s)
  at whichever single frequency `radio.frequency_mhz` is currently configured
  to (the region default unless overridden). This is what feeds the noise
  floor sparkline continuously.
- **Band sweep** (the RF Environment page's spectrum chart) — a scan across
  *every* 100 kHz step spanning the region's full band, every
  `radio.spectrum_sweep_interval_seconds` (default 300s, `0` disables
  automatic sweeps though on-demand "Sweep now" still works). Uses the exact
  same `ConcentratorChannelPlan.band_limits_hz(region)` table as the channel
  plans above — `range(band_min, band_max + step, 100_000)`.

| Region | Sweep range | Step | Points |
|---|---|---|---|
| `US` | 902.0 – 928.0 MHz | 100 kHz | 261 |
| `EU_868` | 863.0 – 870.0 MHz | 100 kHz | 71 |
| `ANZ` | 915.0 – 928.0 MHz | 100 kHz | 131 |
| `IN` | 865.0 – 867.0 MHz | 100 kHz | 21 |
| `KR` | 920.0 – 923.0 MHz | 100 kHz | 31 |
| `SG_923` | 917.0 – 925.0 MHz | 100 kHz | 81 |

(Full data: [`bandplan-sx1261-sweep.csv`](bandplan-sx1261-sweep.csv). The
71-point `EU_868` figure matches the code's own comment in
`spectral_scan_service.py` — "a 71-point EU868 sweep takes a few seconds.")

**Requires `radio.sx1261_spi_path` to be set** (e.g. `/dev/spidev0.1`) —
without it, `_configure_sx1261_for_spectral_scan()` never runs
`lgw_sx1261_setconf`, `spectral_scan_supported` stays `False`, and *both*
features above are unavailable — noise floor falls back to a packet-derived
estimate (`rssi - snr` on received packets) instead, and the sweep can't run
at all. This is a single physical chip on the concentrator module, so
`sx1261_spi_path` isn't per-region — only the sweep's frequency *range*
changes with region, not whether the chip itself works.

Each scan (noise-floor or one point of a sweep) briefly pauses RX on the
scanned channel for ~50 ms — invisible against normal packet-loss variance
at these intervals, but why scans are serialized one-at-a-time rather than
run concurrently.

## A table you might see disagree: `src/radio/presets.py`

`src/radio/presets.py` has its own `REGION_DEFAULTS` dict (frequency
suggestions used elsewhere, e.g. default frequency for a serial/USB
Meshtastic stick) — it agrees with the concentrator's table for `US` and
`EU_868`, but **differs for `ANZ`, `IN`, `KR`, and `SG_923`**:

| Region | `concentrator_config.py` (this doc, authoritative for the concentrator) | `presets.py` `REGION_DEFAULTS` |
|---|---|---|
| `ANZ` | 919.875 MHz | 916.0 MHz |
| `IN` | 865.875 MHz | 865.4625 MHz |
| `KR` | 922.875 MHz | 921.9 MHz |
| `SG_923` | 917.875 MHz | 923.0 MHz |

[RADIO-CONFIG-EXPLAINED.md](RADIO-CONFIG-EXPLAINED.md#region)'s region table
matches `concentrator_config.py`, not `presets.py` — if you're cross-
referencing frequencies across the codebase and they don't match, this is
why. Not something this pass changed or fixed, just flagging it as found.

---

## See Also

- [RADIO-CONFIG-EXPLAINED.md](RADIO-CONFIG-EXPLAINED.md): Meshtastic's own
  frequency-slot selection (US slot map, custom slots, SF/BW/CR), separate
  from the concentrator's receive plan documented here
- [Configuration > Radio](CONFIGURATION.md#radio): full field reference
- [HARDWARE-MATRIX.md](HARDWARE-MATRIX.md): supported concentrator boards
