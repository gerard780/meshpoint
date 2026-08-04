/*
  Meshpoint emergency pager client -- Heltec WiFi LoRa32 V3 (ESP32-S3 + SX1262)

  Talks directly over the air to the concentrator's dedicated FSK channel
  (ch9) built this session -- NOT a USB/serial companion like
  extra/pocsag_companion, and NOT POCSAG/DAPNET. A small, standalone,
  battery-powered two-way pager: one PRG button, one OLED, no keyboard.

  ---- Radio parameters: MUST match the concentrator exactly ----
  Every value below is hardcoded to match src/capture/concentrator_source.py's
  PAGER_FSK_* constants and src/config.py's RadioConfig.pager_* defaults, as
  configured on the deployed Pi at the time this was written. If those are
  ever changed (e.g. via Configuration -> Radio -> Pager on the dashboard),
  this firmware must be re-flashed to match -- there is no live sync yet.
  A future version could fetch these from the dashboard (e.g. a small HTTP
  endpoint or a provisioning step) instead of hardcoding, but that's still
  deferred -- WiFi/mDNS/OTA/a small web dashboard were added below (see that
  section's own comment), but only for status/manual-send/reflash
  convenience; the RF parameters above stay compile-time constants, never
  fetched live. WiFi is entirely best-effort and optional, same as
  pocsag_companion.ino's own -- with no real credentials configured (see
  secrets.h below) this device still works exactly as a standalone RX/TX
  pager, no network required at all.

    Frequency:        869.4625 MHz   (PAGER_FSK_FREQUENCY_HZ = 869_462_500)
    Sync word:         0x94 0x64 0x37 (3 bytes -- PAGER_FSK_SYNC_WORD = 0x946437)
    Bit rate:          4.8 kbps       (FSK_DEFAULT_DATARATE = 4800 bps)
    Frequency dev.:    25 kHz         (FSK_DEFAULT_FDEV_KHZ = 25)
    RX bandwidth:      125 kHz        (FSK_DEFAULT_BANDWIDTH = BW_125KHZ)
    TX power:          14 dBm         (TransmitConfig.tx_power_dbm default --
                                        conservative first pick, well under the
                                        ETSI sub-band P ceiling of 27 dBm/500mW;
                                        raising this needs a real PA/antenna
                                        check first, not done here)

  Whitening encoding and 2-byte CCITT CRC are confirmed against the real
  SX1302 HAL source (extra/sx1302_hal/libloragw/src/loragw_sx1302.c):
  DCFREE_ENC=2 ("Whitening Encoding", explicit comment in the HAL) and
  CRC_IBM=0 ("CCITT CRC", explicit comment) match RadioLib's
  RADIOLIB_ENCODING_WHITENING and setCRC()'s CCITT-polynomial default
  (0x1021) respectively -- these two settings genuinely matter (a whitening
  mismatch would make sync-word detection fail outright, not just degrade),
  so they were verified against source rather than guessed. Gaussian shaping
  IS enabled on the concentrator side too (GAUSSIAN_EN=1, GAUSSIAN_SELECT_BT=2)
  but the SX1302 HAL headers don't document which real BT value "2" maps to
  (0.3/0.5/0.7/1.0) -- RADIOLIB_SHAPING_0_5 below is a reasonable guess, not
  confirmed. A shaping/CRC-init mismatch is lower-risk than a whitening
  mismatch (affects spectral cleanliness / CRC-init edge cases, not whether
  the link can sync at all) -- worth the first thing to revisit if real
  hardware testing shows packets never being received.

  ---- WiFi / mDNS / OTA (optional, best-effort) ----
  Ported from pocsag_companion.ino's own WiFi/OTA section, minus NTP (this
  device has no use for wall-clock time) and minus the callsign/licensing
  gate (ch9 is ISM-band FSK, not amateur radio spectrum -- there's nothing
  here to license-gate the way POCSAG's TX is). WiFi connect is attempted
  once at boot with a bounded timeout (WIFI_CONNECT_TIMEOUT_MS below); if it
  fails or secrets.h still has placeholder credentials, the sketch carries
  on RX/TX-only exactly as before, no WiFi/OTA/mDNS/web dashboard at all --
  the button/OLED/radio path never depends on any of this. Once WiFi is up,
  the device is reachable at pager-<its own MY_CAPCODES[0]>.local (a
  per-unit hostname, so more than one pager on the same network doesn't
  collide) -- that same hostname is reused verbatim as the ArduinoOTA
  hostname. OTA needs its own password (OTA_PASSWORD in secrets.h) -- an
  unauthenticated OTA listener on a device sitting in someone's pocket would
  be a bad idea.

  ---- Web dashboard ----
  Once WiFi is up, a small password-gated single-page UI is served at
  http://pager-<capcode>.local/ (same dark color scheme + auth-modal pattern
  as pocsag_companion.ino's own). Cards: live status (capcodes this unit
  answers to, its own SEND_TO_CAPCODE, WiFi/hostname/uptime/heap), the last
  received message, a live in/outgoing log (same ring buffer + housekeeping
  as the OLED path), a free-text send form (POSTs to /api/send -- lets any
  authorized browser trigger a send, not just the physical button; stages
  the request for loop() to actually transmit, same reasoning as
  pocsag_companion.ino's own /api/send for why a web request can't call the
  radio directly), a WiFi-credentials card (POSTs to /api/wifi, applied
  on the next reboot via /api/reboot), and a screen-timeout setting (POSTs
  to /api/timeout, backs the same displayTimeoutMs the "Display power"
  section below also uses, 0 = never blank). Login password is
  WEB_PASSWORD in secrets.h, checked via an X-Auth-Password header on every
  API call, exactly as pocsag_companion.ino's own dashboard does.

  WiFi/OTA/web-password credentials live in secrets.h, INTENTIONALLY NOT
  INCLUDED IN THIS FILE and gitignored (see .gitignore) -- never hardcode
  real credentials directly in a tracked .ino. See secrets.h.example
  (created alongside this file) for what to fill in.

  ---- Status: UNTESTED ON REAL HARDWARE ----
  Compile-verified only (arduino-cli, esp32:esp32:heltec_wifi_lora_32_V3,
  RadioLib 7.7.1). Everything about the button UX, OLED layout, the RadioLib
  FSK RX/TX calls themselves, AND the WiFi/mDNS/OTA/web dashboard section
  above needs a real flash + real over-the-air test against the concentrator
  (which has already round-trip self-tested its own TX->RX loopback live,
  per project memory -- this is the first test with a genuinely separate
  second radio).

  ---- Hardware pins (Heltec WiFi LoRa32 V3) ----
  Ground truth copied from extra/pocsag_companion/pocsag_companion.ino's own
  hard-won, live-hardware-confirmed pin map (ESP32 core's own board file,
  cross-checked against Meshtastic's heltec_v3 variant.h) -- not re-derived,
  reused directly since it's the exact same physical board:
    SPI:    SCK 9, MISO 11, MOSI 10, CS 8
    Radio:  RST 12, BUSY 13, DIO1 14  (SX1262)
    OLED:   SDA 17, SCL 18, RST 21 (own dedicated reset pin, NOT shared with
            the radio's RST)
    VEXT:   GPIO36 -- external power switch for the OLED, active LOW = on.
            Must be driven low before Wire.begin()/display.begin(), or the
            OLED's power rail stays off and the screen never lights up.
    Button: GPIO0 (USER_SW / PRG), active LOW with internal pull-up.

  ---- Button UX (single-button state machine) ----
  Sketched during this session's pager brainstorm (see project memory,
  "Pager brainstorm continued: channel-isolation approach picked, button UX
  sketched") for the original ch5-7 LoRa plan -- carries over unchanged since
  it's about the button/OLED interaction, not the channel/modulation:
    Idle (default): OLED shows the last received message, who it's from,
      and its RSSI.
    Long-hold from idle: enters the reply menu, starting on the first
      canned-message option.
    In menu, short press: cycles to the next canned option (wraps around).
    In menu, long-hold: sends the currently highlighted option, returns to idle.
    In menu, no activity for MENU_TIMEOUT_MS: times out back to idle
      unsent (the "don't get stuck in a stale menu" refinement flagged
      earlier, now implemented).
    A message arriving while in the menu is stored but does NOT interrupt
      the menu display (the "leaning toward wait" refinement flagged
      earlier) -- it'll show once back at idle.
    Short press from idle also wakes the screen if it had auto-blanked
      (see "Display power" below) -- still no menu action, long-hold
      remains the only way in.

  ---- Display power ----
  Ported from pocsag_companion.ino's own: the OLED auto-blanks (real
  DISPLAYOFF command, not just cleared pixels, so it actually saves power)
  after displayTimeoutMs of no new screen content -- runtime-settable from
  the web dashboard's "Screen Timeout" card (0 = never blank), persisted in
  NVS so it survives a reboot. A short press from idle wakes it back up
  (see "Button UX" above); every drawIdle()/drawMenu() call also wakes it
  as a side effect of any real content update. No physical button toggles
  it off manually the way pocsag_companion.ino's BOOT button does -- this
  device's single button is already fully committed to the reply-menu
  state machine, so display power is timeout-only plus wake-on-activity.

  ---- Screen design (UNCONFIRMED ON REAL HARDWARE -- see status below) ----
  Idle/menu screens share a top status bar (drawTopBar()): title text on
  the left, a small vector WiFi icon and a new-message envelope icon fixed
  at the right edge (both hand-drawn from Adafruit_GFX primitives -- arcs/
  lines/rects -- not a bitmap asset). The envelope only appears while
  hasUnseenMessage is true, which is really only ever true for more than
  an instant in one case: a message arriving while in the send-menu
  (which deliberately doesn't interrupt, see "Button UX" above) -- idle
  itself clears the flag the moment it draws, since arriving there always
  means the message is already fully shown. Idle also word-wraps the
  message text at space boundaries (printWrapped()) instead of relying on
  Adafruit_GFX's own auto-wrap, which breaks at the screen edge mid-
  character (e.g. "emergency" splitting into "emergenc"/"y" -- seen live
  in an early real-hardware photo before this existed), and shows a
  relative "Xm ago" timestamp instead of a wall clock (a real clock would
  need NTP, deliberately not run on this device otherwise -- see the
  WiFi/mDNS/OTA section above). A boot screen (drawBootScreen(), shown
  once in setup() before RX/TX/WiFi come up) shows "LoRaPager" in large
  text plus this unit's own capcode and frequency.

  All of this is compile-verified only -- the icon pixel math (drawn from
  the real Adafruit_GFX_Library's own drawCircleHelper()/drawRoundRect()
  source to get the quadrant bitmask right, not guessed) has never been
  seen on an actual OLED. First real flash should confirm the icons render
  where intended and don't clip/overlap the title or "ago" text before
  trusting this description over what the screen actually shows.

  ---- Addressing (POCSAG-style capcodes) ----
  Every frame is a JSON envelope, {"from":<capcode>,"to":<capcode>,
  "text":"..."} -- same convention pocsag_companion.ino's own serial
  protocol already uses, reused deliberately rather than a hand-rolled
  binary layout (self-describing, and ArduinoJson is already a
  dependency here). A capcode is just a plain integer.

  This device answers to every address in MY_CAPCODES (its own personal
  number, plus optionally one or more group/team addresses -- a single
  pager can belong to more than one group at once), plus every shared
  EMERGENCY_CAPCODES address (911 US / 112 EU -- broadcasts everyone
  should see regardless of group membership) -- it only surfaces a
  received message whose "to" matches one of those. Sending stamps
  MY_CAPCODES[0] (the first entry -- the personal number, by convention,
  not a group address) as "from" and SEND_TO_CAPCODE (this box's own
  radio.pager_capcode -- the base station this pager reports back to)
  as "to".

  Unlike the radio parameters above (genuinely fixed per deployment),
  MY_CAPCODES and SEND_TO_CAPCODE are DELIBERATELY NOT meant to be hand-
  edited here -- each physical pager needs its own identity/group
  membership, so these are placeholders rewritten at compile time by
  Configuration -> Firmware's Pager client card (a "Capcodes to program"
  field, comma-separated, feeds MY_CAPCODES; SEND_TO_CAPCODE comes from
  this box's already-configured radio.pager_capcode automatically). See
  src/api/routes/pager_firmware_routes.py's _rewrite_my_capcodes()/
  _rewrite_send_to_capcode(). A manual compile without going through
  that dashboard flow keeps whatever value was last injected (or the
  placeholder below, on a fresh checkout).
*/

#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>

#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#include <RadioLib.h>
#include <ArduinoJson.h> // v7.4.3 -- JsonDocument/deserializeJson v7 API,
                          // same version pocsag_companion.ino uses

#include <WiFi.h>
#include <ESPmDNS.h>
#include <ArduinoOTA.h>
#include <AsyncTCP.h>
#include <ESPAsyncWebServer.h>
#include <freertos/semphr.h>
#include <Preferences.h> // ESP32 core, NVS-backed key/value store -- persists
                          // the web password + WiFi credentials across reboots
#include "secrets.h" // gitignored -- WIFI_SSID/WIFI_PASSWORD/OTA_PASSWORD/WEB_PASSWORD, see that file

// ---------- WiFi / mDNS / OTA / web dashboard tuning knobs (see header comment) ----------
#define WIFI_CONNECT_TIMEOUT_MS 10000UL // bounded -- never hang core RX/TX waiting on WiFi that isn't there
#define WEB_LOG_SIZE 40                 // ring buffer size backing the web UI's log card
#define PREFS_NAMESPACE "pager"         // NVS namespace for web password + WiFi credentials + screen timeout
#define REBOOT_DELAY_MS 500UL           // lets an HTTP reply actually flush before ESP.restart()
#define DISPLAY_TIMEOUT_MS_DEFAULT 10000UL // startup value for the runtime displayTimeoutMs
                                   // below (settable live from the web UI's "Screen Timeout"
                                   // card, 0 = never blank) -- same default pocsag_companion.ino uses

// ---------- Radio parameters (see header comment for why each value) ----------
#define PAGER_FREQ_MHZ        869.4625f
#define PAGER_BITRATE_KBPS    4.8f
#define PAGER_FREQ_DEV_KHZ    25.0f
#define PAGER_RX_BANDWIDTH_KHZ 125.0f
#define PAGER_TX_POWER_DBM    14
#define PAGER_PREAMBLE_BITS   16

// 0x946437, MSB first -- matches src/capture/concentrator_source.py's
// PAGER_FSK_SYNC_WORD as a raw byte sequence (uint64_t "ALIGN RIGHT" per
// the HAL header, i.e. plain big-endian for a 3-byte value).
uint8_t PAGER_SYNC_WORD[3] = { 0x94, 0x64, 0x37 };

// ---------- Hardware pins (Heltec WiFi LoRa32 V3) ----------
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

// ---------- Capcodes (see header comment's "Addressing" section) ----------
// Placeholders -- rewritten at compile time by Configuration -> Firmware's
// Pager client card ("Capcodes to program", comma-separated), NOT meant
// to be hand-edited (see header comment). More than one lets a single
// unit belong to a personal number plus one or more group/team addresses
// (e.g. a squad capcode) at once -- the FIRST entry is used as "from"
// when this device sends.
const uint32_t MY_CAPCODES[] = { 123456UL };
const int NUM_MY_CAPCODES = sizeof(MY_CAPCODES) / sizeof(MY_CAPCODES[0]);
const uint32_t SEND_TO_CAPCODE = 654321UL;

// Shared broadcast addresses every pager listens on regardless of its own
// personal capcode -- 911 (US) and 112 (EU) emergency numbers. Genuinely
// fixed (not per-unit), so these stay hand-edited here rather than
// dashboard-injected, unlike MY_CAPCODE/SEND_TO_CAPCODE above.
const uint32_t EMERGENCY_CAPCODES[] = { 911, 112 };
const int NUM_EMERGENCY_CAPCODES = sizeof(EMERGENCY_CAPCODES) / sizeof(EMERGENCY_CAPCODES[0]);

// ---------- Canned messages ----------
// Placeholder wording -- easy to edit/extend, not a fixed protocol. Kept
// short: the JSON envelope adds overhead on top of this text, and the
// concentrator's own HAL caps a single FSK frame at 255 bytes total.
const char* CANNED_MESSAGES[] = {
  "OK",
  "On my way",
  "Call me",
  "All clear",
  "Emergency - need help",
};
const int NUM_CANNED = sizeof(CANNED_MESSAGES) / sizeof(CANNED_MESSAGES[0]);

// ---------- Button state machine ----------
enum PagerUiState { STATE_IDLE, STATE_MENU };
PagerUiState uiState = STATE_IDLE;
int cannedIndex = 0;

const unsigned long LONG_PRESS_MS   = 700;
const unsigned long MENU_TIMEOUT_MS = 8000;
const unsigned long DEBOUNCE_MS     = 30;

bool lastRawReading   = HIGH;   // active-low: HIGH = released, LOW = pressed
bool debouncedPressed = false;
unsigned long lastEdgeMs    = 0;
unsigned long pressStartMs  = 0;
bool longPressFired    = false;
unsigned long menuActivityMs = 0;

// ---------- Display power ----------
//
// Ported from pocsag_companion.ino's own display-power section: the OLED
// was staying on indefinitely, not great for a battery-powered pager sitting
// in a pocket. Auto-blanks via the panel's own real DISPLAYOFF command (not
// just clearing pixels, so it actually saves power) after displayTimeoutMs
// with no new screen content, and a short button press (see onShortPress())
// wakes it back up rather than being a no-op from idle. Every drawIdle()/
// drawMenu() call routes through wakeDisplay() first, so any real screen
// update both wakes the panel if it was off and resets the idle timer --
// callers don't need to think about display power at all.

bool displayOn = true;
unsigned long lastDisplayActivity = 0;
// Runtime-settable (starts at DISPLAY_TIMEOUT_MS_DEFAULT, changeable live from
// the web UI's "Screen Timeout" card via POST /api/timeout, persisted in NVS
// the same way webPassword/wifiSsid are) -- 0 means "never auto-blank."
uint32_t displayTimeoutMs = DISPLAY_TIMEOUT_MS_DEFAULT;

void wakeDisplay() {
  if (!displayOn) {
    display.ssd1306_command(SSD1306_DISPLAYON);
    displayOn = true;
  }
  lastDisplayActivity = millis();
}

// ---------- Last received message ----------
bool hasReceivedMessage = false;
String lastMessageText;
uint32_t lastMessageFrom = 0;
float lastMessageRssi = 0;
unsigned long lastMessageMs = 0; // millis() at receipt, for the idle screen's "Xm ago" footer
int rxCount = 0; // messages actually addressed to us (MY_CAPCODES/EMERGENCY_CAPCODES) --
                  // not every frame heard on the channel, same "forMe" gate as the OLED path
// Set whenever a message arrives, cleared the moment drawIdle() actually
// shows it -- since handleReceivedPacket() already redraws idle
// immediately when a message arrives while STATE_IDLE, this is really
// only ever true for more than an instant in ONE case: a message arriving
// while STATE_MENU, which deliberately does NOT interrupt the menu (see
// header comment) -- the topbar's envelope icon is the one place that
// pending message becomes visible before returning to idle.
bool hasUnseenMessage = false;

// ---------- RX interrupt flag ----------
volatile bool rxFlag = false;
void onRadioAction() { rxFlag = true; }

// ---------- WiFi / mDNS / OTA / web dashboard state ----------
//
// Same cross-task discipline pocsag_companion.ino's own web dashboard
// section documents: AsyncWebServer's request/body callbacks run on
// AsyncTCP's own FreeRTOS task, not on loop()'s thread -- loop() is the
// only thread that may ever touch `radio`, so a web-triggered send only
// ever stages a request (queueWebSend()) for loop() to pick up
// (checkWebSendPending()) and actually run itself. webLog[] and the NVS-
// backed String settings below are read on the web task and written on
// loop()'s thread (or vice versa), so all access to them goes through
// stateMutex.

bool wifiConnected = false;
String mdnsHostname; // "pager-<MY_CAPCODES[0]>", computed once in setup()
                      // once the (possibly dashboard-injected) capcode is known

AsyncWebServer server(80);
SemaphoreHandle_t stateMutex;

struct LogEntry {
  uint32_t capcode; // the OTHER party -- "from" for rx, "to" for tx
  String text;
  String dir; // "rx" | "tx"
  unsigned long ts; // millis() when logged
};
LogEntry webLog[WEB_LOG_SIZE];
int webLogHead = 0;  // next slot to write
int webLogCount = 0; // how many of the ring's slots are populated so far

void pushWebLog(uint32_t capcode, const String &text, const String &dir) {
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  LogEntry &e = webLog[webLogHead];
  e.capcode = capcode;
  e.text = text;
  e.dir = dir;
  e.ts = millis();
  webLogHead = (webLogHead + 1) % WEB_LOG_SIZE;
  if (webLogCount < WEB_LOG_SIZE) webLogCount++;
  xSemaphoreGive(stateMutex);
}

// Web-triggered TX handoff -- see the section comment above for why this
// exists instead of just calling sendMessage() from the web handler.
volatile bool webSendPending = false;
String webSendText;

bool queueWebSend(const String &text) {
  bool queued = false;
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  if (!webSendPending) {
    webSendText = text;
    webSendPending = true;
    queued = true;
  }
  xSemaphoreGive(stateMutex);
  return queued;
}

bool rebootRequested = false;
unsigned long rebootRequestedAt = 0;

// Web dashboard login password -- starts as the secrets.h compile-time
// default (WEB_PASSWORD), overridable at runtime via NVS the same way
// pocsag_companion.ino's own is, so a changed password survives a reboot.
Preferences prefs;
String webPassword = WEB_PASSWORD;

String getWebPassword() {
  String p;
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  p = webPassword;
  xSemaphoreGive(stateMutex);
  return p;
}

void setWebPassword(const String &newPassword) {
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  webPassword = newPassword;
  xSemaphoreGive(stateMutex);
}

// WiFi credentials -- start as the secrets.h compile-time defaults,
// overridable at runtime via NVS. Unlike webPassword above, a change here
// does NOT take effect immediately: setupWifiOta() only ever runs once, in
// setup(), so a new SSID/password needs a reboot to actually connect with
// (see /api/reboot).
String wifiSsid = WIFI_SSID;
String wifiPass = WIFI_PASSWORD;

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

void setWifiCredentials(const String &ssid, const String &pass) {
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  wifiSsid = ssid;
  wifiPass = pass;
  xSemaphoreGive(stateMutex);
}

// Arduino's auto-prototype generator (a brace-counting heuristic, not a
// real parser) loses track of scope inside the web dashboard section's raw
// HTML/CSS/JS string literal further down this file, so it fails to
// auto-declare anything defined after that point -- same issue
// pocsag_companion.ino's own forward-declarations section documents.
// setup()/loop() above call these, so they need explicit prototypes here.
void setupWifiOta();
void setupWebServer();
void checkWebSendPending();

void setup() {
  Serial.begin(115200);
  delay(500);

  // OLED power rail: must happen before Wire.begin()/display.begin(), or
  // the screen stays dark even though the rest of setup() succeeds (see
  // header comment -- this exact bug already cost real debugging time on
  // pocsag_companion.ino's own Heltec V3 build).
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

  ConfigFSK_t cfg;
  cfg.frequency = PAGER_FREQ_MHZ;
  cfg.bitRate = PAGER_BITRATE_KBPS;
  cfg.frequencyDeviation = PAGER_FREQ_DEV_KHZ;
  cfg.receiverBandwidth = PAGER_RX_BANDWIDTH_KHZ;
  cfg.power = PAGER_TX_POWER_DBM;
  cfg.preambleLength = PAGER_PREAMBLE_BITS;

  int state = radio.beginFSK(cfg);
  if (state != RADIOLIB_ERR_NONE) {
    Serial.printf("[!] Radio init failed: %d\n", state);
    display.clearDisplay();
    display.setCursor(0, 0);
    display.printf("Radio init\nfailed: %d", state);
    display.display();
    while (true) delay(1000);
  }

  radio.setSyncWord(PAGER_SYNC_WORD, sizeof(PAGER_SYNC_WORD));
  // 2-byte CRC, RadioLib's default CCITT polynomial (0x1021) -- confirmed
  // to match the concentrator's own CRC_IBM=0 ("CCITT CRC") choice; see
  // header comment for what's confirmed vs. a best-guess default.
  radio.setCRC(2);
  radio.setEncoding(RADIOLIB_ENCODING_WHITENING);
  radio.setDataShaping(RADIOLIB_SHAPING_0_5);

  radio.setPacketReceivedAction(onRadioAction);
  state = radio.startReceive();
  if (state != RADIOLIB_ERR_NONE) {
    Serial.printf("[!] startReceive failed: %d\n", state);
  }

  Serial.println("[*] Pager client ready");
  Serial.printf("[*] %.4f MHz, %.1f kbps, sync 0x%02X%02X%02X\n",
                PAGER_FREQ_MHZ, PAGER_BITRATE_KBPS,
                PAGER_SYNC_WORD[0], PAGER_SYNC_WORD[1], PAGER_SYNC_WORD[2]);

  stateMutex = xSemaphoreCreateMutex(); // guards webLog[]/webSend*/webPassword/wifi creds -- see that section's own comment
  prefs.begin(PREFS_NAMESPACE, false);
  setWebPassword(prefs.getString("web_password", WEB_PASSWORD));
  setWifiCredentials(
    prefs.getString("wifi_ssid", WIFI_SSID),
    prefs.getString("wifi_pass", WIFI_PASSWORD)
  );
  // Plain uint32_t read/write is effectively atomic on ESP32 for this
  // purpose, no mutex needed the way the String-based settings above
  // genuinely require one -- same reasoning pocsag_companion.ino's own
  // displayTimeoutMs uses.
  displayTimeoutMs = prefs.getUInt("dispTimeoutMs", DISPLAY_TIMEOUT_MS_DEFAULT);
  lastDisplayActivity = millis();
  mdnsHostname = "pager-" + String(MY_CAPCODES[0]); // per-unit, so more than
                                                      // one pager on the same
                                                      // network doesn't collide
  setupWifiOta(); // best-effort, bounded timeout -- see header comment

  drawIdle();
}

void loop() {
  checkButton();

  if (rxFlag) {
    rxFlag = false;
    handleReceivedPacket();
  }

  if (uiState == STATE_MENU && millis() - menuActivityMs > MENU_TIMEOUT_MS) {
    uiState = STATE_IDLE;
    drawIdle();
  }

  if (wifiConnected) ArduinoOTA.handle();
  checkWebSendPending(); // picks up a send staged by the web UI's /api/send
                          // handler -- see queueWebSend()'s own comment for
                          // why the handoff, not a direct call, is required

  if (rebootRequested && millis() - rebootRequestedAt >= REBOOT_DELAY_MS) {
    ESP.restart();
  }

  if (displayOn && displayTimeoutMs > 0 && millis() - lastDisplayActivity >= displayTimeoutMs) {
    display.ssd1306_command(SSD1306_DISPLAYOFF);
    displayOn = false;
  }
}

void handleReceivedPacket() {
  size_t len = radio.getPacketLength();
  if (len == 0 || len > 255) {
    radio.startReceive();
    return;
  }

  uint8_t buf[256];
  int state = radio.readData(buf, len);
  if (state == RADIOLIB_ERR_NONE) {
    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, buf, len);
    if (err) {
      // Not a valid envelope -- foreign noise on the channel, or (before
      // this capcode work) an old plain-text test frame. Same "fails to
      // parse, gets dropped" reasoning as the dashboard's own adapter.
      Serial.printf("[!] RX JSON parse failed: %s\n", err.c_str());
      radio.startReceive();
      return;
    }

    uint32_t to = doc["to"] | 0;
    uint32_t from = doc["from"] | 0;
    const char* text = doc["text"] | "";

    bool forMe = false;
    for (int i = 0; i < NUM_MY_CAPCODES; i++) {
      if (to == MY_CAPCODES[i]) { forMe = true; break; }
    }
    if (!forMe) {
      for (int i = 0; i < NUM_EMERGENCY_CAPCODES; i++) {
        if (to == EMERGENCY_CAPCODES[i]) { forMe = true; break; }
      }
    }
    if (!forMe) {
      Serial.printf("[RX] ignored (to=%lu, not one of ours)\n", (unsigned long)to);
      radio.startReceive();
      return;
    }

    lastMessageText = String(text);
    lastMessageFrom = from;
    lastMessageRssi = radio.getRSSI();
    lastMessageMs = millis();
    hasReceivedMessage = true;
    hasUnseenMessage = true;
    rxCount++;
    Serial.printf("[RX] from=%lu to=%lu \"%s\" rssi=%.1f\n",
                  (unsigned long)from, (unsigned long)to, text, lastMessageRssi);
    pushWebLog(from, lastMessageText, "rx");

    // "Leaning toward wait" -- don't yank the menu away if the operator is
    // mid-selection; the new message still shows the moment they return to
    // idle (either via timeout or by sending/cancelling).
    if (uiState == STATE_IDLE) drawIdle();
  } else {
    Serial.printf("[!] readData failed: %d\n", state);
  }

  radio.startReceive();
}

// Shared by the physical button's canned-message send (sendCannedMessage()
// below) and the web dashboard's free-text /api/send (via
// checkWebSendPending()) -- one place that actually touches the radio for
// TX, so both paths log/behave identically. Only ever called from loop()'s
// thread (see the WiFi/web dashboard state section's own comment for why
// that matters).
void sendMessage(const String &text) {
  JsonDocument doc;
  doc["from"] = MY_CAPCODES[0]; // primary/personal number, not a group address
  doc["to"] = SEND_TO_CAPCODE;
  doc["text"] = text;
  char buf[256];
  size_t len = serializeJson(doc, buf, sizeof(buf));

  int state = radio.transmit((uint8_t*)buf, len);
  Serial.printf("[TX] from=%lu to=%lu \"%s\" -> %s\n",
                (unsigned long)MY_CAPCODES[0], (unsigned long)SEND_TO_CAPCODE,
                text.c_str(), state == RADIOLIB_ERR_NONE ? "OK" : "FAIL");
  if (state == RADIOLIB_ERR_NONE) pushWebLog(SEND_TO_CAPCODE, text, "tx");
  // transmit() leaves the radio in TX/idle state -- must explicitly go
  // back to RX or every message sent would also deafen this device to
  // anything arriving afterward.
  radio.startReceive();
}

void sendCannedMessage(int idx) {
  sendMessage(String(CANNED_MESSAGES[idx]));
}

// ---------- Button: debounce + short/long press detection ----------
//
// Long-press fires as soon as the hold duration crosses LONG_PRESS_MS
// (while still held), not on release -- gives immediate feedback and lets
// short-press fire cleanly on release only when long-press never fired
// this cycle. Same 30ms debounce window style as pocsag_companion.ino's
// own checkButton(), just extended to track press duration too.
void checkButton() {
  bool reading = digitalRead(BUTTON_GPIO);
  if (reading != lastRawReading) {
    lastEdgeMs = millis();
    lastRawReading = reading;
  }

  if (millis() - lastEdgeMs > DEBOUNCE_MS) {
    bool pressed = (reading == LOW);
    if (pressed && !debouncedPressed) {
      // just pressed
      debouncedPressed = true;
      pressStartMs = millis();
      longPressFired = false;
    } else if (!pressed && debouncedPressed) {
      // just released
      debouncedPressed = false;
      if (!longPressFired) onShortPress();
    } else if (pressed && debouncedPressed && !longPressFired
               && millis() - pressStartMs >= LONG_PRESS_MS) {
      longPressFired = true;
      onLongPress();
    }
  }
}

void onShortPress() {
  if (uiState == STATE_MENU) {
    cannedIndex = (cannedIndex + 1) % NUM_CANNED;
    menuActivityMs = millis();
    drawMenu();
  } else {
    // Short press from idle: still no menu action (long-hold is the only
    // way into the menu) -- but this now wakes the screen if it had
    // auto-blanked, or just resets the idle timer if it was already on.
    // drawIdle() routes through wakeDisplay() internally, so this one call
    // handles both cases.
    drawIdle();
  }
}

void onLongPress() {
  if (uiState == STATE_IDLE) {
    uiState = STATE_MENU;
    cannedIndex = 0;
    menuActivityMs = millis();
    drawMenu();
  } else {
    sendCannedMessage(cannedIndex);
    uiState = STATE_IDLE;
    drawIdle();
  }
}

// ---------- OLED ----------
//
// Small vector icons (WiFi status, new-message) built from Adafruit_GFX
// primitives rather than a bitmap asset -- no extra tooling/flash needed
// for a couple of 8x8px glyphs. drawCircleHelper()'s cornername bitmask
// (confirmed against the real installed Adafruit_GFX_Library's own
// drawRoundRect(), which draws each of the 4 corners with a known mask):
// 0x1 = upper-left quadrant, 0x2 = upper-right -- combined (0x3) draws
// just the top arc, the classic "wifi bars" look, anchored on a dot at
// the bottom of the icon's 8x8 box.

void drawWifiIcon(int x, int y, bool connected) {
  int cx = x + 4;
  int cy = y + 7;
  display.fillCircle(cx, cy, 1, SSD1306_WHITE);
  if (connected) {
    display.drawCircleHelper(cx, cy, 2, 0x3, SSD1306_WHITE);
    display.drawCircleHelper(cx, cy, 4, 0x3, SSD1306_WHITE);
  }
}

// Outline rectangle + a flap (two diagonals meeting at bottom-center).
// Only ever called when there's actually something to signal (see
// hasUnseenMessage) -- no separate "no message" variant, the icon area
// is just left blank instead.
void drawEnvelopeIcon(int x, int y) {
  display.drawRect(x, y + 1, 8, 6, SSD1306_WHITE);
  display.drawLine(x, y + 1, x + 4, y + 4, SSD1306_WHITE);
  display.drawLine(x + 8, y + 1, x + 4, y + 4, SSD1306_WHITE);
}

// Shared status row for the idle/menu screens -- title text on the left,
// WiFi + new-message icons fixed at the right edge regardless of title
// length (titles used here are always short; not truncated/measured).
void drawTopBar(const String &title) {
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print(title);
  drawWifiIcon(108, 0, wifiConnected);
  if (hasUnseenMessage) drawEnvelopeIcon(118, 0);
  display.drawFastHLine(0, 9, OLED_WIDTH, SSD1306_WHITE);
}

// Word-wraps `text` into up to maxLines lines of maxCharsPerLine each,
// breaking at the last space within each line instead of Adafruit_GFX's
// own auto-wrap (which breaks at the screen edge mid-character -- e.g.
// "emergency" splitting into "emergenc"/"y"). Falls back to a hard break
// only if a single word alone exceeds maxCharsPerLine. Truncates with
// "..." on the last line if the text doesn't fit in maxLines.
void printWrapped(const String &text, int x, int y, int maxCharsPerLine, int maxLines, int lineHeight) {
  int line = 0;
  int pos = 0;
  int len = text.length();
  while (pos < len && line < maxLines) {
    int remaining = len - pos;
    int take = min(remaining, maxCharsPerLine);
    if (take < remaining) {
      int lastSpace = text.lastIndexOf(' ', pos + take);
      if (lastSpace > pos) take = lastSpace - pos;
    }
    String chunk = text.substring(pos, pos + take);
    bool isLastLine = (line == maxLines - 1);
    if (isLastLine && (pos + take < len)) {
      while (chunk.length() > 0 && (int)chunk.length() + 3 > maxCharsPerLine) {
        chunk.remove(chunk.length() - 1);
      }
      chunk += "...";
    }
    display.setCursor(x, y + line * lineHeight);
    display.print(chunk);
    pos += take;
    while (pos < len && text[pos] == ' ') pos++; // skip the space we broke on
    line++;
  }
}

// "3m ago" style relative timestamp -- deliberately not a wall clock
// (would need NTP, which this device otherwise has no use for and
// intentionally doesn't run -- see the WiFi/mDNS/OTA header comment).
String relativeTimeAgo(unsigned long sinceMs) {
  unsigned long elapsedS = (millis() - sinceMs) / 1000;
  if (elapsedS < 60) return String(elapsedS) + "s ago";
  if (elapsedS < 3600) return String(elapsedS / 60) + "m ago";
  if (elapsedS < 86400) return String(elapsedS / 3600) + "h ago";
  return String(elapsedS / 86400) + "d ago";
}

void drawIdle() {
  wakeDisplay();
  hasUnseenMessage = false; // this IS the "seeing" it -- see the flag's own comment
  display.clearDisplay();
  drawTopBar("PAGER #" + String(MY_CAPCODES[0]));

  display.setCursor(0, 13);
  if (!hasReceivedMessage) {
    display.println("No messages yet");
  } else {
    display.printf("From: %lu", (unsigned long)lastMessageFrom);
    printWrapped(lastMessageText, 0, 23, 21, 3, 8);
    display.setCursor(0, 56);
    display.printf("RSSI %.0fdBm", lastMessageRssi);
    String ago = relativeTimeAgo(lastMessageMs);
    display.setCursor(OLED_WIDTH - ago.length() * 6, 56);
    display.print(ago);
  }
  display.display();
}

void drawMenu() {
  wakeDisplay();
  display.clearDisplay();
  drawTopBar("SEND (hold=send)");

  display.setCursor(0, 16);
  display.println(CANNED_MESSAGES[cannedIndex]);
  display.setCursor(0, 56);
  display.printf("%d/%d", cannedIndex + 1, NUM_CANNED);
  display.display();
}

// Shown once at boot, before RX/TX/WiFi are up -- see setup(). Same
// dark/cyan aesthetic as the rest of this device's screens, just bigger
// text for a moment of real branding instead of a bare "starting..."
// line, matching what a "cool case" deserves.
void drawBootScreen() {
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);

  display.setTextSize(2);
  String title = "LoRaPager";
  int titleW = title.length() * 12; // size-2 glyphs are 12px wide
  display.setCursor((OLED_WIDTH - titleW) / 2, 8);
  display.println(title);

  display.setTextSize(1);
  String cap = "#" + String(MY_CAPCODES[0]);
  display.setCursor((OLED_WIDTH - (int)cap.length() * 6) / 2, 34);
  display.println(cap);

  char freqBuf[20];
  snprintf(freqBuf, sizeof(freqBuf), "%.4f MHz", PAGER_FREQ_MHZ);
  int freqW = strlen(freqBuf) * 6;
  display.setCursor((OLED_WIDTH - freqW) / 2, 46);
  display.println(freqBuf);

  display.display();
}


// ---------- WiFi / mDNS / OTA ----------
//
// All best-effort -- see the header comment for the full rationale. Runs
// once at boot, after the radio's already configured for RX, so a slow/
// failed WiFi connect only adds a bounded delay before "ready", never
// blocks it outright.

void setupWifiOta() {
  String ssid = getWifiSsid();
  String pass = getWifiPassword();

  if (ssid.length() == 0 || ssid == "YOUR_WIFI_SSID") {
    Serial.println("[wifi] no credentials configured, skipping WiFi/OTA/web dashboard");
    return;
  }

  WiFi.mode(WIFI_STA);
  WiFi.setHostname(mdnsHostname.c_str());
  WiFi.begin(ssid.c_str(), pass.c_str());

  Serial.print("[wifi] connecting to "); Serial.print(ssid);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_CONNECT_TIMEOUT_MS) {
    delay(250);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[wifi] connect timed out, continuing RX/TX-only");
    return;
  }

  wifiConnected = true;
  Serial.print("[wifi] connected, IP="); Serial.println(WiFi.localIP());

  if (MDNS.begin(mdnsHostname.c_str())) {
    Serial.print("[mdns] reachable at "); Serial.print(mdnsHostname); Serial.println(".local");
  } else {
    Serial.println("[mdns] begin() failed");
  }

  // Same hostname as WiFi/mDNS above, so "what is this device called on
  // the network" has one answer everywhere, not two different ones.
  ArduinoOTA.setHostname(mdnsHostname.c_str());
  ArduinoOTA.setPassword(OTA_PASSWORD);
  ArduinoOTA.onStart([]() {
    Serial.println("[ota] update starting");
    display.clearDisplay();
    display.setTextSize(1);
    display.setCursor(0, 0);
    display.println("OTA update");
    display.println("starting...");
    display.display();
  });
  ArduinoOTA.onEnd([]() {
    Serial.println("[ota] update complete");
    display.clearDisplay();
    display.setTextSize(1);
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

// Called every loop() pass. Cheap when nothing's pending (one bool check).
void checkWebSendPending() {
  if (!webSendPending) return;
  String text;
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  text = webSendText;
  webSendPending = false;
  xSemaphoreGive(stateMutex);
  sendMessage(text);
}


// ---------- Web dashboard ----------
//
// Small password-gated single-page UI served straight from flash (no
// filesystem, no external assets/fonts/CDN -- this device may only have
// LAN access, not real internet), styled to match meshpoint's own dark
// dashboard theme, same convention pocsag_companion.ino's own web
// dashboard already uses. Every API route (not the static page itself,
// which has nothing sensitive in its shell) requires the X-Auth-Password
// header -- plain string comparison is plenty, this is a LAN-local hobby
// device's login, not a target worth building constant-time comparison for.

bool checkAuth(AsyncWebServerRequest *request) {
  if (!request->hasHeader("X-Auth-Password") ||
      request->getHeader("X-Auth-Password")->value() != getWebPassword()) {
    request->send(401, "application/json", "{\"ok\":false,\"error\":\"unauthorized\"}");
    return false;
  }
  return true;
}

const char INDEX_HTML[] = R"HTMLPAGE(
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Meshpoint Pager</title>
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
  .card h2 { font-size:13px; text-transform:uppercase; letter-spacing:1px; color: var(--text-secondary); margin:0 0 10px 0; }
  #log { height:260px; overflow-y:auto; font-size:12px; display:flex; flex-direction:column; gap:6px; }
  .row { border-left:2px solid var(--border); padding:4px 8px; border-radius:4px; background: rgba(255,255,255,0.02); }
  .row.rx { border-left-color: var(--accent-cyan); }
  .row.tx { border-left-color: var(--accent-green); }
  .row .meta { color: var(--text-muted); font-size:10px; }
  .row .cap { color: var(--accent-amber); }
  .row .txt { color: var(--text-primary); word-break: break-word; }
  label { font-size:11px; color: var(--text-secondary); display:block; margin-bottom:4px; margin-top:10px; }
  input[type=text], input[type=password], input[type=number] {
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
  .hint { font-size:11px; color: var(--text-muted); margin-top:8px; }
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
</style>
</head>
<body>

<div id="authOverlay" class="modal-overlay">
  <div class="card">
    <h2>MESHPOINT PAGER</h2>
    <div id="whoami">--</div>
    <label for="pw">Password</label>
    <input type="password" id="pw" autocomplete="off" spellcheck="false">
    <button onclick="tryLogin()">Unlock</button>
    <div class="result err" id="authErr"></div>
  </div>
</div>

<div id="app" class="hidden">
  <header>
    <h1>MESHPOINT PAGER</h1>
    <div class="status">
      <span><span class="dot" id="wifiDot"></span><span id="hostname">--</span></span>
      <span>RX <span id="rxCount">0</span></span>
    </div>
  </header>

  <div class="grid">
    <div class="card">
      <h2>Status</h2>
      <div class="kv"><span>My capcode(s)</span><span id="myCapcodes">--</span></div>
      <div class="kv"><span>Reports to</span><span id="sendToCapcode">--</span></div>
      <div class="kv"><span>SSID</span><span id="connSsid">--</span></div>
      <div class="kv"><span>IP</span><span id="connIp">--</span></div>
      <div class="kv"><span>RSSI (WiFi)</span><span id="connRssi">--</span></div>
      <div class="kv"><span>Free Heap</span><span id="hwHeap">--</span></div>
      <div class="kv"><span>Uptime</span><span id="uptime">--</span></div>
    </div>

    <div class="card">
      <h2>Last Message</h2>
      <div class="kv"><span>From</span><span id="lastFrom">--</span></div>
      <div class="kv"><span>RSSI</span><span id="lastRssi">--</span></div>
      <div id="lastText" style="font-size:13px; margin-top:8px; word-break:break-word;">(none yet)</div>
    </div>

    <div class="card">
      <h2>In / Outgoing Log</h2>
      <div id="log"></div>
    </div>

    <div class="card">
      <h2>Send</h2>
      <label for="text">Message (to <span id="sendToHint">--</span>)</label>
      <input type="text" id="text" placeholder="Message text" maxlength="200">
      <button id="sendBtn" onclick="sendPage()">Send</button>
      <div class="result" id="sendResult"></div>
    </div>

    <div class="card">
      <h2>WiFi Credentials</h2>
      <label for="wifiSsid">SSID</label>
      <input type="text" id="wifiSsid" placeholder="Network name">
      <label for="wifiPass">Password</label>
      <input type="password" id="wifiPass" placeholder="Leave blank to keep current">
      <button onclick="saveWifi()">Save (needs reboot to apply)</button>
      <div class="result" id="wifiResult"></div>
      <button class="secondary" onclick="rebootNow()">Reboot Now</button>
      <div class="result" id="rebootResult"></div>
    </div>

    <div class="card">
      <h2>Screen Timeout</h2>
      <label for="timeout">Seconds idle before auto-off (0 = never)</label>
      <input type="number" id="timeout" min="0" step="1">
      <button onclick="applyTimeout()">Apply</button>
      <div class="result" id="timeoutResult"></div>
      <div class="hint">A short press on the physical button also wakes the screen manually at any time.</div>
    </div>
  </div>
</div>

<script>
let pw = sessionStorage.getItem('pagerPw') || '';
let timeoutTouched = false;

// Unauthenticated -- shown on the login screen itself, before a password
// is entered. Neither field is sensitive: capcode is a public POCSAG-style
// address by definition, hostname is already broadcast in the clear via
// mDNS anyway.
fetch('/api/whoami').then(r => r.json()).then(d => {
  document.getElementById('whoami').textContent = 'Capcode ' + d.capcode + ' · ' + d.hostname + '.local';
}).catch(() => {});

function authHeaders() { return { 'X-Auth-Password': pw }; }

async function checkAuthOk() {
  try {
    const r = await fetch('/api/status', { headers: authHeaders() });
    return r.ok;
  } catch (e) { return false; }
}

async function tryLogin() {
  pw = document.getElementById('pw').value;
  const ok = await checkAuthOk();
  if (ok) {
    sessionStorage.setItem('pagerPw', pw);
    enterApp();
  } else {
    document.getElementById('authErr').textContent = 'Wrong password';
  }
}

function enterApp() {
  document.getElementById('authOverlay').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
  pollStatus();
  pollLog();
  setInterval(pollStatus, 5000);
  setInterval(pollLog, 3000);
}

async function apiGet(path) {
  const r = await fetch(path, { headers: authHeaders() });
  if (r.status === 401) { sessionStorage.removeItem('pagerPw'); location.reload(); throw new Error('unauthorized'); }
  return r.json();
}

async function apiPost(path, body) {
  const r = await fetch(path, {
    method: 'POST',
    headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
    body: JSON.stringify(body)
  });
  if (r.status === 401) { sessionStorage.removeItem('pagerPw'); location.reload(); throw new Error('unauthorized'); }
  return r.json();
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function fmtRow(e) {
  const secsAgo = Math.round(e.ms_ago / 1000);
  return '<div class="row ' + e.dir + '">' +
    '<div class="meta">' + e.dir.toUpperCase() + ' · ' + secsAgo + 's ago</div>' +
    '<div><span class="cap">#' + e.capcode + '</span> <span class="txt">' + escapeHtml(e.text || '(no text)') + '</span></div>' +
    '</div>';
}

async function pollLog() {
  try {
    const entries = await apiGet('/api/log'); // oldest-first from the server
    const log = document.getElementById('log');
    const atTop = log.scrollTop <= 10;
    log.innerHTML = entries.slice().reverse().map(fmtRow).join('');
    if (atTop) log.scrollTop = 0;
  } catch (e) {}
}

async function pollStatus() {
  try {
    const s = await apiGet('/api/status');
    document.getElementById('hostname').textContent = s.hostname;
    document.getElementById('wifiDot').className = 'dot ' + (s.wifi ? 'on' : 'off');
    document.getElementById('rxCount').textContent = s.rxCount;
    document.getElementById('myCapcodes').textContent = s.myCapcodes.join(', ');
    document.getElementById('sendToCapcode').textContent = s.sendToCapcode;
    document.getElementById('sendToHint').textContent = s.sendToCapcode;
    document.getElementById('connSsid').textContent = s.wifiSsid || '--';
    document.getElementById('connIp').textContent = s.wifiIp || '--';
    document.getElementById('connRssi').textContent = s.wifi ? (s.wifiRssi + ' dBm') : '--';
    document.getElementById('hwHeap').textContent = Math.round(s.freeHeap / 1024) + ' KB free';
    document.getElementById('uptime').textContent = Math.round(s.uptimeMs / 60000) + ' min';
    if (s.hasLastMessage) {
      document.getElementById('lastFrom').textContent = s.lastFrom;
      document.getElementById('lastRssi').textContent = s.lastRssi + ' dBm';
      document.getElementById('lastText').textContent = s.lastText;
    }
    if (!document.getElementById('wifiSsid').value) document.getElementById('wifiSsid').value = s.wifiSsid || '';
    if (!timeoutTouched) document.getElementById('timeout').value = Math.round(s.displayTimeoutMs / 1000);
  } catch (e) {}
}

async function sendPage() {
  const textInput = document.getElementById('text');
  const btn = document.getElementById('sendBtn');
  const result = document.getElementById('sendResult');
  const text = textInput.value.trim();
  if (!text) { result.className = 'result err'; result.textContent = 'Enter a message'; return; }
  btn.disabled = true;
  result.className = 'result'; result.textContent = 'Sending...';
  try {
    const r = await apiPost('/api/send', { text });
    if (r.ok) {
      result.className = 'result ok'; result.textContent = 'Queued';
      textInput.value = '';
      setTimeout(pollLog, 1500);
    } else {
      result.className = 'result err'; result.textContent = r.error || 'Failed';
    }
  } catch (e) {
    result.className = 'result err'; result.textContent = 'Request failed';
  }
  btn.disabled = false;
}

async function saveWifi() {
  const ssid = document.getElementById('wifiSsid').value.trim();
  const pass = document.getElementById('wifiPass').value;
  const result = document.getElementById('wifiResult');
  if (!ssid) { result.className = 'result err'; result.textContent = 'SSID is required'; return; }
  try {
    const r = await apiPost('/api/wifi', { ssid, password: pass });
    result.className = r.ok ? 'result ok' : 'result err';
    result.textContent = r.ok ? 'Saved -- reboot to apply' : (r.error || 'Failed');
  } catch (e) {
    result.className = 'result err'; result.textContent = 'Request failed';
  }
}

async function rebootNow() {
  const result = document.getElementById('rebootResult');
  result.className = 'result'; result.textContent = 'Rebooting...';
  try {
    await apiPost('/api/reboot', {});
  } catch (e) {
    // Expected -- the device drops the connection as it restarts.
  }
  result.className = 'result ok';
  result.textContent = 'Reconnecting...';
  setTimeout(() => location.reload(), 6000);
}

async function applyTimeout() {
  const seconds = parseInt(document.getElementById('timeout').value, 10) || 0;
  const result = document.getElementById('timeoutResult');
  try {
    const r = await apiPost('/api/timeout', { ms: seconds * 1000 });
    result.className = r.ok ? 'result ok' : 'result err';
    result.textContent = r.ok ? 'Saved' : (r.error || 'Failed');
    timeoutTouched = false;
  } catch (e) {
    result.className = 'result err'; result.textContent = 'Request failed';
  }
}

document.getElementById('timeout').addEventListener('input', () => timeoutTouched = true);
document.getElementById('pw').addEventListener('keydown', e => { if (e.key === 'Enter') tryLogin(); });

if (pw) checkAuthOk().then(ok => { if (ok) enterApp(); });
</script>
</body>
</html>
)HTMLPAGE";

void setupWebServer() {
  server.on("/", HTTP_GET, [](AsyncWebServerRequest *request) {
    request->send(200, "text/html", INDEX_HTML);
  });

  // Deliberately NOT gated by checkAuth() -- shown on the login screen
  // itself, before a password is entered. Neither field is sensitive: a
  // capcode is a public POCSAG-style address by definition, hostname is
  // already broadcast in the clear via mDNS anyway.
  server.on("/api/whoami", HTTP_GET, [](AsyncWebServerRequest *request) {
    JsonDocument doc;
    doc["capcode"] = MY_CAPCODES[0];
    doc["hostname"] = mdnsHostname;
    String json;
    serializeJson(doc, json);
    request->send(200, "application/json", json);
  });

  server.on("/api/status", HTTP_GET, [](AsyncWebServerRequest *request) {
    if (!checkAuth(request)) return;
    JsonDocument doc;
    doc["ok"] = true;
    doc["hostname"] = mdnsHostname;
    doc["wifi"] = wifiConnected;
    doc["rxCount"] = rxCount;
    doc["sendToCapcode"] = SEND_TO_CAPCODE;
    JsonArray caps = doc["myCapcodes"].to<JsonArray>();
    for (int i = 0; i < NUM_MY_CAPCODES; i++) caps.add(MY_CAPCODES[i]);

    doc["hasLastMessage"] = hasReceivedMessage;
    if (hasReceivedMessage) {
      doc["lastFrom"] = lastMessageFrom;
      doc["lastText"] = lastMessageText;
      doc["lastRssi"] = lastMessageRssi;
    }

    doc["freeHeap"] = ESP.getFreeHeap();
    doc["uptimeMs"] = millis();
    doc["displayTimeoutMs"] = displayTimeoutMs;

    doc["wifiSsid"] = wifiConnected ? WiFi.SSID() : "";
    doc["wifiIp"] = wifiConnected ? WiFi.localIP().toString() : "";
    doc["wifiRssi"] = wifiConnected ? WiFi.RSSI() : 0;

    String json;
    serializeJson(doc, json);
    request->send(200, "application/json", json);
  });

  server.on("/api/log", HTTP_GET, [](AsyncWebServerRequest *request) {
    if (!checkAuth(request)) return;
    JsonDocument doc;
    JsonArray arr = doc.to<JsonArray>();
    unsigned long now = millis();
    xSemaphoreTake(stateMutex, portMAX_DELAY);
    int start = (webLogHead - webLogCount + WEB_LOG_SIZE) % WEB_LOG_SIZE;
    for (int i = 0; i < webLogCount; i++) {
      int idx = (start + i) % WEB_LOG_SIZE;
      JsonObject o = arr.add<JsonObject>();
      o["capcode"] = webLog[idx].capcode;
      o["text"] = webLog[idx].text;
      o["dir"] = webLog[idx].dir;
      o["ms_ago"] = now - webLog[idx].ts;
    }
    xSemaphoreGive(stateMutex);
    String json;
    serializeJson(doc, json);
    request->send(200, "application/json", json);
  });

  server.on("/api/send", HTTP_POST, [](AsyncWebServerRequest *request) {
    // Body is handled by the callback below; nothing to do on the
    // "request known, body not yet received" pass.
  }, nullptr, [](AsyncWebServerRequest *request, uint8_t *data, size_t len, size_t index, size_t total) {
    if (!checkAuth(request)) return;
    JsonDocument doc;
    if (deserializeJson(doc, data, len)) {
      request->send(400, "application/json", "{\"ok\":false,\"error\":\"bad json\"}");
      return;
    }
    String text = doc["text"] | "";
    text.trim();
    if (text.length() == 0) {
      request->send(400, "application/json", "{\"ok\":false,\"error\":\"text is required\"}");
      return;
    }
    if (!queueWebSend(text)) {
      request->send(429, "application/json", "{\"ok\":false,\"error\":\"a send is already in progress\"}");
      return;
    }
    // Queued, not yet transmitted -- loop() runs the actual send shortly
    // after this returns (see checkWebSendPending()); the log card will
    // show it once it lands.
    request->send(202, "application/json", "{\"ok\":true,\"queued\":true}");
  });

  server.on("/api/timeout", HTTP_POST, [](AsyncWebServerRequest *request) {
  }, nullptr, [](AsyncWebServerRequest *request, uint8_t *data, size_t len, size_t index, size_t total) {
    if (!checkAuth(request)) return;
    JsonDocument doc;
    if (deserializeJson(doc, data, len)) {
      request->send(400, "application/json", "{\"ok\":false,\"error\":\"bad json\"}");
      return;
    }
    long ms = doc["ms"] | -1;
    if (ms < 0 || ms > 24UL * 60 * 60 * 1000) { // 0 = disabled, up to 24h
      request->send(400, "application/json", "{\"ok\":false,\"error\":\"ms out of range (0-86400000)\"}");
      return;
    }
    displayTimeoutMs = (uint32_t)ms;
    prefs.putUInt("dispTimeoutMs", displayTimeoutMs);
    if (displayTimeoutMs > 0) lastDisplayActivity = millis(); // don't blank immediately on a fresh, longer setting
    request->send(200, "application/json", "{\"ok\":true}");
  });

  server.on("/api/wifi", HTTP_POST, [](AsyncWebServerRequest *request) {
  }, nullptr, [](AsyncWebServerRequest *request, uint8_t *data, size_t len, size_t index, size_t total) {
    if (!checkAuth(request)) return;
    JsonDocument doc;
    if (deserializeJson(doc, data, len)) {
      request->send(400, "application/json", "{\"ok\":false,\"error\":\"bad json\"}");
      return;
    }
    String ssid = doc["ssid"] | "";
    String pass = doc["password"] | ""; // empty is valid -- open networks have no password
    ssid.trim();
    if (ssid.length() == 0) {
      request->send(400, "application/json", "{\"ok\":false,\"error\":\"ssid is required\"}");
      return;
    }
    setWifiCredentials(ssid, pass);
    prefs.putString("wifi_ssid", ssid);
    prefs.putString("wifi_pass", pass);
    request->send(200, "application/json", "{\"ok\":true}");
  });

  server.on("/api/reboot", HTTP_POST, [](AsyncWebServerRequest *request) {
    if (!checkAuth(request)) return;
    Serial.println("[web] reboot requested via dashboard");
    request->send(200, "application/json", "{\"ok\":true}");
    rebootRequested = true;
    rebootRequestedAt = millis(); // loop() does the actual ESP.restart() -- see its own comment
  });

  server.begin();
  Serial.print("[web] dashboard ready at http://"); Serial.print(mdnsHostname); Serial.println(".local/");
}
