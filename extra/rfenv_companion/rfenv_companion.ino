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
      -> {"type":"status","board":"heltec_v3_rfenv","uptime_ms":<uint32>}

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

  Status: compile-verified only (arduino-cli compile --fqbn
  esp32:esp32:heltec_wifi_lora_32_V3 --warnings all). No physical board
  flashed yet for this specific sketch.
*/

#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>

#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#include <RadioLib.h>
#include <ArduinoJson.h> // v7.4.3 -- JsonDocument/deserializeJson v7 API

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

#define DEFAULT_FREQ_MHZ 869.525f // used both for radio.begin() and as the
                                   // local button-triggered scan's anchor
                                   // until Meshpoint has actually polled once

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
// Default EU868 -- adjust to the deployment's own region if reused
// elsewhere; this is a firmware-local convenience view, not something
// Meshpoint coordinates or depends on.
#define BAND_START_MHZ 863.0f
#define BAND_END_MHZ   870.0f
#define BAND_STEPS 32 // -> 4px-wide columns on a 128px-wide screen
#define BAND_REDRAW_EVERY_N_STEPS 4

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

void drawBootScreen() {
  display.clearDisplay();
  display.setTextSize(2);
  int16_t x1, y1;
  uint16_t w, h;
  const char *title = "RF Env";
  display.getTextBounds(title, 0, 0, &x1, &y1, &w, &h);
  display.setCursor((OLED_WIDTH - w) / 2, 16);
  display.println(title);
  display.setTextSize(1);
  const char *sub = "Companion";
  display.getTextBounds(sub, 0, 0, &x1, &y1, &w, &h);
  display.setCursor((OLED_WIDTH - w) / 2, 40);
  display.println(sub);
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

void setup() {
  Serial.begin(115200);
  delay(500);

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
  drawBootScreen();

  pinMode(BUTTON_GPIO, INPUT_PULLUP);

  SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_CS);
  int state = radio.begin(869.525, 125.0, 9, 7, RADIOLIB_SX126X_SYNC_WORD_PRIVATE, 10, 8);
  if (state != RADIOLIB_ERR_NONE) {
    Serial.printf("[!] Radio init failed: %d\n", state);
    display.clearDisplay();
    display.setCursor(0, 0);
    display.printf("Radio init\nfailed: %d", state);
    display.display();
    while (true) delay(1000);
  }
  radio.startReceive();

  Serial.println("[*] RF Environment companion ready");
  drawCurrentScreen();
}

void loop() {
  checkSerialInput(); // services {"cmd":"status"}/{"cmd":"scan"} promptly, always first
  checkButton();
  stepLiveScan(); // cheap (one retune + one RSSI read) -- fine to run every loop iteration

  if (displayOn && millis() - lastDisplayActivity >= DISPLAY_TIMEOUT_MS) {
    display.ssd1306_command(SSD1306_DISPLAYOFF);
    displayOn = false;
  }
}
