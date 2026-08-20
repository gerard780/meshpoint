/*
  RF Environment Scanner -- Heltec WiFi LoRa32 V3 (ESP32-S3 + SX1262)

  A standalone handheld/deployable RF scanner. Forked from Meshpoint's
  rfenv_companion.ino (a second radio that reported ambient-RSSI
  histograms back to Meshpoint's dashboard over USB serial, working
  around the deployed RAK2287 concentrator having no SX1261 for a real
  hardware spectral scan) -- this version drops the Meshpoint tether
  entirely (no serial protocol, nothing polls it, nothing depends on a
  Python backend) and keeps only the actual scanning capability: an
  OLED+button standalone tool, plus its own independent WiFi web
  dashboard for the same functionality from a phone/laptop.

  ---------------------------------------------------------------------
  OLED (128x64 SSD1306, onboard) + PRG button (GPIO0, same physical
  button pager_client.ino uses) -- one screen, two gestures:

    Short press -- runs one band sweep (a discrete scan across
                   BAND_STEPS fixed frequencies spanning
                   BAND_START_MHZ..BAND_END_MHZ, picked by secrets.h's
                   ACTIVE_BAND -- see that file's own comment), and
                   draws median (solid line) + p95/peak (sparse dots)
                   -- the same statistic the web dashboard's Band
                   Spectrum card shows, just local and synchronous.
    Hold          -- (>= LONG_PRESS_MS) toggles CONTINUOUS mode: keeps
                   hopping across the same frequency plan in a loop,
                   redrawing a live bar-per-frequency RSSI view (one
                   raw instantaneous sample per hop, not the sweep's
                   multi-sample statistic) every hop, forever, until
                   held again -- at which point it drops back to the
                   single-sweep view above (running one fresh sweep
                   immediately, so the screen isn't left showing a
                   stale reading). The display does NOT auto-blank
                   while continuous mode is running -- see
                   DISPLAY_TIMEOUT_MS below.

  Boots straight into one sweep (no separate "waiting" screen -- there's
  nothing to wait for any more, nothing external ever has to poll this
  board before it's useful). Auto-blanks after DISPLAY_TIMEOUT_MS
  (10s) of no button activity, same wakeDisplay()/SSD1306_DISPLAYOFF
  pattern already proven in extra/pager_client.ino and
  extra/pocsag_companion.ino -- EXCEPT while continuous mode is active,
  which deliberately keeps the panel on for as long as you're watching
  it live (see loop()'s own auto-blank check).

  The first press while the screen is blanked ONLY wakes it (redraws
  whatever was last on screen, resets the idle timer) -- it does NOT
  also run a scan or toggle continuous mode in the same press. Only
  once the screen is already on does a press/hold do its normal thing.
  Same "don't act on the press that was really just meant to wake the
  screen up" reasoning a phone's lock screen already gets right.

  Hardware pins are the exact ones already verified on this same board
  in extra/pager_client/pager_client.ino -- copied, not re-derived.

  ---------------------------------------------------------------------
  WiFi / mDNS / OTA / web dashboard -- entirely optional (kept from the
  original Meshpoint-companion fork, since it's genuinely independent
  of the serial protocol that got removed -- it never talked to
  Meshpoint's backend either, just visually matched its dashboard
  theme). If secrets.h's WIFI_SSID is empty or still the placeholder,
  setupWifiOta() returns immediately and none of this runs -- the
  OLED+button scanner above never depends on any of it.

  When configured, this gives a second, independent way to use the same
  scanning capability the OLED already provides: a live RF-environment
  view (Status/Channel Histogram/Band Spectrum/WiFi Credentials cards,
  "Scan now"/"Sweep now" buttons) in a browser at
  http://rfenv-scanner-<band>.local -- useful e.g. hung somewhere out
  of reach and checked from a phone, where squinting at a 128x64 OLED
  isn't practical. Channel Histogram (single-frequency RSSI-level
  distribution, pick any frequency) only lives here, not on the OLED --
  there's no good way to type an arbitrary frequency with one button
  and no keypad, so that stays a web-only feature. ArduinoOTA lets
  firmware updates go out over WiFi instead of USB once configured.

  Cross-thread safety: AsyncWebServer's request/body callbacks run on
  AsyncTCP's own FreeRTOS task, not loop()'s thread -- loop() remains
  the only thread that ever touches `radio` (a web-triggered Scan/Sweep
  only stages a request via queueWebScan()/queueWebSweep(), which
  loop()'s checkWebScanPending()/checkWebSweepPending() actually run) or
  mutates webPassword/wifiSsid/wifiPass, all guarded by stateMutex --
  same discipline pocsag_companion.ino/pager_client.ino both already
  establish for their own web dashboards.

  Status: forked from a LIVE-CONFIRMED (histogram, sweep, OLED text)
  Meshpoint companion -- the underlying scan/sweep/RSSI-sampling code
  is proven on real hardware, but this specific single-screen/
  continuous-mode OLED rework is compile-verified only, not yet
  flashed/tested.
*/

#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>

#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#include <RadioLib.h>
#include <ArduinoJson.h> // v7.4.3 -- JsonDocument/deserializeJson v7 API

#include <WiFi.h>
#include <ESPmDNS.h>
#include <ArduinoOTA.h>
#include <AsyncTCP.h>
#include <ESPAsyncWebServer.h>
#include <freertos/semphr.h>
#include <Preferences.h>
// Gitignored -- WIFI_SSID/WIFI_PASSWORD/OTA_PASSWORD/WEB_PASSWORD AND
// ACTIVE_BAND (which physical unit's antenna this build is for -- see
// that file's own comment for why this has to be told, not detected,
// unlike ttn-heltec's V3/V4 board-revision auto-detection). Included
// this early, ahead of the BAND-derived constants below, specifically
// so ACTIVE_BAND is already known by the time they need it.
#include "secrets.h"

// ==== Band (see secrets.h's ACTIVE_BAND, not hand-edited here) ====
// Short band identifier, reported in the web dashboard's /api/status --
// same idea as pocsag_companion.ino's own BOARD_NAME_STR.
#if ACTIVE_BAND == BAND_70CM
  #define BAND_NAME_STR "70cm"
  #define DEFAULT_FREQ_MHZ 439.9875f
  #define BAND_START_MHZ 430.0f
  #define BAND_END_MHZ   440.0f
  // Pre-fills the web dashboard's Channel Histogram frequency input --
  // DAPNET/POCSAG's real German transmitter frequency (same constant
  // extra/pocsag_companion.ino uses), a genuinely fixed real-world
  // standard, not a guess.
  #define WEB_SCAN_DEFAULT_MHZ 439.9875f
#elif ACTIVE_BAND == BAND_EU868
  #define BAND_NAME_STR "eu868"
  #define DEFAULT_FREQ_MHZ 869.525f
  #define BAND_START_MHZ 863.0f
  #define BAND_END_MHZ   870.0f
  // Same shared Meshtastic/MeshCore-area anchor DEFAULT_FREQ_MHZ
  // already uses -- this firmware has no live knowledge of a
  // deployment's own actual MeshCore frequency (region/config-specific)
  // -- freely editable in the web UI either way.
  #define WEB_SCAN_DEFAULT_MHZ 869.525f
#else
  #error "secrets.h: ACTIVE_BAND must be set to BAND_EU868 or BAND_70CM"
#endif

#if ACTIVE_BAND == BAND_EU868
// This deployment's own known channels (see config/local.yaml on the
// Meshpoint side, radio.frequency_mhz/radio.pager_frequency_mhz) --
// LoRa (TTN's first default uplink channel of 8 - it hops, no single
// fixed frequency), MT/MC (Meshtastic + MeshCore share this one radio
// channel), Pager. Drawn as plain unlabeled lines in drawChartGrid() --
// text labels here got cramped/hard to read on a 128px OLED (see git
// history), so this is just a denser-dashed line than the generic scale
// ticks, distinct enough to read as "a specific marked channel" without
// needing to fit any text. EU868-only (~863-870MHz) -- meaningless on
// the 70cm build's 430-440MHz range, so this compiles out there entirely.
static const float KNOWN_FREQ_MARKERS[] = { 868.1f, 869.525f, 869.4625f };
#define NUM_KNOWN_FREQ_MARKERS (sizeof(KNOWN_FREQ_MARKERS) / sizeof(KNOWN_FREQ_MARKERS[0]))
#endif

// ---------- Hardware pins (Heltec WiFi LoRa32 V3) ----------
// Identical to extra/pager_client/pager_client.ino's own pin block.
#define LORA_SCK  9
#define LORA_MISO 11
#define LORA_MOSI 10
#define LORA_CS   8
#define LORA_RST  12
#define LORA_BUSY 13
#define LORA_DIO1 14

#define OLED_WIDTH  128
#define OLED_HEIGHT 64
#define OLED_SDA_PIN 17
#define OLED_SCL_PIN 18
#define OLED_RST_PIN 21
#define VEXT_PIN 36

#define BUTTON_GPIO 0

SX1262 radio = new Module(LORA_CS, LORA_DIO1, LORA_RST, LORA_BUSY);
Adafruit_SSD1306 display(OLED_WIDTH, OLED_HEIGHT, &Wire, OLED_RST_PIN);

// ---------- WiFi / mDNS / OTA / Preferences / web dashboard ----------
// Entirely optional -- if secrets.h's WIFI_SSID is empty or still the
// placeholder, setupWifiOta() returns immediately and none of this ever
// runs. When it IS configured, this gives a second, independent way to
// use the same scanning capability the OLED already provides: a live
// RF-environment view in a browser on the board's own WiFi -- useful
// e.g. hung somewhere out of reach and checked from a phone. Ported
// from pocsag_companion.ino's own WiFi/OTA/web-dashboard section --
// mechanism only, not its paging-specific content (no callsign, no
// page-send form/log -- this device has neither concept).
// Band-suffixed (not just "rfenv-companion") so two boards on the same
// LAN -- one EU868, one 70cm -- get distinct .local names instead of
// colliding: "rfenv-companion-eu868.local" / "rfenv-companion-70cm.local".
#define MDNS_HOSTNAME "rfenv-scanner-" BAND_NAME_STR
#define WIFI_CONNECT_TIMEOUT_MS 10000UL
#define PREFS_NAMESPACE "rfenv"
#define REBOOT_DELAY_MS 500UL

AsyncWebServer server(80);
Preferences prefs;
bool wifiConnected = false;
bool rebootRequested = false;
uint32_t rebootRequestedAt = 0;

// AsyncWebServer's request/body callbacks run on AsyncTCP's own FreeRTOS
// task, NOT loop()'s thread -- loop() remains the only thread that ever
// touches `radio` (runHistogramScan()/runBandSpectrumSweep() are only
// ever called from there, same rule pocsag_companion.ino enforces for
// its own sendPocsagAlpha()) or mutates the Strings below. A web
// handler never calls those functions directly -- it only stages a
// request (queueWebScan()/queueWebSweep(), same idea as POCSAG's own
// queueWebSend()/checkWebSendPending()) that loop() picks up and runs
// itself. String mutation across FreeRTOS tasks is a real
// heap-corruption risk on ESP32, not just a stale-read risk, so every
// access to webPassword/wifiSsid/wifiPass and the two pending-action
// flags below goes through this mutex.
SemaphoreHandle_t stateMutex;

String webPassword = WEB_PASSWORD;
String wifiSsid = WIFI_SSID;
String wifiPass = WIFI_PASSWORD;

bool webScanPending = false;
bool webSweepPending = false;
// 0 = use runLocalHistScan()'s own DEFAULT_FREQ_MHZ fallback; non-zero =
// scan at exactly this frequency instead, set by the web dashboard's
// own frequency input next to "Scan Now".
uint32_t webScanFrequencyHz = 0;

// ---------- Histogram bin scheme (see header comment) ----------
#define NB_LEVELS 35
#define LEVEL_MIN_DBM (-140)
#define LEVEL_STEP_DBM 3
// Top bin covers LEVEL_MIN_DBM + (NB_LEVELS-1)*LEVEL_STEP_DBM = -38 dBm
// and above -- samples stronger than that (e.g. a radio a few cm away)
// just saturate the last bucket rather than overflow the array.

#define SAMPLE_DELAY_MS 2
#define RETUNE_SETTLE_MS 5

// DEFAULT_FREQ_MHZ (used for radio.begin() and as the web dashboard's
// Channel Histogram fallback frequency) is derived from the BAND SELECT
// block near the top of the file.

// Web-triggered Channel Histogram scan -- more samples than a sweep
// point (BAND_SPECTRUM_NB_SCAN_PER_POINT below) since it's a single
// on-demand reading, not one of BAND_STEPS points in a time-budgeted sweep.
#define LOCAL_SCAN_NB_SCAN 400

// ---------- Standalone band scan (see header comment) ----------
// BAND_START_MHZ/BAND_END_MHZ are derived from the BAND SELECT block
// near the top of the file.
#define BAND_STEPS 32 // -> 4px-wide columns on a 128px-wide screen
#define BAND_REDRAW_EVERY_N_STEPS 1 // 32 steps is few enough to redraw every hop

static float bandRssi[BAND_STEPS];
static int bandIndex = 0;
static bool bandRssiValid[BAND_STEPS] = {false};

// ---------- Band sweep (single-shot view, see header comment) ----------
// Same BAND_STEPS frequency plan as the continuous-mode hop above, but
// a discrete snapshot with median/p95 per point instead of one raw
// instantaneous sample per hop -- run fresh on every press, not
// continuously.
#define BAND_SPECTRUM_NB_SCAN_PER_POINT 8
static float bandSpectrumMedian[BAND_STEPS];
static float bandSpectrumP95[BAND_STEPS];
static bool hasBandSpectrum = false;
static uint32_t bandSpectrumAtMs = 0; // millis() of the last completed sweep; 0 = never.
                                       // Lets the web dashboard tell a fresh Sweep-now
                                       // result apart from a stale one while polling.

// ---------- Display auto-blank (burn-in protection) ----------
// Same pattern and same 10s default already proven in
// extra/pager_client.ino and extra/pocsag_companion.ino. Continuous
// mode is exempt in practice, not by a special-cased check here -- see
// stepLiveScan()'s own comment for why.
#define DISPLAY_TIMEOUT_MS 10000
static bool displayOn = true;
static uint32_t lastDisplayActivity = 0;

void wakeDisplay() {
  if (!displayOn) {
    display.ssd1306_command(SSD1306_DISPLAYON);
    displayOn = true;
  }
  lastDisplayActivity = millis();
}

// ---------- Web-only channel histogram scan ----------
// Same 35-bin scan the OLED's own band sweep uses internally
// (runHistogramScan(), one call per sweep point) -- just a single
// arbitrary frequency instead, triggered from the web dashboard's own
// Channel Histogram card. OLED-only, not shown here since there's no
// good way to type an arbitrary frequency with one button and no
// keypad (see header comment) -- the web UI is the only place this
// result is ever rendered.
static uint16_t localHistCounts[NB_LEVELS];
static uint32_t localHistFrequencyHz = 0;
static bool hasLocalHist = false;
static uint32_t localHistAtMs = 0; // millis() of the last completed scan; 0 = never.
                                    // Same freshness-tracking role as bandSpectrumAtMs.

// The OLED has exactly one screen with two view modes -- see the header
// comment's "Short press"/"Hold" description.
static bool continuousMode = false;

// Forward declarations -- called before their definitions below (setup()/
// loop() aren't the only entry points here), and Arduino's auto-generated
// prototypes don't reliably cover every case (see pager_client.ino's own
// identical precedent for this).
void drawMainScreen();
bool runHistogramScan(uint32_t frequencyHz, uint16_t nbScan, uint16_t *counts);
float percentileDbm(uint16_t *counts, float p);
void runBandSpectrumSweep();
void setupWebServer();

// ---------- Button (short press = one sweep, hold = toggle continuous) ----------
static bool lastButtonReading = HIGH;
static bool buttonState = HIGH;
static uint32_t lastButtonChangeMs = 0;
static uint32_t buttonDownAtMs = 0;
static bool longPressFired = false;
#define DEBOUNCE_MS 30
#define LONG_PRESS_MS 700

// Shared by the web dashboard's frequency-input-driven scan
// (queueWebScan()/checkWebScanPending()) -- runLocalHistScanAt() for an
// explicit target frequency, runLocalHistScan() falling back to
// DEFAULT_FREQ_MHZ when the dashboard's own frequency input was empty.
void runLocalHistScanAt(uint32_t freqHz) {
  if (runHistogramScan(freqHz, LOCAL_SCAN_NB_SCAN, localHistCounts)) {
    localHistFrequencyHz = freqHz;
    hasLocalHist = true;
    localHistAtMs = millis();
  }
}

void runLocalHistScan() {
  runLocalHistScanAt((uint32_t)(DEFAULT_FREQ_MHZ * 1e6f));
}

// Sweeps the same BAND_STEPS frequency plan the live-scan view uses,
// but with a small per-point histogram (BAND_SPECTRUM_NB_SCAN_PER_POINT)
// instead of one raw sample, so median/p95 are real statistics rather
// than a single noisy reading -- ~32 * ~20ms =~ 0.6s, fine to block on
// a button press the same way the web-triggered histogram scan does.
void runBandSpectrumSweep() {
  static uint16_t counts[NB_LEVELS];
  for (int i = 0; i < BAND_STEPS; i++) {
    float freqMHz = BAND_START_MHZ + (BAND_END_MHZ - BAND_START_MHZ) * i / (float)(BAND_STEPS - 1);
    uint32_t freqHz = (uint32_t)(freqMHz * 1e6f);
    if (runHistogramScan(freqHz, BAND_SPECTRUM_NB_SCAN_PER_POINT, counts)) {
      bandSpectrumMedian[i] = percentileDbm(counts, 50.0f);
      bandSpectrumP95[i] = percentileDbm(counts, 95.0f);
    }
  }
  hasBandSpectrum = true;
  bandSpectrumAtMs = millis();
}

// ---------- WiFi/web state accessors (mutex-guarded, see stateMutex's
// own comment for why) ----------

String getWebPassword() {
  String p;
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  p = webPassword;
  xSemaphoreGive(stateMutex);
  return p;
}

void setWebPassword(const String &pw) {
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  webPassword = pw;
  xSemaphoreGive(stateMutex);
}

String getWifiSsid() {
  String s;
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  s = wifiSsid;
  xSemaphoreGive(stateMutex);
  return s;
}

String getWifiPassword() {
  String p;
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  p = wifiPass;
  xSemaphoreGive(stateMutex);
  return p;
}

// A WiFi-credential change here does NOT take effect until reboot --
// setupWifiOta() only ever runs once, from setup() -- same documented
// caveat as pocsag_companion.ino's own setWifiCredentials().
void setWifiCredentials(const String &ssid, const String &pass) {
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  wifiSsid = ssid;
  wifiPass = pass;
  xSemaphoreGive(stateMutex);
}

// ---------- Web-triggered scan/sweep staging (see stateMutex's own
// comment for why a web handler can't just call runHistogramScan()/
// runBandSpectrumSweep() directly) ----------

// freqHz: 0 = use runLocalHistScan()'s own default logic; non-zero =
// scan at exactly this frequency (the web dashboard's frequency input).
void queueWebScan(uint32_t freqHz) {
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  webScanPending = true;
  webScanFrequencyHz = freqHz;
  xSemaphoreGive(stateMutex);
}

void queueWebSweep() {
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  webSweepPending = true;
  xSemaphoreGive(stateMutex);
}

// Called every loop() pass. Cheap when nothing's pending (one mutex
// take/give), same as pocsag_companion.ino's own checkWebSendPending().
void checkWebScanPending() {
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  bool run = webScanPending;
  uint32_t freqHz = webScanFrequencyHz;
  webScanPending = false;
  webScanFrequencyHz = 0;
  xSemaphoreGive(stateMutex);
  if (!run) return;
  if (freqHz != 0) runLocalHistScanAt(freqHz);
  else runLocalHistScan();
}

void checkWebSweepPending() {
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  bool run = webSweepPending;
  webSweepPending = false;
  xSemaphoreGive(stateMutex);
  if (run) runBandSpectrumSweep();
}

void checkButton() {
  bool reading = digitalRead(BUTTON_GPIO);
  if (reading != lastButtonReading) {
    lastButtonChangeMs = millis();
  }
  if ((millis() - lastButtonChangeMs) > DEBOUNCE_MS && reading != buttonState) {
    buttonState = reading;
    if (buttonState == LOW) { // pressed (active LOW, INPUT_PULLUP)
      buttonDownAtMs = millis();
      longPressFired = false;

      // A press that arrives while the screen is blanked ONLY wakes it
      // back up (redraw whatever was already on screen, reset the idle
      // timer) - it does NOT also run a sweep or toggle continuous mode
      // in the same press, same "don't act on the press that was really
      // just meant to wake the screen" reasoning the header comment
      // documents. Marking longPressFired here suppresses both the
      // short-press branch below (on release) and the long-press branch
      // further down (even if this same press is held past
      // LONG_PRESS_MS) for the rest of this press.
      if (!displayOn) {
        wakeDisplay();
        drawMainScreen();
        longPressFired = true;
        lastButtonReading = reading;
        return;
      }
    } else { // released
      // Short press: run one fresh sweep and show it - but only in
      // single-shot mode. While continuous mode is running, a short
      // press does nothing; holding again is the only way to exit it
      // (see the long-press branch below).
      if (!longPressFired && !continuousMode) {
        runBandSpectrumSweep();
        drawMainScreen();
      }
    }
  }
  // Fire the long-press action once, as soon as the hold threshold is
  // crossed, rather than waiting for release -- more responsive, and
  // matches the header comment's "hold" wording literally.
  if (buttonState == LOW && !longPressFired &&
      (millis() - buttonDownAtMs) >= LONG_PRESS_MS) {
    longPressFired = true;
    continuousMode = !continuousMode;
    if (continuousMode) {
      // Start the hop cycle fresh rather than resuming mid-band from
      // wherever the last continuous session left off.
      bandIndex = 0;
      for (int i = 0; i < BAND_STEPS; i++) bandRssiValid[i] = false;
    } else {
      runBandSpectrumSweep(); // fresh snapshot, not the stale one from before continuous mode started
    }
    drawMainScreen();
  }
  lastButtonReading = reading;
}

// ---------- RSSI sampling ----------

// One instantaneous RSSI reading. getRSSI(false) reads the live value
// rather than the last-received-packet value -- valid in receive mode
// regardless of whether anything is actually demodulating, same
// principle the header comment describes for the real HAL's scan.
float sampleRssiDbm() {
  return radio.getRSSI(false);
}

void bucketSample(float rssiDbm, uint16_t *counts) {
  int idx = (int)roundf((rssiDbm - LEVEL_MIN_DBM) / (float)LEVEL_STEP_DBM);
  if (idx < 0) idx = 0;
  if (idx >= NB_LEVELS) idx = NB_LEVELS - 1;
  counts[idx]++;
}

// p-th percentile dBm reading from a 35-bin histogram -- mirrors
// SpectralScanResult.percentile() (src/hal/sx1302_spectral_scan.py) so
// the on-device floor/median readout matches what Meshpoint itself
// would compute from the same histogram. Bins are already in ascending
// level order by construction (LEVEL_MIN_DBM + i*LEVEL_STEP_DBM), so no
// sort needed here (that Python version sorts because the real HAL's
// own bin order isn't guaranteed -- this firmware's bins always are).
float percentileDbm(uint16_t *counts, float p) {
  uint32_t total = 0;
  for (int i = 0; i < NB_LEVELS; i++) total += counts[i];
  if (total == 0) return NAN;
  float target = total * (p / 100.0f);
  uint32_t cumulative = 0;
  for (int i = 0; i < NB_LEVELS; i++) {
    cumulative += counts[i];
    if (cumulative >= target) return LEVEL_MIN_DBM + i * LEVEL_STEP_DBM;
  }
  return LEVEL_MIN_DBM + (NB_LEVELS - 1) * LEVEL_STEP_DBM;
}

// Retunes to frequencyHz, takes nbScan RSSI samples, and buckets them
// into counts[NB_LEVELS]. Shared by the OLED's own band sweep
// (runBandSpectrumSweep(), one call per point) and the web dashboard's
// Channel Histogram scan (runLocalHistScanAt()) -- same sampling logic
// either way, only the caller (and what happens with the result) differs.
// Returns false (counts left untouched) if the radio can't retune.
bool runHistogramScan(uint32_t frequencyHz, uint16_t nbScan, uint16_t *counts) {
  float freqMHz = frequencyHz / 1e6f;
  int state = radio.setFrequency(freqMHz);
  if (state != RADIOLIB_ERR_NONE) {
    Serial.printf("[scan] setFrequency(%.4f) failed: %d\n", freqMHz, state);
    return false;
  }
  delay(RETUNE_SETTLE_MS);
  radio.startReceive();

  memset(counts, 0, sizeof(uint16_t) * NB_LEVELS);
  for (uint16_t i = 0; i < nbScan; i++) {
    bucketSample(sampleRssiDbm(), counts);
    delay(SAMPLE_DELAY_MS);
  }
  return true;
}

// ---------- Display ----------

// Consistent top bar for the screen's two modes ("LIVE SCAN"/"BAND
// SWEEP", see drawMainScreen()) -- so at a glance you know which one
// you're in. Right-aligns this unit's own IP address when WiFi is
// actually connected (nothing shown otherwise) -- lets you find the web
// dashboard's address straight off the OLED, no laptop already on the
// same network needed first. Titles here are short enough to leave room
// for a typical home-network IP; a long enough one could still run into
// the title -- this display is only 128px, there's no
// scrolling/truncation fallback for that edge case.
void drawHeader(const char *title) {
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println(title);

  if (wifiConnected) {
    String ip = WiFi.localIP().toString();
    int16_t x1, y1;
    uint16_t w, h;
    display.getTextBounds(ip, 0, 0, &x1, &y1, &w, &h);
    display.setCursor(OLED_WIDTH - w, 0);
    display.print(ip);
  }

  display.drawFastHLine(0, 9, OLED_WIDTH, SSD1306_WHITE);
}

// dBm -> pixel-row helper shared by the band-sweep chart's two series.
int bandSpectrumY(float dbm, int bottomY, int chartH) {
  const float rangeDbm = (float)(NB_LEVELS * LEVEL_STEP_DBM);
  float norm = (dbm - LEVEL_MIN_DBM) / rangeDbm;
  if (norm < 0) norm = 0;
  if (norm > 1) norm = 1;
  return bottomY - (int)(norm * chartH);
}

// Two reference dBm levels for the chart's horizontal gridlines --
// round numbers spanning a typical "strong" to "weak" range, not tied
// to any particular band.
#define DBM_GRID_1 -60
#define DBM_GRID_2 -100

// Vertical frequency gridlines, FREQ_GRID_POINTS of them, labeled with
// their MHz value. Generic bands get them evenly spaced across the
// FULL span including both edges (so the two end points land exactly
// on BAND_START_MHZ/BAND_END_MHZ), each rounded to the nearest whole
// MHz for a clean, readable label. EU868 uses a hand-picked set instead
// (863/865/867/870) tuned to sit clear of this deployment's own known
// channels (KNOWN_FREQ_MARKERS, below) -- the generic formula would
// land a tick at 868, which sits almost exactly on top of LoRa's 868.1
// (see git history: that's what made the two lines look like one).
#define FREQ_GRID_POINTS 4

// Shared reference grid for both of drawMainScreen()'s modes -- 2
// horizontal dashed lines at DBM_GRID_1/DBM_GRID_2 (left-labeled) and
// FREQ_GRID_LINES vertical dashed lines (bottom-labeled with their MHz
// value) -- lets a glance at the chart answer "roughly what level/
// frequency is this" instead of only showing relative shape. Dashed
// (drawn as scattered pixels, not solid lines) specifically so the
// gridlines stay visually distinct from the actual data line drawn on
// top of them afterward. Drawn first (background) -- callers draw their
// real data line/dots after calling this, so the data stays on top.
void drawChartGrid(int topY, int bottomY, int chartH) {
  display.setTextSize(1);

  int dbmLevels[2] = { DBM_GRID_1, DBM_GRID_2 };
  for (int i = 0; i < 2; i++) {
    int y = bandSpectrumY((float)dbmLevels[i], bottomY, chartH);
    for (int x = 0; x < OLED_WIDTH; x += 3) display.drawPixel(x, y, SSD1306_WHITE);
    display.setCursor(0, max(topY, y - 8));
    display.print(dbmLevels[i]);
  }

  // Scale ticks -- see FREQ_GRID_POINTS's own comment for why EU868
  // gets a hand-picked set instead of the generic evenly-spaced one.
  // The OLED is too small (128px) for labeled PER-CHANNEL markers to
  // read cleanly (see git history: that got cramped fast once two
  // known channels landed close enough together to need merging). The
  // web dashboard's Band Spectrum chart shows the real, labeled channel
  // markers instead (see that page's own drawLines()), where there's
  // actually room for them.
#if ACTIVE_BAND == BAND_EU868
  float freqTicks[FREQ_GRID_POINTS] = { 863.0f, 865.0f, 867.0f, 869.0f };
#else
  float freqTicks[FREQ_GRID_POINTS];
  for (int i = 0; i < FREQ_GRID_POINTS; i++) {
    freqTicks[i] = roundf(BAND_START_MHZ + (BAND_END_MHZ - BAND_START_MHZ) * i / (float)(FREQ_GRID_POINTS - 1));
  }
#endif
  for (int i = 0; i < FREQ_GRID_POINTS; i++) {
    float freqMhz = freqTicks[i];
    int x = (int)((freqMhz - BAND_START_MHZ) / (BAND_END_MHZ - BAND_START_MHZ) * OLED_WIDTH);
    for (int y = topY; y < bottomY; y += 3) display.drawPixel(x, y, SSD1306_WHITE);

    char buf[8];
    snprintf(buf, sizeof(buf), "%.0f", (double)freqMhz);
    int16_t x1, y1;
    uint16_t w, h;
    display.getTextBounds(buf, 0, 0, &x1, &y1, &w, &h);
    // Based on actual pixel position, not array index -- EU868's last
    // tick (869) no longer sits exactly at the band edge (870) the way
    // it used to, so "last point = right edge" stopped being true; this
    // clips against the real screen bounds instead, correct whether or
    // not a given tick happens to land exactly on BAND_START_MHZ/
    // BAND_END_MHZ.
    int lx = x - w / 2;
    if (lx < 0) lx = 0;
    if (lx + (int)w > OLED_WIDTH) lx = OLED_WIDTH - w;
    display.setCursor(lx, bottomY + 1);
    display.print(buf);
  }

#if ACTIVE_BAND == BAND_EU868
  // This deployment's own known channels (KNOWN_FREQ_MARKERS, see that
  // array's own comment) -- unlabeled on purpose (that's what didn't
  // work last time), drawn SOLID so they're unmistakably distinct from
  // the generic ticks' dashed lines above (a denser dash still read as
  // "basically the same line" next to a nearby tick, e.g. LoRa's 868.1
  // sitting right next to the generic 868 tick). MT/MC and Pager are
  // only 62.5kHz apart and will render as one line here -- correct, not
  // a bug, since they really are nearly the same frequency.
  for (size_t i = 0; i < NUM_KNOWN_FREQ_MARKERS; i++) {
    float mhz = KNOWN_FREQ_MARKERS[i];
    if (mhz < BAND_START_MHZ || mhz > BAND_END_MHZ) continue;
    int x = (int)((mhz - BAND_START_MHZ) / (BAND_END_MHZ - BAND_START_MHZ) * OLED_WIDTH);
    display.drawFastVLine(x, topY, bottomY - topY, SSD1306_WHITE);
  }
#endif
}

// The one OLED screen, in its two view modes (see continuousMode's own
// comment and the header comment's "Short press"/"Hold" description) --
// both a connected line + point markers via the shared bandSpectrumY()
// helper, drawn over drawChartGrid()'s reference gridlines, so the two
// modes read as visually the same kind of chart, not two different
// chart types:
//
//   continuousMode: one raw instantaneous sample per hop (bandRssi[],
//   filled by stepLiveScan()) -- a live, constantly-updating, noisier
//   line since each point is a single reading, not a statistic.
//   Marked with a dot at every point (there's only one series to show
//   here, unlike the sweep's median+p95 pair below).
//
//   !continuousMode: median (solid connected line) + p95/peak (sparse
//   dots at every other point, visually distinct from the median line
//   on a 1-bit display) from the last runBandSpectrumSweep() -- a real
//   multi-sample statistic across the same frequency plan, not just one
//   noisy reading, refreshed only on a fresh press/mode-exit rather
//   than continuously.
//
// No on-screen gesture reminder any more (dropped in favor of a taller
// chart + the grid's own axis labels below) -- short-press/hold are
// meant to become muscle memory quickly; see the header comment if
// you forget.
void drawMainScreen() {
  wakeDisplay(); // any real content update wakes the panel if blanked
                 // and resets the idle timer -- see loop()'s own auto-blank check.
  display.clearDisplay();

  const int topY = 11;
  const int bottomY = OLED_HEIGHT - 8; // leaves just enough room below for drawChartGrid()'s frequency labels
  const int colWidth = OLED_WIDTH / BAND_STEPS;
  const int chartH = bottomY - topY;

  if (continuousMode) {
    drawHeader("SCANNER");
    drawChartGrid(topY, bottomY, chartH);

    int prevX = -1, prevY = 0;
    for (int i = 0; i < BAND_STEPS; i++) {
      if (!bandRssiValid[i]) { prevX = -1; continue; } // don't bridge a line across a gap
      int x = i * colWidth + colWidth / 2;
      int y = bandSpectrumY(bandRssi[i], bottomY, chartH);
      if (prevX >= 0) {
        display.drawLine(prevX, prevY, x, y, SSD1306_WHITE);
      }
      display.drawPixel(x, y, SSD1306_WHITE);
      prevX = x;
      prevY = y;
    }
  } else {
    drawHeader("SWEEP");

    if (!hasBandSpectrum) {
      display.setCursor(0, 20);
      display.println("Sweeping...");
      display.display();
      return;
    }

    drawChartGrid(topY, bottomY, chartH);

    int prevX = -1, prevY = 0;
    for (int i = 0; i < BAND_STEPS; i++) {
      int x = i * colWidth + colWidth / 2;
      int yMed = bandSpectrumY(bandSpectrumMedian[i], bottomY, chartH);
      if (prevX >= 0) {
        display.drawLine(prevX, prevY, x, yMed, SSD1306_WHITE);
      }
      prevX = x;
      prevY = yMed;
      if (i % 2 == 0) {
        display.drawPixel(x, bandSpectrumY(bandSpectrumP95[i], bottomY, chartH), SSD1306_WHITE);
      }
    }
  }

  display.display();
}

// Same three-line centered layout as pager_client.ino's own
// drawBootScreen() (title / capcode / frequency) -- no capcode analog
// here, so title / "Scanner" / anchor frequency instead. Centering
// uses getTextBounds() (measures the real glyph box) rather than
// pager_client's manual "N chars * fixed glyph width" math -- more
// robust, and this file already had the helper in scope here.
void drawBootScreen() {
  display.clearDisplay();
  int16_t x1, y1;
  uint16_t w, h;

  display.setTextSize(2);
  const char *title = "RF Env";
  display.getTextBounds(title, 0, 0, &x1, &y1, &w, &h);
  display.setCursor((OLED_WIDTH - w) / 2, 8);
  display.println(title);

  display.setTextSize(1);
  const char *sub = "Scanner";
  display.getTextBounds(sub, 0, 0, &x1, &y1, &w, &h);
  display.setCursor((OLED_WIDTH - w) / 2, 30);
  display.println(sub);

  char freqBuf[24];
  snprintf(freqBuf, sizeof(freqBuf), "%.4f MHz", (double)DEFAULT_FREQ_MHZ);
  display.getTextBounds(freqBuf, 0, 0, &x1, &y1, &w, &h);
  display.setCursor((OLED_WIDTH - w) / 2, 46);
  display.println(freqBuf);

  display.display();
  delay(1200);
}

// Advances the live band scan by one step per call -- deliberately not
// a blocking sweep-then-draw loop, so loop() stays responsive to the
// button/web/OTA checks between every single-frequency hop. A no-op
// unless continuousMode is actually active -- no reason to keep
// retuning/sampling the radio in the background while the single-shot
// BAND SWEEP view is showing, which runs its own sweep on each press
// instead. Each redraw here goes through drawMainScreen(), which always
// wakeDisplay()s -- so as long as continuous mode keeps calling this
// faster than DISPLAY_TIMEOUT_MS, the screen never auto-blanks while
// it's running, exactly the "stays on while you're actively watching
// it" behavior the header comment describes.
void stepLiveScan() {
  if (!continuousMode) return;

  float freqMHz = BAND_START_MHZ + (BAND_END_MHZ - BAND_START_MHZ) * bandIndex / (float)(BAND_STEPS - 1);
  if (radio.setFrequency(freqMHz) == RADIOLIB_ERR_NONE) {
    delay(RETUNE_SETTLE_MS);
    radio.startReceive();
    // sampleRssiDbm() (getRSSI(false)) reads the SX126x's raw
    // instantaneous AGC-level RSSI over SPI - right after
    // startReceive() the AGC hasn't locked onto the current channel
    // yet, so a sample taken with zero delay reads a bogus, near-floor
    // value. runHistogramScan()'s own sweep never shows this because it
    // always takes several samples per point and uses their median -
    // one bad first sample gets outvoted by the later, AGC-settled
    // ones. A single-sample-per-hop view has no such statistical cover,
    // so it needs its own explicit settle delay here (same
    // SAMPLE_DELAY_MS gap runHistogramScan() already waits between its
    // own samples).
    delay(SAMPLE_DELAY_MS);
    bandRssi[bandIndex] = sampleRssiDbm();
    bandRssiValid[bandIndex] = true;
  }
  bandIndex = (bandIndex + 1) % BAND_STEPS;
  if (bandIndex % BAND_REDRAW_EVERY_N_STEPS == 0) {
    drawMainScreen();
  }
}

// ---------- Web dashboard ----------
// A small password-gated single-page UI served straight from flash (no
// filesystem, no external assets/fonts/CDN -- this device may only
// have LAN access, not real internet), styled to match Meshpoint's own
// dark dashboard theme -- same palette pocsag_companion.ino/pager_client
// .ino already hardcode for exactly this reason (both already converged
// on Meshpoint's own real frontend/css/dashboard.css tokens; copied
// here verbatim rather than re-derived, same idea those two files
// already established).
const char INDEX_HTML[] = R"HTMLPAGE(
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RF Environment Scanner</title>
<style>
  :root {
    --bg-primary: #0a0e17;
    --bg-card: #162033;
    --border: #233049;
    --text-primary: #e2e8f0;
    --text-secondary: #94a3b8;
    --text-muted: #64748b;
    --accent-green: #00e5a0;
    --accent-cyan: #06b6d4;
    --accent-purple: #a855f7;
    --accent-amber: #f59e0b;
    --accent-red: #ef4444;
    --radius: 8px;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg-primary);
    color: var(--text-primary);
    font-family: 'JetBrains Mono', 'Courier New', monospace;
    padding: 16px;
  }
  header { display:flex; align-items:center; justify-content:space-between; margin-bottom:16px; flex-wrap:wrap; gap:8px; }
  h1 { font-size: 18px; margin:0; color: var(--accent-cyan); letter-spacing: 0.5px; }
  .status { font-size:12px; color: var(--text-secondary); display:flex; gap:14px; align-items:center; }
  .dot { width:8px; height:8px; border-radius:50%; display:inline-block; margin-right:5px; }
  .dot.on { background: var(--accent-green); box-shadow:0 0 6px var(--accent-green); }
  .dot.off { background: var(--accent-red); }
  .grid { display:grid; grid-template-columns: repeat(2, 1fr); gap:16px; }
  @media (max-width: 700px) { .grid { grid-template-columns: 1fr; } }
  .card { background: var(--bg-card); border:1px solid var(--border); border-radius: var(--radius); padding:14px; }
  .card.wide { grid-column: 1 / -1; }
  .card h2 { font-size:13px; text-transform:uppercase; letter-spacing:1px; color: var(--text-secondary); margin:0 0 4px 0; }
  .card-desc { font-size:11px; color: var(--text-muted); margin:0 0 10px 0; line-height:1.4; }
  label { font-size:11px; color: var(--text-secondary); display:block; margin-bottom:4px; margin-top:10px; }
  input[type=text], input[type=password] {
    width:100%; background: var(--bg-primary); border:1px solid var(--border); color: var(--text-primary);
    padding:8px; border-radius:4px; font-family:inherit; font-size:13px;
  }
  button {
    margin-top:12px; width:100%; background: var(--accent-cyan); color:#04121a; border:none; border-radius:4px;
    padding:10px; font-family:inherit; font-weight:600; font-size:13px; cursor:pointer; letter-spacing:0.5px;
  }
  button:active { opacity:0.8; }
  button:disabled { opacity:0.5; cursor:default; }
  button.secondary { background: var(--bg-primary); color: var(--text-secondary); border:1px solid var(--border); }
  .kv { display:flex; justify-content:space-between; gap:8px; font-size:12px; padding:3px 0; border-bottom:1px solid rgba(255,255,255,0.04); }
  .kv span:first-child { color: var(--text-secondary); }
  .kv span:last-child { color: var(--text-primary); text-align:right; word-break:break-all; }
  #whoami { font-size:11px; color: var(--text-muted); margin: -4px 0 10px 0; }
  .result { font-size:12px; margin-top:8px; min-height:14px; }
  .result.ok { color: var(--accent-green); }
  .result.err { color: var(--accent-red); }
  .modal-overlay {
    position:fixed; inset:0; background: rgba(10,14,23,0.92); display:flex; align-items:center; justify-content:center; z-index:100;
  }
  .modal-overlay .card { width:280px; }
  .modal-overlay h2 { color: var(--accent-cyan); font-size:14px; }
  .hidden { display:none !important; }
  .chartwrap { position:relative; height:140px; margin-top:6px; }
  canvas { width:100%; height:100%; display:block; }
  .readout { display:flex; flex-wrap:wrap; gap:16px; font-size:12px; color: var(--text-secondary); margin-top:6px; }
  .readout b { color: var(--accent-cyan); }
  .readout .stale { color: var(--accent-amber); }
  .legend { display:flex; gap:14px; font-size:11px; color: var(--text-muted); margin-top:4px; }
  .legend i { display:inline-block; width:8px; height:8px; border-radius:2px; margin-right:4px; vertical-align:middle; }
</style>
</head>
<body>

<div id="authOverlay" class="modal-overlay">
  <div class="card">
    <h2>RF ENVIRONMENT SCANNER</h2>
    <div id="whoami">--</div>
    <label for="pw">Password</label>
    <input type="password" id="pw" autocomplete="off" spellcheck="false">
    <button onclick="tryLogin()">Unlock</button>
    <div class="result err" id="authErr"></div>
  </div>
</div>

<div id="app" class="hidden">
  <header>
    <h1>RF ENVIRONMENT SCANNER</h1>
    <div class="status">
      <span><span class="dot on" id="wifiDot"></span><span id="hostname">--</span></span>
    </div>
  </header>

  <div class="grid">
    <div class="card">
      <h2>Status</h2>
      <div class="kv"><span>Board</span><span id="stBoard">--</span></div>
      <div class="kv"><span>Band</span><span id="stBand">--</span></div>
      <div class="kv"><span>Uptime</span><span id="stUptime">--</span></div>
      <div class="kv"><span>SSID</span><span id="stSsid">--</span></div>
      <div class="kv"><span>IP</span><span id="stIp">--</span></div>
      <div class="kv"><span>WiFi RSSI</span><span id="stRssi">--</span></div>
      <div class="kv"><span>Free Heap</span><span id="stHeap">--</span></div>
    </div>

    <div class="card">
      <h2>WiFi Credentials</h2>
      <label for="wifiSsid">SSID</label>
      <input type="text" id="wifiSsid" autocomplete="off" spellcheck="false">
      <label for="wifiPass">Password</label>
      <input type="password" id="wifiPass" autocomplete="off" spellcheck="false">
      <button onclick="saveWifi()">Save (takes effect on reboot)</button>
      <button class="secondary" onclick="rebootNow()">Reboot Now</button>
      <div class="result" id="wifiResult"></div>
    </div>

    <div class="card wide">
      <h2>Channel Histogram</h2>
      <p class="card-desc">RSSI level distribution at ONE fixed frequency (shown below the
        chart) — not multiple channels. The x-axis is signal strength (dBm), not frequency;
        a tall bar means many samples landed at that noise/signal level. For a per-frequency
        view across a band, see Band Spectrum below instead.</p>
      <div class="chartwrap"><canvas id="histCanvas"></canvas></div>
      <div class="readout">
        <span>Floor <b id="histFloor">--</b> dBm</span>
        <span>Median <b id="histMedian">--</b> dBm</span>
        <span id="histAge">no scan yet</span>
      </div>
      <label for="scanFreq">Scan frequency (MHz)</label>
      <input type="text" id="scanFreq" inputmode="decimal" autocomplete="off" spellcheck="false" placeholder="e.g. 869.525">
      <button onclick="scanNow()">Scan Now</button>
      <div class="result" id="scanResult"></div>
    </div>

    <div class="card wide">
      <h2>Band Spectrum</h2>
      <p class="card-desc">Median and peak (p95) RSSI swept across the whole band (x-axis =
        frequency in MHz) — the dashed markers in Meshpoint's own Band Spectrum card show
        LoRaWAN/Meshtastic/MeshCore/Pager channel positions on a concentrator; this board has
        no channel plan of its own, so it's a plain frequency sweep with no markers.</p>
      <div class="chartwrap"><canvas id="sweepCanvas"></canvas></div>
      <div class="legend">
        <span><i style="background:#06b6d4"></i>Median</span>
        <span><i style="background:#a855f7"></i>Peak (p95)</span>
      </div>
      <div class="readout"><span id="sweepAge">no sweep yet</span></div>
      <button onclick="sweepNow()">Sweep Now</button>
      <div class="result" id="sweepResult"></div>
    </div>
  </div>
</div>

<script>
let pw = sessionStorage.getItem('rfenvPw') || '';

fetch('/api/whoami').then(r => r.json()).then(d => {
  document.getElementById('whoami').textContent = d.hostname + '.local · ' + d.band;
}).catch(() => {});

function authHeaders() { return { 'X-Auth-Password': pw }; }

async function checkAuthPw() {
  try {
    const r = await fetch('/api/status', { headers: authHeaders() });
    return r.ok;
  } catch (e) { return false; }
}

async function tryLogin() {
  pw = document.getElementById('pw').value;
  const ok = await checkAuthPw();
  if (ok) {
    sessionStorage.setItem('rfenvPw', pw);
    enterApp();
  } else {
    document.getElementById('authErr').textContent = 'Wrong password';
  }
}

function enterApp() {
  document.getElementById('authOverlay').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
  pollStatus();
  setInterval(pollStatus, 5000);
}

async function apiGet(path) {
  const r = await fetch(path, { headers: authHeaders() });
  if (r.status === 401) { sessionStorage.removeItem('rfenvPw'); location.reload(); throw new Error('unauthorized'); }
  return r.json();
}

async function apiPost(path, body) {
  const r = await fetch(path, {
    method: 'POST',
    headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
    body: JSON.stringify(body || {}),
  });
  if (r.status === 401) { sessionStorage.removeItem('rfenvPw'); location.reload(); throw new Error('unauthorized'); }
  return r.json();
}

function fmtAgo(s) {
  if (s < 60) return s + 's ago';
  if (s < 3600) return Math.floor(s / 60) + 'm ago';
  return Math.floor(s / 3600) + 'h ago';
}

function drawBars(canvas, counts, color) {
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = w * dpr; canvas.height = h * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  if (!counts || !counts.length) return;
  const maxCount = Math.max(1, ...counts);
  const colW = w / counts.length;
  for (let i = 0; i < counts.length; i++) {
    const bh = (counts[i] / maxCount) * (h - 4);
    if (bh < 1) continue;
    ctx.fillStyle = color;
    ctx.fillRect(i * colW, h - bh, Math.max(1, colW - 1), bh);
  }
}

// This deployment's own known channels (see config/local.yaml on the
// Meshpoint side, radio.frequency_mhz/radio.pager_frequency_mhz).
// Web-only - the OLED's own chart dropped per-channel markers in favor
// of generic evenly-spaced ticks (128px was too small for labeled
// markers to read cleanly, see drawChartGrid()'s own comment), but this
// canvas has plenty of room to show the WHOLE TTN EU868 channel plan
// (all 8 channels), not just one representative point. EU868 only - the
// web page is the same regardless of which band the firmware was
// actually built for, so drawLines() only draws these when the live
// /api/status response says band === 'eu868'.
// Colors distinguish the 8 (near-identical, all just "LoRa") LoRaWAN
// channels from the two channels that actually matter most to check on
// (MT/MC, Pager) -- amber for LoRa, accent-green/accent-red (same CSS
// tokens as this page's :root palette) for MT/MC/Pager respectively, so
// they stand out from the LoRa cluster at a glance instead of blending
// into "one more amber line".
const KNOWN_FREQ_MARKERS = [
  { mhz: 868.1, label: 'LoRa', color: '#f59e0b' }, { mhz: 868.3, label: 'LoRa', color: '#f59e0b' }, { mhz: 868.5, label: 'LoRa', color: '#f59e0b' },
  { mhz: 867.1, label: 'LoRa', color: '#f59e0b' }, { mhz: 867.3, label: 'LoRa', color: '#f59e0b' }, { mhz: 867.5, label: 'LoRa', color: '#f59e0b' },
  { mhz: 867.7, label: 'LoRa', color: '#f59e0b' }, { mhz: 867.9, label: 'LoRa', color: '#f59e0b' },
  { mhz: 869.525, label: 'MT/MC', color: '#00e5a0' },  // Meshtastic + MeshCore share this one radio channel
  { mhz: 869.4625, label: 'Pgr', color: '#ef4444' },   // POCSAG/DAPNET FSK channel
];

function drawLines(canvas, median, p95, startMhz, endMhz, band) {
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = w * dpr; canvas.height = h * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  if (!median || !median.length) return;
  const padBottom = 14; // room for the frequency axis labels below
  const chartH = h - padBottom;
  const all = median.concat(p95 || []);
  let lo = Math.min(...all), hi = Math.max(...all);
  if (hi - lo < 10) hi = lo + 10;
  const x = (i) => (i / (median.length - 1)) * w;
  const y = (v) => chartH - ((v - lo) / (hi - lo)) * (chartH - 4) - 2;

  // Frequency axis -- light gridlines + MHz labels, same idea as the
  // real dashboard's own Band Spectrum card (frontend/js/radio_spectrum_card.js)
  // -- without this there was no way to tell which x position was which
  // frequency, just a floating line.
  if (typeof startMhz === 'number' && typeof endMhz === 'number' && endMhz > startMhz) {
    const span = endMhz - startMhz;
    const step = span > 20 ? 5 : (span > 4 ? 1 : 0.5);
    ctx.font = '9px monospace';
    ctx.strokeStyle = 'rgba(148,163,184,0.12)';
    ctx.fillStyle = 'rgba(148,163,184,0.7)';
    ctx.lineWidth = 1;
    ctx.textAlign = 'center';
    for (let f = Math.ceil(startMhz / step) * step; f <= endMhz + 0.001; f += step) {
      const fx = ((f - startMhz) / span) * w;
      ctx.beginPath();
      ctx.moveTo(fx, 0);
      ctx.lineTo(fx, chartH);
      ctx.stroke();
      ctx.fillText(step >= 1 ? f.toFixed(0) : f.toFixed(1), Math.min(Math.max(fx, 12), w - 12), h - 3);
    }

    // Known-channel markers -- colored (see KNOWN_FREQ_MARKERS's own
    // comment), drawn distinctly from the faint gray scale gridlines
    // above so they read as "your specific channels", not just more
    // scale reference. One line per actual channel frequency (so all 8
    // LoRaWAN channels are genuinely all there), but labels get grouped
    // by pixel-proximity + text so adjacent same-label channels and
    // near-identical frequencies (MT/MC and Pager are only 62.5kHz
    // apart) don't stack into unreadable overlapping text.
    if (band === 'eu868') {
      const positioned = KNOWN_FREQ_MARKERS
        .filter(m => m.mhz >= startMhz && m.mhz <= endMhz)
        .map(m => ({ x: ((m.mhz - startMhz) / span) * w, label: m.label, color: m.color }))
        .sort((a, b) => a.x - b.x);

      ctx.lineWidth = 1;
      positioned.forEach(m => {
        ctx.strokeStyle = m.color;
        ctx.beginPath();
        ctx.moveTo(m.x, 0);
        ctx.lineTo(m.x, chartH);
        ctx.stroke();
      });

      // A group's label is drawn in its marker's own color when every
      // marker merged into it shares one (e.g. a cluster of LoRa
      // channels); mixed-color groups (MT/MC merging with Pager at a
      // narrow enough canvas width) fall back to a neutral color
      // instead of arbitrarily picking one of theirs.
      const labelGroups = [];
      positioned.forEach(m => {
        const lastGroup = labelGroups[labelGroups.length - 1];
        if (lastGroup && Math.abs(lastGroup.x - m.x) <= 10) {
          if (!lastGroup.labels.includes(m.label)) lastGroup.labels.push(m.label);
          if (lastGroup.color !== m.color) lastGroup.color = null;
        } else {
          labelGroups.push({ x: m.x, labels: [m.label], color: m.color });
        }
      });
      labelGroups.forEach(g => {
        ctx.fillStyle = g.color || 'rgba(226,232,240,0.9)';
        ctx.fillText(g.labels.join('/'), Math.min(Math.max(g.x, 16), w - 16), 10);
      });
    }
  }

  if (p95 && p95.length) {
    ctx.strokeStyle = '#a855f7';
    ctx.lineWidth = 1;
    ctx.beginPath();
    p95.forEach((v, i) => { i === 0 ? ctx.moveTo(x(i), y(v)) : ctx.lineTo(x(i), y(v)); });
    ctx.stroke();
  }
  ctx.strokeStyle = '#06b6d4';
  ctx.lineWidth = 2;
  ctx.beginPath();
  median.forEach((v, i) => { i === 0 ? ctx.moveTo(x(i), y(v)) : ctx.lineTo(x(i), y(v)); });
  ctx.stroke();
}

let scanFreqPrefilled = false;

async function pollStatus() {
  let d;
  try { d = await apiGet('/api/status'); } catch (e) { return null; }

  if (!scanFreqPrefilled && d.web_scan_default_mhz) {
    const freqInput = document.getElementById('scanFreq');
    if (freqInput && !freqInput.value) freqInput.value = d.web_scan_default_mhz;
    scanFreqPrefilled = true;
  }

  document.getElementById('hostname').textContent = d.hostname + '.local';

  document.getElementById('stBoard').textContent = d.board;
  document.getElementById('stBand').textContent = d.band;
  document.getElementById('stUptime').textContent = fmtAgo(Math.floor(d.uptime_ms / 1000));
  document.getElementById('stSsid').textContent = d.wifi.ssid;
  document.getElementById('stIp').textContent = d.wifi.ip;
  document.getElementById('stRssi').textContent = d.wifi.rssi + ' dBm';
  document.getElementById('stHeap').textContent = Math.round(d.free_heap / 1024) + ' KB';

  if (d.hist.has) {
    drawBars(document.getElementById('histCanvas'), d.hist.counts, '#06b6d4');
    document.getElementById('histFloor').textContent = d.hist.floor_dbm;
    document.getElementById('histMedian').textContent = d.hist.median_dbm;
    const histAge = document.getElementById('histAge');
    histAge.textContent = fmtAgo(d.hist.age_s) + ' @ ' + (d.hist.frequency_hz / 1e6).toFixed(3) + ' MHz';
    histAge.className = d.hist.age_s > 300 ? 'stale' : '';
  }
  if (d.sweep.has) {
    drawLines(document.getElementById('sweepCanvas'), d.sweep.median, d.sweep.p95, d.sweep.start_mhz, d.sweep.end_mhz, d.band);
    const sweepAge = document.getElementById('sweepAge');
    sweepAge.textContent = fmtAgo(d.sweep.age_s) + ' · ' + d.sweep.start_mhz + '-' + d.sweep.end_mhz + ' MHz';
    sweepAge.className = d.sweep.age_s > 300 ? 'stale' : '';
  }
  return d;
}

// Shared by scanNow()/sweepNow(): posts the trigger, then polls until
// the relevant result's age_s comes back genuinely fresh (not just a
// fire-and-forget single re-poll, which previously left "Scanning…"/
// "Sweeping…" stuck on screen forever even once the real result had
// long since landed -- nothing was ever clearing it). Gives up after
// maxTries (12s @ 1s each) as a fallback if something's actually stuck.
async function runAndAwaitFresh(triggerUrl, resultEl, verb, hasFreshResult, body) {
  resultEl.className = 'result ok';
  resultEl.textContent = verb + '…';
  try {
    await apiPost(triggerUrl, body);
  } catch (e) {
    resultEl.className = 'result err';
    resultEl.textContent = 'Failed';
    return;
  }
  let tries = 0;
  const timer = setInterval(async () => {
    tries += 1;
    const d = await pollStatus();
    const fresh = d && hasFreshResult(d);
    if (fresh || tries >= 12) {
      clearInterval(timer);
      resultEl.textContent = fresh ? 'Done.' : 'Still running? refresh the page to check.';
    }
  }, 1000);
}

function scanNow() {
  const freqInput = document.getElementById('scanFreq');
  const mhz = freqInput ? parseFloat(freqInput.value) : NaN;
  const body = (!isNaN(mhz) && mhz > 0) ? { frequency_mhz: mhz } : {};
  runAndAwaitFresh('/api/scan', document.getElementById('scanResult'), 'Scanning',
    (d) => d.hist.has && d.hist.age_s <= 2, body);
}

function sweepNow() {
  runAndAwaitFresh('/api/sweep', document.getElementById('sweepResult'), 'Sweeping',
    (d) => d.sweep.has && d.sweep.age_s <= 2);
}

async function saveWifi() {
  const r = document.getElementById('wifiResult');
  const ssid = document.getElementById('wifiSsid').value;
  const password = document.getElementById('wifiPass').value;
  try {
    await apiPost('/api/wifi', { ssid, password });
    r.className = 'result ok'; r.textContent = 'Saved — reboot to apply.';
  } catch (e) { r.className = 'result err'; r.textContent = 'Failed'; }
}

async function rebootNow() {
  const r = document.getElementById('wifiResult');
  try { await apiPost('/api/reboot'); } catch (e) {}
  r.className = 'result ok'; r.textContent = 'Rebooting…';
}
</script>
</body>
</html>
)HTMLPAGE";

bool checkAuth(AsyncWebServerRequest *request) {
  if (!request->hasHeader("X-Auth-Password") ||
      request->getHeader("X-Auth-Password")->value() != getWebPassword()) {
    request->send(401, "application/json", "{\"ok\":false,\"error\":\"unauthorized\"}");
    return false;
  }
  return true;
}

void setupWebServer() {
  server.on("/", HTTP_GET, [](AsyncWebServerRequest *request) {
    request->send(200, "text/html", INDEX_HTML);
  });

  // Unauthenticated -- lets the device be told apart at a glance before
  // a password is even entered. Neither field is sensitive: hostname is
  // already broadcast in the clear via mDNS anyway, band is a firmware
  // build choice, not a secret. Same reasoning pocsag_companion.ino's
  // own unauthenticated /api/whoami gives.
  server.on("/api/whoami", HTTP_GET, [](AsyncWebServerRequest *request) {
    JsonDocument doc;
    doc["hostname"] = MDNS_HOSTNAME;
    doc["band"] = BAND_NAME_STR;
    String out;
    serializeJson(doc, out);
    request->send(200, "application/json", out);
  });

  server.on("/api/status", HTTP_GET, [](AsyncWebServerRequest *request) {
    if (!checkAuth(request)) return;
    JsonDocument doc;
    doc["hostname"] = MDNS_HOSTNAME;
    doc["board"] = "heltec_v3_rfenv";
    doc["band"] = BAND_NAME_STR;
    doc["web_scan_default_mhz"] = WEB_SCAN_DEFAULT_MHZ;
    doc["uptime_ms"] = millis();
    doc["free_heap"] = ESP.getFreeHeap();

    JsonObject wifi = doc["wifi"].to<JsonObject>();
    wifi["ssid"] = WiFi.SSID();
    wifi["ip"] = WiFi.localIP().toString();
    wifi["rssi"] = WiFi.RSSI();

    JsonObject hist = doc["hist"].to<JsonObject>();
    hist["has"] = hasLocalHist;
    if (hasLocalHist) {
      hist["frequency_hz"] = localHistFrequencyHz;
      hist["floor_dbm"] = (int)percentileDbm(localHistCounts, 10.0f);
      hist["median_dbm"] = (int)percentileDbm(localHistCounts, 50.0f);
      hist["age_s"] = (millis() - localHistAtMs) / 1000;
      JsonArray counts = hist["counts"].to<JsonArray>();
      for (int i = 0; i < NB_LEVELS; i++) counts.add(localHistCounts[i]);
    }

    JsonObject sweep = doc["sweep"].to<JsonObject>();
    sweep["has"] = hasBandSpectrum;
    if (hasBandSpectrum) {
      sweep["start_mhz"] = BAND_START_MHZ;
      sweep["end_mhz"] = BAND_END_MHZ;
      sweep["age_s"] = (millis() - bandSpectrumAtMs) / 1000;
      JsonArray med = sweep["median"].to<JsonArray>();
      JsonArray p95 = sweep["p95"].to<JsonArray>();
      for (int i = 0; i < BAND_STEPS; i++) {
        med.add(bandSpectrumMedian[i]);
        p95.add(bandSpectrumP95[i]);
      }
    }

    String out;
    serializeJson(doc, out);
    request->send(200, "application/json", out);
  });

  // Neither of these touches `radio` directly -- they only stage a
  // request for loop() to run (see queueWebScan()/queueWebSweep()'s own
  // comment for why). /api/scan takes an optional JSON body
  // ({"frequency_mhz": ...}, the dashboard's frequency input) -- same
  // request/body-callback split AsyncWebServer needs for a POST body,
  // matching /api/wifi below. An absent/zero/invalid frequency_mhz
  // falls back to runLocalHistScan()'s own default-frequency logic.
  server.on("/api/scan", HTTP_POST, [](AsyncWebServerRequest *request) {
  }, nullptr, [](AsyncWebServerRequest *request, uint8_t *data, size_t len, size_t index, size_t total) {
    if (!checkAuth(request)) return;
    uint32_t freqHz = 0;
    if (len > 0) {
      JsonDocument doc;
      if (!deserializeJson(doc, data, len)) {
        double mhz = doc["frequency_mhz"] | 0.0;
        if (mhz > 0.0) freqHz = (uint32_t)(mhz * 1e6);
      }
    }
    queueWebScan(freqHz);
    request->send(202, "application/json", "{\"ok\":true}");
  });
  server.on("/api/sweep", HTTP_POST, [](AsyncWebServerRequest *request) {
    if (!checkAuth(request)) return;
    queueWebSweep();
    request->send(202, "application/json", "{\"ok\":true}");
  });

  // Same request/body-callback split AsyncWebServer needs for a POST
  // body, matching pocsag_companion.ino's own /api/send /api/timeout
  // routes exactly.
  server.on("/api/wifi", HTTP_POST, [](AsyncWebServerRequest *request) {
  }, nullptr, [](AsyncWebServerRequest *request, uint8_t *data, size_t len, size_t index, size_t total) {
    if (!checkAuth(request)) return;
    JsonDocument doc;
    if (deserializeJson(doc, data, len)) {
      request->send(400, "application/json", "{\"ok\":false,\"error\":\"bad json\"}");
      return;
    }
    String ssid = doc["ssid"] | "";
    String password = doc["password"] | "";
    if (ssid.length() == 0) {
      request->send(400, "application/json", "{\"ok\":false,\"error\":\"ssid is required\"}");
      return;
    }
    setWifiCredentials(ssid, password);
    prefs.putString("wifi_ssid", ssid);
    prefs.putString("wifi_pass", password);
    request->send(200, "application/json", "{\"ok\":true}");
  });

  server.on("/api/reboot", HTTP_POST, [](AsyncWebServerRequest *request) {
    if (!checkAuth(request)) return;
    rebootRequested = true;
    rebootRequestedAt = millis();
    request->send(200, "application/json", "{\"ok\":true}");
  });

  server.begin();
}

// Ported from pocsag_companion.ino's own setupWifiNtpOta() -- minus NTP,
// which that sketch only needs for wall-clock timestamps this device
// has no use for either (same reasoning pager_client.ino's own header
// comment already gives for excluding NTP: nothing here needs wall-clock
// time). Non-blocking: on no-credentials or a failed/timed-out connect,
// this just returns and the device carries on exactly as it does with
// no WiFi at all -- USB-serial/OLED function is never gated on this.
void setupWifiOta() {
  String ssid = getWifiSsid();
  String pass = getWifiPassword();

  if (ssid.length() == 0 || ssid == "YOUR_WIFI_SSID") {
    Serial.println("[wifi] no credentials configured, skipping WiFi/OTA/web dashboard");
    return;
  }

  WiFi.mode(WIFI_STA);
  WiFi.setHostname(MDNS_HOSTNAME);
  WiFi.begin(ssid.c_str(), pass.c_str());

  Serial.print("[wifi] connecting to "); Serial.print(ssid);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_CONNECT_TIMEOUT_MS) {
    delay(250);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[wifi] connect timed out, continuing USB-serial/OLED-only");
    return;
  }

  wifiConnected = true;
  Serial.print("[wifi] connected, IP="); Serial.println(WiFi.localIP());

  if (MDNS.begin(MDNS_HOSTNAME)) {
    Serial.print("[mdns] reachable at "); Serial.print(MDNS_HOSTNAME); Serial.println(".local");
  } else {
    Serial.println("[mdns] begin() failed");
  }

  ArduinoOTA.setHostname(MDNS_HOSTNAME);
  ArduinoOTA.setPassword(OTA_PASSWORD);
  ArduinoOTA.onStart([]() {
    Serial.println("[ota] update starting");
    display.clearDisplay();
    display.setCursor(0, 0);
    display.println("OTA update");
    display.println("starting...");
    display.display();
  });
  ArduinoOTA.onEnd([]() {
    Serial.println("[ota] update complete");
    display.clearDisplay();
    display.setCursor(0, 0);
    display.println("OTA update");
    display.println("done, rebooting");
    display.display();
  });
  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    Serial.printf("[ota] progress: %u%%\n", (progress * 100) / total);
  });
  ArduinoOTA.onError([](ota_error_t error) {
    Serial.print("[ota] error "); Serial.println((int)error);
  });
  ArduinoOTA.begin();
  Serial.println("[ota] ready");

  setupWebServer(); // only reachable at all once WiFi is up, so started here
}

void setup() {
  Serial.begin(115200);
  delay(500);

  // Guards webPassword/wifiSsid/wifiPass and the web-triggered
  // scan/sweep pending flags -- must exist before anything (including
  // setupWifiOta(), later in this function) could possibly touch them.
  stateMutex = xSemaphoreCreateMutex();

  // OLED power rail: must happen before Wire.begin()/display.begin(),
  // or the screen stays dark -- same VEXT gotcha pager_client.ino's own
  // header comment documents (already cost real debugging time once).
  pinMode(VEXT_PIN, OUTPUT);
  digitalWrite(VEXT_PIN, LOW); // power ON

  Wire.begin(OLED_SDA_PIN, OLED_SCL_PIN);
  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("[!] OLED init failed");
  }
  display.setRotation(0);
  // Set once, applies to every subsequent print()/println() for the
  // rest of the program -- without this, text silently never rendered
  // (drawFastHLine()/fillRect() always pass their color explicitly so
  // those drew fine regardless; only text relies on this state). Same
  // call pager_client.ino's own confirmed-working boot screen makes.
  display.setTextColor(SSD1306_WHITE);
  drawBootScreen();

  pinMode(BUTTON_GPIO, INPUT_PULLUP);

  SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_CS);
  int state = radio.begin(DEFAULT_FREQ_MHZ, 125.0, 9, 7, RADIOLIB_SX126X_SYNC_WORD_PRIVATE, 10, 8);
  if (state != RADIOLIB_ERR_NONE) {
    Serial.printf("[!] Radio init failed: %d\n", state);
    display.clearDisplay();
    display.setCursor(0, 0);
    display.printf("Radio init\nfailed: %d", state);
    display.display();
    while (true) delay(1000);
  }
  radio.startReceive();

  // NVS overrides, if any were ever saved via the web UI -- each falls
  // back to the secrets.h compile-time default (the String globals
  // above are already seeded from those macros). WiFi/OTA/web-server
  // come up last, after core RF function is already configured -- a
  // slow/failed WiFi connect only adds a bounded delay before the ready
  // banner below, never blocks RX/scan/serial function.
  prefs.begin(PREFS_NAMESPACE, false);
  setWebPassword(prefs.getString("web_password", WEB_PASSWORD));
  setWifiCredentials(
    prefs.getString("wifi_ssid", WIFI_SSID),
    prefs.getString("wifi_pass", WIFI_PASSWORD)
  );
  setupWifiOta();

  Serial.println("[*] RF Environment Scanner ready");

  // Boots straight into a real reading instead of an empty/waiting
  // screen -- see header comment. Blocks setup() for ~0.6s (the same
  // sweep a button press triggers later), acceptable once at boot.
  runBandSpectrumSweep();
  drawMainScreen();
}

void loop() {
  checkButton();
  stepLiveScan(); // cheap (one retune + one RSSI read) when continuousMode is active, a no-op otherwise

  if (wifiConnected) ArduinoOTA.handle();
  checkWebScanPending();  // picks up a scan staged by the web UI's /api/scan handler
  checkWebSweepPending(); // picks up a sweep staged by the web UI's /api/sweep handler

  if (rebootRequested && millis() - rebootRequestedAt >= REBOOT_DELAY_MS) {
    ESP.restart();
  }

  if (displayOn && millis() - lastDisplayActivity >= DISPLAY_TIMEOUT_MS) {
    display.ssd1306_command(SSD1306_DISPLAYOFF);
    displayOn = false;
  }
}
