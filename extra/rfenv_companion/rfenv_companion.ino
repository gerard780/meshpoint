/*
  Meshpoint RF Environment companion -- Heltec WiFi LoRa32 V3 (ESP32-S3 + SX1262)

  Built to close a real, datasheet-confirmed gap: the deployed RAK2287
  concentrator has no SX1261 at all, so it can never run a real hardware
  spectral scan -- Meshpoint's RF Environment page falls back to a
  packet-derived noise-floor estimate forever on that board. This
  companion is a second, independent radio with its own antenna that
  samples real ambient RSSI and reports a histogram back to Meshpoint
  over USB serial, so that page can show real hardware-measured data
  again even on a board that will never grow a working SX1261.

  ---------------------------------------------------------------------
  Wire protocol -- newline-delimited JSON, request/response, same idiom
  as extra/pocsag_companion's {"cmd":"status"} (src/capture/dapnet_source.py
  is the reference implementation of this exact request/response style
  on the Meshpoint side; this firmware is polled, it never speaks first):

    {"cmd":"status"}
      -> {"type":"status","board":"heltec_v3_rfenv","band":"eu868"|"70cm",
          "uptime_ms":<uint32>}

    {"cmd":"scan","frequency_hz":<uint32>,"nb_scan":<uint16>}
      -> {"type":"scan_result","frequency_hz":<uint32>,"nb_scan":<uint16>,
          "levels_dbm":[<int>, ... NB_LEVELS entries ...],
          "counts":[<int>, ... NB_LEVELS entries ...]}

      Retunes to frequency_hz, enters LoRa receive mode, and takes
      nb_scan (clamped to [MIN_NB_SCAN, MAX_NB_SCAN]) radio.getRSSI()
      readings -- an AGC-level instantaneous measurement, valid
      regardless of packet sync/demod, same principle as the real
      SX1302 HAL's own spectral scan not depending on packet demod.
      Each sample is bucketed on-device into one of NB_LEVELS fixed
      dBm bins (see below) -- deliberately mirrors the real HAL's own
      division of labour (src/hal/sx1302_spectral_scan.py: "the scan
      operation lives in SX1302SpectralScan... the value derivation
      lives in SpectralScanResult") -- this firmware plays the role of
      the HAL (raw sampling + histogram), the Python-side
      RfEnvCompanionScanService plays the role of SX1302SpectralScan.run()
      (issue the scan, wait, wrap the result). The bin scale here is a
      firmware-local convention, independent of the real HAL's own
      35-level table -- it only needs to be internally consistent for
      the percentile math the Python side already has (SpectralScanResult).

    {"cmd":"sweep","frequencies_hz":[<uint32>, ...],"nb_scan":<uint16>}
      -> {"type":"sweep_result","point_count":<uint16>,
          "points":[{"frequency_hz":<uint32>,"floor_dbm":<int>,
                      "median_dbm":<int>,"p95_dbm":<int>}, ...]}

      Powers the Band Spectrum card (src/api/routes/spectrum_routes.py),
      a genuinely different feature from the single-frequency histogram
      above -- RfEnvCompanionScanService requests this with the SAME
      frequency list src/api/server.py's own _sweep_frequencies_hz()
      computes for the real HAL sweep (frequency-plan logic stays
      Python-side, single source of truth, same reasoning as the scan
      command not hardcoding a region here either). Per point, this
      firmware takes nb_scan samples (clamped to
      [MIN_NB_SCAN, SWEEP_MAX_NB_SCAN_PER_POINT] -- deliberately a much
      smaller ceiling than the histogram scan's, since a 71-point EU868
      sweep needs to finish in a few seconds, not a few seconds PER
      point), computes floor/median/p95 from a throwaway per-point
      histogram (percentileDbm(), same math as the standalone local
      scan), and reports only those three numbers per point rather than
      the full histogram -- keeps a 71-point reply small. frequencies_hz
      is capped at SWEEP_MAX_POINTS; excess entries are ignored rather
      than blowing the sweep's time budget or JSON reply size.

  Any malformed/unrecognised line is logged to Serial and ignored, same
  behaviour as every other companion's serial parser in this repo.

  ---------------------------------------------------------------------
  OLED (128x64 SSD1306, onboard). Every screen opens with a one-line
  header (STATUS / LIVE SCAN / BAND SPECTRUM / CHANNEL HISTOGRAM,
  drawHeader()) naming itself after the matching RF Environment
  dashboard card, so it's unambiguous which screen/data you're looking
  at without needing to read the whole layout. PRG button (GPIO0, same
  physical button pager_client.ino uses) drives four screens --
  everything here works with no USB/Meshpoint connection at all, so
  the board is a genuinely useful standalone RF tool on its own:

    STATUS            -- how long ago Meshpoint last polled (or
                          "waiting for Meshpoint..." before the first
                          poll). Short-press cycles to LIVE SCAN.
    LIVE SCAN         -- continuously hops across BAND_STEPS fixed
                          frequencies spanning BAND_START_MHZ..BAND_END_MHZ
                          (compile-time, defaults to EU868) and renders
                          a live bar-per-frequency RSSI view (one raw
                          instantaneous sample per hop). Short-press
                          advances to BAND SPECTRUM.
    BAND SPECTRUM     -- short-press runs a fresh discrete sweep across
                          the same BAND_STEPS frequency plan (a handful
                          of samples per point via runHistogramScan(),
                          not one raw sample like LIVE SCAN), and draws
                          median (solid line) + p95/peak (sparse dots)
                          -- the on-device equivalent of the dashboard's
                          Band Spectrum card, same math as the
                          {"cmd":"sweep"} handler below just local and
                          synchronous. Short-press returns to STATUS.
    CHANNEL HISTOGRAM -- hold the button (>= LONG_PRESS_MS, works from
                          any of the three screens above) to run the
                          exact same 35-bin histogram scan Meshpoint
                          itself requests over serial ({"cmd":"scan"}),
                          at whatever frequency Meshpoint last polled
                          (or DEFAULT_FREQ_MHZ before the first poll),
                          and render it right here -- floor/median
                          computed the same way (percentileDbm(),
                          mirroring SpectralScanResult.percentile()) so
                          this matches what the RF Environment page
                          would show for the same scan. Short-press
                          returns to STATUS.

  Auto-blanks after DISPLAY_TIMEOUT_MS (default 5s) of no button
  activity -- burn-in protection, same wakeDisplay()/SSD1306_DISPLAYOFF
  pattern already proven in extra/pager_client.ino and
  extra/pocsag_companion.ino. Any button press wakes the panel AND
  performs its normal action in the same press (no separate "just
  wake" gesture) -- wakeDisplay() runs at the top of drawCurrentScreen(),
  which every button-triggered path already calls. Deliberately NOT
  reset by LIVE SCAN's own continuous background redraw (stepLiveScan()
  calls drawLiveScanScreen() directly, bypassing drawCurrentScreen()) --
  otherwise that screen's animation would keep the panel on forever
  regardless of whether anyone's actually there watching it.

  A serial scan/sweep request from Meshpoint briefly interrupts
  whichever screen is active to service it (same "scan pauses
  everything else for its short window" tradeoff the real HAL's own
  docstring already documents), then that screen resumes/redraws
  normally afterward.

  Hardware pins are the exact ones already verified on this same board
  in extra/pager_client/pager_client.ino -- copied, not re-derived.

  ---------------------------------------------------------------------
  WiFi / mDNS / OTA / web dashboard -- entirely optional, ported from
  extra/pocsag_companion.ino's own WiFi/OTA/web-dashboard section
  (mechanism only, not its paging-specific content -- no callsign, no
  page-send form/log, this device has neither concept). If secrets.h's
  WIFI_SSID is empty or still the placeholder, setupWifiOta() returns
  immediately and none of this runs -- a board used purely as a
  USB-serial Meshpoint companion needs secrets.h left untouched.

  When configured, this gives a second, independent way to use the same
  standalone-scanner capability the OLED already provides: a live
  RF-environment view (Status/Channel Histogram/Band Spectrum/WiFi
  Credentials cards, "Scan now"/"Sweep now" buttons) in a browser at
  http://rfenv-companion.local, styled to match Meshpoint's own dark
  dashboard theme -- useful e.g. as a portable scanner, where a
  phone/laptop screen beats squinting at a 128x64 OLED. ArduinoOTA lets
  firmware updates go out over WiFi instead of USB once configured.

  Cross-thread safety: AsyncWebServer's request/body callbacks run on
  AsyncTCP's own FreeRTOS task, not loop()'s thread -- loop() remains
  the only thread that ever touches `radio` (a web-triggered Scan/Sweep
  only stages a request via queueWebScan()/queueWebSweep(), which
  loop()'s checkWebScanPending()/checkWebSweepPending() actually run) or
  mutates webPassword/wifiSsid/wifiPass, all guarded by stateMutex --
  same discipline pocsag_companion.ino/pager_client.ino both already
  establish for their own web dashboards.

  Status: LIVE-CONFIRMED on real hardware (histogram, sweep, OLED text
  after the setTextColor fix) via Configuration -> Firmware's compile/
  flash card. The WiFi/OTA/web-dashboard section above is new and
  compile-verified only -- not yet flashed/tested on real hardware.
*/

// ==== BAND SELECT ====
// Uncomment exactly one before compiling. Same source-level toggle +
// regex-rewrite mechanism as pocsag_companion.ino's own BOARD SELECT
// block (see src/api/routes/rfenv_companion_firmware_routes.py's
// _select_band_define()) -- Configuration -> Firmware's Band picker
// rewrites this automatically, no need to hand-edit for the normal
// dashboard-driven flow. EU868 matches this board's primary use case
// (feeding Meshpoint's RF Environment page, tied to the concentrator's
// own band); 70CM is for a second, physically distinct board (its own
// antenna/RF matching network built for that band) used purely as a
// standalone handheld scanner -- it can never usefully feed a
// 868/915-band Meshpoint's own RF Environment page.
//#define BAND_EU868
#define BAND_70CM

#if defined(BAND_EU868) && defined(BAND_70CM)
  #error "Uncomment only ONE band in the BAND SELECT block above"
#elif !defined(BAND_EU868) && !defined(BAND_70CM)
  #error "Uncomment exactly ONE band in the BAND SELECT block above"
#endif

// Short band identifier, reported in the {"cmd":"status"} reply --
// same idea as pocsag_companion.ino's own BOARD_NAME_STR.
#if defined(BAND_70CM)
  #define BAND_NAME_STR "70cm"
  #define DEFAULT_FREQ_MHZ 433.500f
  #define BAND_START_MHZ 430.0f
  #define BAND_END_MHZ   440.0f
#else
  #define BAND_NAME_STR "eu868"
  #define DEFAULT_FREQ_MHZ 869.525f
  #define BAND_START_MHZ 863.0f
  #define BAND_END_MHZ   870.0f
#endif

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
#include "secrets.h" // gitignored -- WIFI_SSID/WIFI_PASSWORD/OTA_PASSWORD/WEB_PASSWORD, see that file

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
// runs, exactly like extra/pocsag_companion.ino's own behavior. A board
// used purely as a USB-serial Meshpoint companion needs secrets.h left
// untouched. When it IS configured, this gives a second, independent
// way to use the same standalone-scanner capability the OLED already
// provides: a live RF-environment view in a browser on the board's own
// WiFi -- useful e.g. as a portable scanner, where a phone/laptop
// screen beats squinting at a 128x64 OLED. Ported from
// pocsag_companion.ino's own WiFi/OTA/web-dashboard section --
// mechanism only, not its paging-specific content (no callsign, no
// page-send form/log -- this device has neither concept).
#define MDNS_HOSTNAME "rfenv-companion"
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

// ---------- Histogram bin scheme (see header comment) ----------
#define NB_LEVELS 35
#define LEVEL_MIN_DBM (-140)
#define LEVEL_STEP_DBM 3
// Top bin covers LEVEL_MIN_DBM + (NB_LEVELS-1)*LEVEL_STEP_DBM = -38 dBm
// and above -- samples stronger than that (e.g. a radio a few cm away)
// just saturate the last bucket rather than overflow the array.

#define MIN_NB_SCAN 16
#define MAX_NB_SCAN 1500 // ~3s worst case at SAMPLE_DELAY_MS below -- keeps
                          // Meshpoint's own request timeout (~8s) comfortable
#define SAMPLE_DELAY_MS 2
#define RETUNE_SETTLE_MS 5

// DEFAULT_FREQ_MHZ (used both for radio.begin() and as the local
// button-triggered scan's anchor until Meshpoint has actually polled
// once) is derived from the BAND SELECT block near the top of the file.

// Button-triggered local scan (see header comment) -- fewer samples than
// the serial-triggered default since a human is standing there watching
// the screen rather than a timeout budget on the other end of a wire.
#define LOCAL_SCAN_NB_SCAN 400

// ---------- Band spectrum sweep ({"cmd":"sweep"}, see header comment) ----------
// Much smaller than MAX_NB_SCAN -- a 71-point EU868 sweep needs a per-point
// budget small enough that the WHOLE sweep still finishes in a few seconds.
#define SWEEP_MAX_NB_SCAN_PER_POINT 32
#define SWEEP_MAX_POINTS 128 // safety cap on the incoming frequencies_hz array

// ---------- Standalone live band-scan (see header comment) ----------
// BAND_START_MHZ/BAND_END_MHZ are derived from the BAND SELECT block
// near the top of the file -- this is a firmware-local convenience
// view either way, not something Meshpoint coordinates or depends on.
#define BAND_STEPS 32 // -> 4px-wide columns on a 128px-wide screen
#define BAND_REDRAW_EVERY_N_STEPS 1 // 32 steps is few enough to redraw every hop

static float bandRssi[BAND_STEPS];
static int bandIndex = 0;
static bool bandRssiValid[BAND_STEPS] = {false};

// ---------- Local band spectrum (short-press screen) ----------
// Same BAND_STEPS frequency plan as the live scan above, but a discrete
// snapshot with median/p95 per point (same math/spirit as the real
// Band Spectrum card and the {"cmd":"sweep"} handler) instead of one
// raw instantaneous sample per hop -- run fresh each time this screen
// is entered, not continuously.
#define BAND_SPECTRUM_NB_SCAN_PER_POINT 8
static float bandSpectrumMedian[BAND_STEPS];
static float bandSpectrumP95[BAND_STEPS];
static bool hasBandSpectrum = false;
static uint32_t bandSpectrumAtMs = 0; // millis() of the last completed sweep; 0 = never.
                                       // Lets the web dashboard tell a fresh Sweep-now
                                       // result apart from a stale one while polling.

// ---------- Display auto-blank (burn-in protection) ----------
// Same pattern already proven in extra/pager_client.ino and
// extra/pocsag_companion.ino (there: 10s default; shorter here since
// this board mostly just sits polling in the background, no one's
// meant to be reading it continuously).
#define DISPLAY_TIMEOUT_MS 5000
static bool displayOn = true;
static uint32_t lastDisplayActivity = 0;

void wakeDisplay() {
  if (!displayOn) {
    display.ssd1306_command(SSD1306_DISPLAYON);
    displayOn = true;
  }
  lastDisplayActivity = millis();
}

// ---------- Standalone local histogram scan (button long-press) ----------
// Same 35-bin scan Meshpoint itself requests over serial ({"cmd":"scan"}),
// just triggered locally and rendered on-device -- a user standing next
// to the board with no laptop/Pi in reach can still get a real reading.
static uint16_t localHistCounts[NB_LEVELS];
static uint32_t localHistFrequencyHz = 0;
static bool hasLocalHist = false;
static uint32_t localHistAtMs = 0; // millis() of the last completed scan; 0 = never.
                                    // Same freshness-tracking role as bandSpectrumAtMs.
// Tracks whatever frequency Meshpoint most recently requested over serial,
// so a local scan matches the real anchor channel once one exists --
// falls back to DEFAULT_FREQ_MHZ before the first serial poll ever arrives.
static uint32_t lastRequestedFrequencyHz = 0;

enum ScreenMode { SCREEN_STATUS, SCREEN_LIVE_SCAN, SCREEN_BAND_SPECTRUM, SCREEN_LOCAL_HIST };
static ScreenMode currentScreen = SCREEN_STATUS;

static uint32_t lastPollAtMs = 0;
static bool everPolled = false;

// Forward declarations -- called before their definitions below (setup()/
// loop() aren't the only entry points here), and Arduino's auto-generated
// prototypes don't reliably cover every case (see pager_client.ino's own
// identical precedent for this).
void drawCurrentScreen();
void drawStatusScreen();
void drawLiveScanScreen();
void drawBandSpectrumScreen();
void drawLocalHistScreen();
bool runHistogramScan(uint32_t frequencyHz, uint16_t nbScan, uint16_t *counts);
float percentileDbm(uint16_t *counts, float p);
void runBandSpectrumSweep();
void setupWebServer();

// ---------- Button (short-press cycles screens, long-press = local scan) ----------
static bool lastButtonReading = HIGH;
static bool buttonState = HIGH;
static uint32_t lastButtonChangeMs = 0;
static uint32_t buttonDownAtMs = 0;
static bool longPressFired = false;
#define DEBOUNCE_MS 30
#define LONG_PRESS_MS 700

void runLocalHistScan() {
  uint32_t freqHz = lastRequestedFrequencyHz != 0
      ? lastRequestedFrequencyHz
      : (uint32_t)(DEFAULT_FREQ_MHZ * 1e6f);
  if (runHistogramScan(freqHz, LOCAL_SCAN_NB_SCAN, localHistCounts)) {
    localHistFrequencyHz = freqHz;
    hasLocalHist = true;
    localHistAtMs = millis();
  }
  currentScreen = SCREEN_LOCAL_HIST;
  drawCurrentScreen();
}

// Sweeps the same BAND_STEPS frequency plan the live-scan view uses,
// but with a small per-point histogram (BAND_SPECTRUM_NB_SCAN_PER_POINT)
// instead of one raw sample, so median/p95 are real statistics rather
// than a single noisy reading -- same idea as handleSweepCommand(),
// just local and synchronous (~32 * ~20ms =~ 0.6s, fine to block on
// button release the same way the local histogram scan already does).
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

void queueWebScan() {
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  webScanPending = true;
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
  webScanPending = false;
  xSemaphoreGive(stateMutex);
  if (run) runLocalHistScan();
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
    } else { // released
      if (!longPressFired) {
        // Short press -- cycle STATUS -> LIVE_SCAN -> BAND_SPECTRUM ->
        // STATUS. From SCREEN_LOCAL_HIST (only ever entered via a long
        // press) a short press also returns to STATUS, same as any
        // other non-cycle screen -- it isn't part of the cycle itself.
        if (currentScreen == SCREEN_STATUS) {
          currentScreen = SCREEN_LIVE_SCAN;
        } else if (currentScreen == SCREEN_LIVE_SCAN) {
          currentScreen = SCREEN_BAND_SPECTRUM;
          runBandSpectrumSweep(); // fresh snapshot every time this screen is entered
        } else {
          currentScreen = SCREEN_STATUS;
        }
        drawCurrentScreen();
      }
    }
  }
  // Fire the long-press action once, as soon as the hold threshold is
  // crossed, rather than waiting for release -- more responsive, and
  // matches the header comment's "hold" wording literally.
  if (buttonState == LOW && !longPressFired &&
      (millis() - buttonDownAtMs) >= LONG_PRESS_MS) {
    longPressFired = true;
    runLocalHistScan();
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
// into counts[NB_LEVELS]. Shared by the serial {"cmd":"scan"} handler
// and the button-triggered local scan -- same sampling logic either
// way, only the caller (and what happens with the result) differs.
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

// Runs one full scan at frequencyHz, replies on Serial as scan_result.
// Briefly takes over the radio from the live band-scan view (if active)
// -- same "scan pauses everything else for its short window" tradeoff
// already documented for the real HAL's own spectral scan.
void handleScanCommand(JsonDocument &doc) {
  uint32_t frequencyHz = doc["frequency_hz"] | 0UL;
  uint16_t nbScan = doc["nb_scan"] | 512;
  if (nbScan < MIN_NB_SCAN) nbScan = MIN_NB_SCAN;
  if (nbScan > MAX_NB_SCAN) nbScan = MAX_NB_SCAN;

  if (frequencyHz == 0) {
    Serial.println("[serial] scan: missing/zero frequency_hz, ignored");
    return;
  }

  static uint16_t counts[NB_LEVELS];
  if (!runHistogramScan(frequencyHz, nbScan, counts)) return;
  lastRequestedFrequencyHz = frequencyHz;

  lastPollAtMs = millis();
  everPolled = true;
  if (currentScreen == SCREEN_STATUS) drawCurrentScreen();

  JsonDocument out;
  out["type"] = "scan_result";
  out["frequency_hz"] = frequencyHz;
  out["nb_scan"] = nbScan;
  JsonArray levels = out["levels_dbm"].to<JsonArray>();
  JsonArray countsOut = out["counts"].to<JsonArray>();
  for (int i = 0; i < NB_LEVELS; i++) {
    levels.add(LEVEL_MIN_DBM + i * LEVEL_STEP_DBM);
    countsOut.add(counts[i]);
  }
  serializeJson(out, Serial);
  Serial.println();
}

// Sweeps every frequency in the requested list, replies on Serial as
// sweep_result. Powers the Band Spectrum card -- see the header comment
// for why this reports only floor/median/p95 per point (not a full
// histogram like handleScanCommand()) and why the frequency list comes
// from Meshpoint rather than a firmware-local band constant.
void handleSweepCommand(JsonDocument &doc) {
  JsonArray freqArray = doc["frequencies_hz"].as<JsonArray>();
  if (freqArray.isNull() || freqArray.size() == 0) {
    Serial.println("[serial] sweep: missing/empty frequencies_hz, ignored");
    return;
  }
  uint16_t nbScan = doc["nb_scan"] | SWEEP_MAX_NB_SCAN_PER_POINT;
  if (nbScan < MIN_NB_SCAN) nbScan = MIN_NB_SCAN;
  if (nbScan > SWEEP_MAX_NB_SCAN_PER_POINT) nbScan = SWEEP_MAX_NB_SCAN_PER_POINT;

  JsonDocument out;
  out["type"] = "sweep_result";
  JsonArray pointsOut = out["points"].to<JsonArray>();

  static uint16_t counts[NB_LEVELS];
  int pointCount = 0;
  for (JsonVariant v : freqArray) {
    if (pointCount >= SWEEP_MAX_POINTS) break;
    uint32_t freqHz = v.as<uint32_t>();
    if (freqHz == 0 || !runHistogramScan(freqHz, nbScan, counts)) continue;
    JsonObject point = pointsOut.add<JsonObject>();
    point["frequency_hz"] = freqHz;
    point["floor_dbm"] = (int)percentileDbm(counts, 10.0f);
    point["median_dbm"] = (int)percentileDbm(counts, 50.0f);
    point["p95_dbm"] = (int)percentileDbm(counts, 95.0f);
    pointCount++;
  }
  out["point_count"] = pointCount;

  lastPollAtMs = millis();
  everPolled = true;
  drawCurrentScreen(); // radio was retuned repeatedly -- refresh whatever's on screen

  serializeJson(out, Serial);
  Serial.println();
}

void sendStatusReply() {
  JsonDocument out;
  out["type"] = "status";
  out["board"] = "heltec_v3_rfenv";
  out["band"] = BAND_NAME_STR;
  out["uptime_ms"] = millis();
  serializeJson(out, Serial);
  Serial.println();
  lastPollAtMs = millis();
  everPolled = true;
  if (currentScreen == SCREEN_STATUS) drawCurrentScreen();
}

// ---------- Serial input: line accumulation + JSON dispatch ----------
// Same line-accumulation approach already verified in pocsag_companion.ino.
String serialLineBuf;

void handleSerialJsonLine(const String &line) {
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, line);
  if (err) {
    Serial.print("[serial] JSON parse error: "); Serial.println(err.c_str());
    return;
  }
  String cmd = doc["cmd"] | "";
  if (cmd == "status") { sendStatusReply(); return; }
  if (cmd == "scan") { handleScanCommand(doc); return; }
  if (cmd == "sweep") { handleSweepCommand(doc); return; }
  Serial.print("[serial] unrecognised cmd: \""); Serial.print(cmd); Serial.println("\"");
}

void checkSerialInput() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      serialLineBuf.trim();
      if (serialLineBuf.length() > 0) {
        handleSerialJsonLine(serialLineBuf);
      }
      serialLineBuf = "";
    } else {
      serialLineBuf += c;
    }
  }
}

// ---------- Display ----------

// Consistent top bar for every screen -- same title wording as the
// matching dashboard card ("CHANNEL HISTOGRAM", "BAND SPECTRUM", ...)
// so at a glance you know which screen you're on and what it maps to
// on the RF Environment page.
void drawHeader(const char *title) {
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println(title);
  display.drawFastHLine(0, 9, OLED_WIDTH, SSD1306_WHITE);
}

void drawStatusScreen() {
  display.clearDisplay();
  drawHeader("STATUS");

  display.setCursor(0, 16);
  if (!everPolled) {
    display.println("Waiting for");
    display.println("Meshpoint...");
  } else {
    uint32_t agoS = (millis() - lastPollAtMs) / 1000;
    display.print("Last poll: ");
    display.print(agoS);
    display.println("s ago");
  }

  display.setCursor(0, 40);
  display.print("Press: cycle views");
  display.setCursor(0, 56);
  display.print("Hold: scan now");
  display.display();
}

void drawLiveScanScreen() {
  display.clearDisplay();
  drawHeader("LIVE SCAN");

  // Bars span the region below the header down to just above the
  // bottom hint line. Each sample is clamped into the same dBm range
  // the scan histogram uses, so a strong nearby transmitter reads the
  // same way in both views.
  const int topY = 11;
  const int bottomY = OLED_HEIGHT - 9;
  const int barAreaH = bottomY - topY;
  const int colWidth = OLED_WIDTH / BAND_STEPS;
  const float rangeDbm = (float)(NB_LEVELS * LEVEL_STEP_DBM);

  for (int i = 0; i < BAND_STEPS; i++) {
    if (!bandRssiValid[i]) continue;
    float norm = (bandRssi[i] - LEVEL_MIN_DBM) / rangeDbm;
    if (norm < 0) norm = 0;
    if (norm > 1) norm = 1;
    int h = (int)(norm * barAreaH);
    display.fillRect(i * colWidth, bottomY - h, max(1, colWidth - 1), h, SSD1306_WHITE);
  }

  display.setCursor(0, OLED_HEIGHT - 8);
  display.print("Press: next  Hold: scan");
  display.display();
}

// dBm -> pixel-row helper shared by the band-spectrum chart's two series.
int bandSpectrumY(float dbm, int bottomY, int chartH) {
  const float rangeDbm = (float)(NB_LEVELS * LEVEL_STEP_DBM);
  float norm = (dbm - LEVEL_MIN_DBM) / rangeDbm;
  if (norm < 0) norm = 0;
  if (norm > 1) norm = 1;
  return bottomY - (int)(norm * chartH);
}

// Median (solid connected line) + p95/peak (sparse dots, visually
// distinct from the median line on a 1-bit display) across the same
// BAND_STEPS frequency plan the live-scan view uses -- the on-device
// equivalent of the dashboard's Band Spectrum card.
void drawBandSpectrumScreen() {
  display.clearDisplay();
  drawHeader("BAND SPECTRUM");

  if (!hasBandSpectrum) {
    display.setCursor(0, 20);
    display.println("Sweeping...");
    display.display();
    return;
  }

  const int topY = 11;
  const int bottomY = OLED_HEIGHT - 9;
  const int chartH = bottomY - topY;
  const int colWidth = OLED_WIDTH / BAND_STEPS;

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

  display.setCursor(0, OLED_HEIGHT - 8);
  display.print("Press: status");
  display.display();
}

// Same 35-bin histogram Meshpoint itself would get from a serial
// {"cmd":"scan"} -- floor/median computed the same way
// (SpectralScanResult.percentile()) so the on-device readout matches
// what the RF Environment page would show for this exact scan.
void drawLocalHistScreen() {
  display.clearDisplay();
  drawHeader("CHANNEL HISTOGRAM");

  if (!hasLocalHist) {
    display.setCursor(0, 20);
    display.println("Local scan failed");
    display.println("(radio busy/error)");
    display.display();
    return;
  }
  display.setCursor(0, 11);
  display.print("@ ");
  display.print(localHistFrequencyHz / 1e6f, 3);
  display.print(" MHz");

  const int topY = 20;
  const int bottomY = OLED_HEIGHT - 17;
  const int barAreaH = bottomY - topY;
  const int colWidth = OLED_WIDTH / NB_LEVELS;
  uint32_t maxCount = 1;
  for (int i = 0; i < NB_LEVELS; i++) {
    if (localHistCounts[i] > maxCount) maxCount = localHistCounts[i];
  }
  for (int i = 0; i < NB_LEVELS; i++) {
    if (localHistCounts[i] == 0) continue;
    int h = (int)((localHistCounts[i] / (float)maxCount) * barAreaH);
    if (h < 1) h = 1;
    display.fillRect(i * colWidth, bottomY - h, max(1, colWidth - 1), h, SSD1306_WHITE);
  }

  float floorDbm = percentileDbm(localHistCounts, 10.0f);
  float medianDbm = percentileDbm(localHistCounts, 50.0f);
  display.setCursor(0, OLED_HEIGHT - 16);
  display.print("Floor ");
  display.print((int)floorDbm);
  display.print(" Med ");
  display.print((int)medianDbm);
  display.setCursor(0, OLED_HEIGHT - 8);
  display.print("Press: status");
  display.display();
}

void drawCurrentScreen() {
  wakeDisplay(); // any real content update wakes the panel if blanked
                 // and resets the idle timer -- see loop()'s auto-blank check.
  if (currentScreen == SCREEN_STATUS) drawStatusScreen();
  else if (currentScreen == SCREEN_LIVE_SCAN) drawLiveScanScreen();
  else if (currentScreen == SCREEN_BAND_SPECTRUM) drawBandSpectrumScreen();
  else drawLocalHistScreen();
}

// Same three-line centered layout as pager_client.ino's own
// drawBootScreen() (title / capcode / frequency) -- no capcode analog
// here, so title / "Companion" / anchor frequency instead. Centering
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
  const char *sub = "Companion";
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
// a blocking sweep-then-draw loop, so loop() stays responsive to
// incoming serial scan requests between every single-frequency hop.
void stepLiveScan() {
  float freqMHz = BAND_START_MHZ + (BAND_END_MHZ - BAND_START_MHZ) * bandIndex / (float)(BAND_STEPS - 1);
  if (radio.setFrequency(freqMHz) == RADIOLIB_ERR_NONE) {
    delay(RETUNE_SETTLE_MS);
    radio.startReceive();
    bandRssi[bandIndex] = sampleRssiDbm();
    bandRssiValid[bandIndex] = true;
  }
  bandIndex = (bandIndex + 1) % BAND_STEPS;
  if (currentScreen == SCREEN_LIVE_SCAN && bandIndex % BAND_REDRAW_EVERY_N_STEPS == 0) {
    drawLiveScanScreen();
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
<title>RF Environment Companion</title>
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
  .card h2 { font-size:13px; text-transform:uppercase; letter-spacing:1px; color: var(--text-secondary); margin:0 0 10px 0; }
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
    <h2>RF ENVIRONMENT COMPANION</h2>
    <div id="whoami">--</div>
    <label for="pw">Password</label>
    <input type="password" id="pw" autocomplete="off" spellcheck="false">
    <button onclick="tryLogin()">Unlock</button>
    <div class="result err" id="authErr"></div>
  </div>
</div>

<div id="app" class="hidden">
  <header>
    <h1>RF ENVIRONMENT COMPANION</h1>
    <div class="status">
      <span><span class="dot on" id="wifiDot"></span><span id="hostname">--</span></span>
      <span id="pollStatus">--</span>
    </div>
  </header>

  <div class="grid">
    <div class="card">
      <h2>Status</h2>
      <div class="kv"><span>Board</span><span id="stBoard">--</span></div>
      <div class="kv"><span>Band</span><span id="stBand">--</span></div>
      <div class="kv"><span>Uptime</span><span id="stUptime">--</span></div>
      <div class="kv"><span>Last Meshpoint poll</span><span id="stLastPoll">--</span></div>
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
      <div class="chartwrap"><canvas id="histCanvas"></canvas></div>
      <div class="readout">
        <span>Floor <b id="histFloor">--</b> dBm</span>
        <span>Median <b id="histMedian">--</b> dBm</span>
        <span id="histAge">no scan yet</span>
      </div>
      <button onclick="scanNow()">Scan Now</button>
      <div class="result" id="scanResult"></div>
    </div>

    <div class="card wide">
      <h2>Band Spectrum</h2>
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

function drawLines(canvas, median, p95, startMhz, endMhz) {
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

async function pollStatus() {
  let d;
  try { d = await apiGet('/api/status'); } catch (e) { return; }

  document.getElementById('hostname').textContent = d.hostname + '.local';
  document.getElementById('pollStatus').textContent = d.ever_polled
    ? ('Meshpoint: ' + fmtAgo(d.last_poll_ago_s)) : 'Waiting for Meshpoint';

  document.getElementById('stBoard').textContent = d.board;
  document.getElementById('stBand').textContent = d.band;
  document.getElementById('stUptime').textContent = fmtAgo(Math.floor(d.uptime_ms / 1000));
  document.getElementById('stLastPoll').textContent = d.ever_polled ? fmtAgo(d.last_poll_ago_s) : 'never';
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
    drawLines(document.getElementById('sweepCanvas'), d.sweep.median, d.sweep.p95, d.sweep.start_mhz, d.sweep.end_mhz);
    const sweepAge = document.getElementById('sweepAge');
    sweepAge.textContent = fmtAgo(d.sweep.age_s) + ' · ' + d.sweep.start_mhz + '-' + d.sweep.end_mhz + ' MHz';
    sweepAge.className = d.sweep.age_s > 300 ? 'stale' : '';
  }
}

async function scanNow() {
  const r = document.getElementById('scanResult');
  try {
    await apiPost('/api/scan');
    r.className = 'result ok'; r.textContent = 'Scanning…';
    setTimeout(pollStatus, 1500);
  } catch (e) { r.className = 'result err'; r.textContent = 'Failed'; }
}

async function sweepNow() {
  const r = document.getElementById('sweepResult');
  try {
    await apiPost('/api/sweep');
    r.className = 'result ok'; r.textContent = 'Sweeping…';
    setTimeout(pollStatus, 2000);
  } catch (e) { r.className = 'result err'; r.textContent = 'Failed'; }
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
    doc["uptime_ms"] = millis();
    doc["ever_polled"] = everPolled;
    doc["last_poll_ago_s"] = everPolled ? (millis() - lastPollAtMs) / 1000 : 0;
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
  // comment for why).
  server.on("/api/scan", HTTP_POST, [](AsyncWebServerRequest *request) {
    if (!checkAuth(request)) return;
    queueWebScan();
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

  Serial.println("[*] RF Environment companion ready");
  drawCurrentScreen();
}

void loop() {
  checkSerialInput(); // services {"cmd":"status"}/{"cmd":"scan"} promptly, always first
  checkButton();
  stepLiveScan(); // cheap (one retune + one RSSI read) -- fine to run every loop iteration

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
