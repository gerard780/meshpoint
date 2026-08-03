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
  endpoint or a provisioning step, mirroring how pocsag_companion.ino has its
  own WiFi dashboard) instead of hardcoding, but that's explicitly deferred --
  hardcoded is simplest to get a first working link, and needs no WiFi
  credentials/network access on this device at all.

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

  ---- Status: UNTESTED ON REAL HARDWARE ----
  Compile-verified only (arduino-cli, esp32:esp32:heltec_wifi_lora_32_V3,
  RadioLib 7.7.1). Everything about the button UX, OLED layout, and the
  RadioLib FSK RX/TX calls themselves needs a real flash + real over-the-air
  test against the concentrator (which has already round-trip self-tested
  its own TX->RX loopback live, per project memory -- this is the first test
  with a genuinely separate second radio).

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

  ---- Addressing (POCSAG-style capcodes) ----
  Every frame is a JSON envelope, {"from":<capcode>,"to":<capcode>,
  "text":"..."} -- same convention pocsag_companion.ino's own serial
  protocol already uses, reused deliberately rather than a hand-rolled
  binary layout (self-describing, and ArduinoJson is already a
  dependency here). A capcode is just a plain integer; this device
  listens on one or more (MY_CAPCODES below -- e.g. its own personal
  number plus a shared address like 911 for broadcasts everyone should
  see), and only surfaces a received message whose "to" matches one of
  them. Sending stamps MY_SEND_CAPCODE as "from" and a hardcoded
  SEND_TO_CAPCODE as "to" -- like the radio parameters above, real
  capcode values are hardcoded for now, not fetched from the dashboard.
*/

#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>

#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#include <RadioLib.h>
#include <ArduinoJson.h> // v7.4.3 -- JsonDocument/deserializeJson v7 API,
                          // same version pocsag_companion.ino uses

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
// Hardcoded for now, same reasoning as the radio parameters above.
// Placeholder numbers -- replace with this device's real assigned
// capcode and whatever it should actually send to before real use.
// This device answers to either of these "to" addresses:
const uint32_t MY_CAPCODES[] = { 911, 123456 };
const int NUM_MY_CAPCODES = sizeof(MY_CAPCODES) / sizeof(MY_CAPCODES[0]);
// ...but sends AS its own personal number (not the shared 911 address),
// and only ever TO this hardcoded recipient for now (no recipient
// picker on a one-button device -- see the New Message tab's own "to"
// field for how the dashboard side chooses a recipient instead).
const uint32_t MY_SEND_CAPCODE = 123456;
const uint32_t SEND_TO_CAPCODE = 654321;

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

// ---------- Last received message ----------
bool hasReceivedMessage = false;
String lastMessageText;
uint32_t lastMessageFrom = 0;
float lastMessageRssi = 0;

// ---------- RX interrupt flag ----------
volatile bool rxFlag = false;
void onRadioAction() { rxFlag = true; }

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
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("Pager starting...");
  display.display();

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
      Serial.printf("[RX] ignored (to=%lu, not one of ours)\n", (unsigned long)to);
      radio.startReceive();
      return;
    }

    lastMessageText = String(text);
    lastMessageFrom = from;
    lastMessageRssi = radio.getRSSI();
    hasReceivedMessage = true;
    Serial.printf("[RX] from=%lu to=%lu \"%s\" rssi=%.1f\n",
                  (unsigned long)from, (unsigned long)to, text, lastMessageRssi);

    // "Leaning toward wait" -- don't yank the menu away if the operator is
    // mid-selection; the new message still shows the moment they return to
    // idle (either via timeout or by sending/cancelling).
    if (uiState == STATE_IDLE) drawIdle();
  } else {
    Serial.printf("[!] readData failed: %d\n", state);
  }

  radio.startReceive();
}

void sendCannedMessage(int idx) {
  const char* msg = CANNED_MESSAGES[idx];

  JsonDocument doc;
  doc["from"] = MY_SEND_CAPCODE;
  doc["to"] = SEND_TO_CAPCODE;
  doc["text"] = msg;
  char buf[256];
  size_t len = serializeJson(doc, buf, sizeof(buf));

  int state = radio.transmit((uint8_t*)buf, len);
  Serial.printf("[TX] from=%lu to=%lu \"%s\" -> %s\n",
                (unsigned long)MY_SEND_CAPCODE, (unsigned long)SEND_TO_CAPCODE,
                msg, state == RADIOLIB_ERR_NONE ? "OK" : "FAIL");
  // transmit() leaves the radio in TX/idle state -- must explicitly go
  // back to RX or every message sent would also deafen this device to
  // anything arriving afterward.
  radio.startReceive();
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
  }
  // Short press from idle: no action defined -- idle is purely a display,
  // long-hold is the only way in.
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
void drawIdle() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("PAGER");
  display.drawFastHLine(0, 10, OLED_WIDTH, SSD1306_WHITE);
  display.setCursor(0, 16);
  if (!hasReceivedMessage) {
    display.println("No messages yet");
  } else {
    display.printf("From: %lu\n", (unsigned long)lastMessageFrom);
    display.println(lastMessageText);
    display.setCursor(0, 56);
    display.printf("RSSI %.0f dBm", lastMessageRssi);
  }
  display.display();
}

void drawMenu() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("SEND (hold=send)");
  display.drawFastHLine(0, 10, OLED_WIDTH, SSD1306_WHITE);
  display.setCursor(0, 16);
  display.println(CANNED_MESSAGES[cannedIndex]);
  display.setCursor(0, 56);
  display.printf("%d/%d", cannedIndex + 1, NUM_CANNED);
  display.display();
}
