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
  OLED (128x64 SSD1306, onboard). PRG button (GPIO0, same physical
  button pager_client.ino uses) drives three screens -- everything
  here works with no USB/Meshpoint connection at all, so the board is
  a genuinely useful standalone RF tool on its own:

    STATUS         -- board name, how long ago Meshpoint last polled
                      (or "waiting for Meshpoint..." before the first
                      poll). Short-press cycles to LIVE BAND SCAN.
    LIVE BAND SCAN -- continuously hops across BAND_STEPS fixed
                      frequencies spanning BAND_START_MHZ..BAND_END_MHZ
                      (compile-time, defaults to EU868) and renders a
                      live bar-per-frequency RSSI view. Short-press
                      returns to STATUS.
    LOCAL SCAN     -- hold the button (>= LONG_PRESS_MS, works from
                      either screen above) to run the exact same
                      35-bin histogram scan Meshpoint itself requests
                      over serial ({"cmd":"scan"}), at whatever
                      frequency Meshpoint last polled (or
                      DEFAULT_FREQ_MHZ before the first poll), and
                      render it right here -- floor/median computed
                      the same way (percentileDbm(), mirroring
                      SpectralScanResult.percentile()) so this matches
                      what the RF Environment page would show for the
                      same scan. Short-press returns to STATUS.

  A serial scan request from Meshpoint briefly interrupts whichever
  screen is active to service it (same "scan pauses everything else
  for its short window" tradeoff the real HAL's own docstring already
  documents), then that screen resumes/redraws normally afterward.

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

enum ScreenMode { SCREEN_STATUS, SCREEN_LIVE_SCAN, SCREEN_LOCAL_HIST };
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
void drawLocalHistScreen();
bool runHistogramScan(uint32_t frequencyHz, uint16_t nbScan, uint16_t *counts);

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
        // Short press -- cycle STATUS <-> LIVE_SCAN. From SCREEN_LOCAL_HIST
        // (only ever entered via a long press) a short press returns to
        // STATUS too, same as any other non-STATUS screen.
        currentScreen = (currentScreen == SCREEN_STATUS) ? SCREEN_LIVE_SCAN : SCREEN_STATUS;
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

void drawStatusScreen() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("RF Env Companion");
  display.drawFastHLine(0, 9, OLED_WIDTH, SSD1306_WHITE);

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
  display.print("Press: live view");
  display.setCursor(0, 56);
  display.print("Hold: scan now");
  display.display();
}

void drawLiveScanScreen() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print("Live scan ");
  display.print((int)BAND_START_MHZ);
  display.print("-");
  display.print((int)BAND_END_MHZ);
  display.println(" MHz");
  display.drawFastHLine(0, 9, OLED_WIDTH, SSD1306_WHITE);

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
  display.print("Hold: status");
  display.display();
}

// Same 35-bin histogram Meshpoint itself would get from a serial
// {"cmd":"scan"} -- floor/median computed the same way
// (SpectralScanResult.percentile()) so the on-device readout matches
// what the RF Environment page would show for this exact scan.
void drawLocalHistScreen() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);
  if (!hasLocalHist) {
    display.println("Local scan failed");
    display.println("(radio busy/error)");
    display.display();
    return;
  }
  display.print("Scan @ ");
  display.print(localHistFrequencyHz / 1e6f, 1);
  display.println(" MHz");
  display.drawFastHLine(0, 9, OLED_WIDTH, SSD1306_WHITE);

  const int topY = 11;
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
  if (currentScreen == SCREEN_STATUS) drawStatusScreen();
  else if (currentScreen == SCREEN_LIVE_SCAN) drawLiveScanScreen();
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
}
