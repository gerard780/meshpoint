/*
  Reticulum band-plan channel test TX -- Heltec WiFi LoRa 32 V3 (SX1262)

  A controlled, repeatable alternative to waiting on real Reticulum
  network traffic: a one-button OLED menu picks one of the concentrator's
  radio.band_plan="reticulum" channels (ch0-ch7, see eu868_reticulum()
  in src/hal/concentrator_config.py -- the full set, including ch0
  "Reticulum" itself, since the real RNode test of that one never
  actually confirmed a hit either), then sends a short, human-readable
  test message on it on demand -- so a hit (or lack of one) in the
  dashboard's RF Environment -> Stray Frames card tells you directly
  whether the concentrator accepts something on that channel at all,
  without depending on when/whether a real Reticulum relay event happens
  to occur. New, standalone file -- not a modification of the existing
  extra/heltec_lorawan_test_tx.ino (a different, LoRaWAN-specific tool).

  STATUS: live-confirmed on real hardware the same session this was
  written -- a "TEST #0 Chat" transmission on ch1 showed up correctly in
  Stray Frames as protocol_hint="reticulum", RSSI -30.4 dBm / SNR 16.0 dB,
  12 bytes, exact payload match.

  ---- Hardware ----
  Board: Heltec WiFi LoRa 32 (V3). Pins below are the same values already
  proven by extra/pager_client.ino and extra/heltec_lorawan_test_tx.ino --
  reused verbatim, not re-derived.

  ---- Sync word ----
  Reticulum's real private-network sync word is the single byte 0x12
  (confirmed from microReticulum_Firmware's own source this session --
  see extra/heltec_v4_reticulum_bron/microReticulum_Firmware/sx126x.cpp).
  RadioLib's SX126x begin() takes that plain byte directly (its uint8_t
  syncWord parameter) and expands it to the chip's real 16-bit register
  pair internally -- use its own named constant
  RADIOLIB_SX126X_SYNC_WORD_PRIVATE rather than hand-deriving the 16-bit
  form (an earlier version of this file passed a hand-derived 0x1424,
  which a real compiler warning caught silently truncating to 0x24). See
  the #define site below for the full writeup.

  ---- Button UX ----
  One button (PRG, GPIO0), same short/long-press debounce shape as
  pager_client.ino's own checkButton() (30ms debounce, 700ms long-press
  threshold) -- reused as the same proven pattern, not reinvented:
    Short press: cycle to the next channel (wraps around).
    Long press:  send a test message on the currently selected channel.
  No menu tree, no WiFi/OTA/NVS -- this is a temporary diagnostic tool,
  not a permanent companion; deliberately not built to that fuller
  pattern's scope.

  Library: RadioLib (Arduino Library Manager)
*/

#include <RadioLib.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ArduinoJson.h>

// ---------- Hardware pins (Heltec WiFi LoRa32 V3) ----------
#define LORA_CS   8
#define LORA_RST  12
#define LORA_BUSY 13
#define LORA_DIO1 14

#define OLED_WIDTH   128
#define OLED_HEIGHT  64
#define OLED_SDA_PIN 17
#define OLED_SCL_PIN 18
#define OLED_RST_PIN 21
#define VEXT_PIN     36

#define BUTTON_GPIO 0

SX1262 radio = new Module(LORA_CS, LORA_DIO1, LORA_RST, LORA_BUSY);
Adafruit_SSD1306 display(OLED_WIDTH, OLED_HEIGHT, &Wire, OLED_RST_PIN);

// Reticulum's real private-network sync word is the single byte 0x12
// (confirmed from microReticulum_Firmware's own source -- see
// extra/heltec_v4_reticulum_bron/microReticulum_Firmware/sx126x.cpp).
// RadioLib already provides this exact value as a named constant --
// RADIOLIB_SX126X_SYNC_WORD_PRIVATE (see RadioLib/src/modules/SX126x/
// SX126x_registers.h: "0x12  // actually 0x1424") -- it handles the
// chip's real 16-bit sync-word register-pair expansion internally, the
// same way the reference tool (extra/heltec_lorawan_test_tx.ino) passes
// the plain byte RADIOLIB_SX126X_SYNC_WORD_PUBLIC (0x34) rather than its
// own internal 0x3444 form. An earlier version of this file passed a
// hand-derived 0x1424 directly -- wrong (silently truncated to 0x24 by
// the uint8_t parameter, a real compiler warning caught this) -- fixed
// to use RadioLib's own constant instead of re-deriving the encoding by
// hand.
#define RETICULUM_PRIVATE_SYNC_WORD RADIOLIB_SX126X_SYNC_WORD_PRIVATE

// ch0-ch7 of eu868_reticulum() (src/hal/concentrator_config.py) -- the
// full set, ch0 ("Reticulum") included: the real RNode test of ch0
// earlier this session never actually confirmed a hit either, so
// there's no real reason to leave it out of this controlled test.
struct TestChannel {
  float freqMhz;
  const char* name;
};
const TestChannel CHANNELS[] = {
  {869.463, "Reticulum"},
  {869.055, "Chat"},
  {869.155, "LoRa Pager"},
  {869.255, "Public"},
  {869.355, "Data"},
  {869.665, "Weather"},
  {869.765, "Alert"},
  {869.865, "Emergency"},
};
const int NUM_CHANNELS = sizeof(CHANNELS) / sizeof(CHANNELS[0]);
int channelIdx = 0;
uint32_t txCount = 0;

// ---------- Button: debounce + short/long press (same shape as
// pager_client.ino's own checkButton(), see header comment) ----------
const unsigned long DEBOUNCE_MS   = 30;
const unsigned long LONG_PRESS_MS = 700;
bool lastRawReading   = HIGH;
bool debouncedPressed = false;
unsigned long lastEdgeMs   = 0;
unsigned long pressStartMs = 0;
bool longPressFired = false;

// ---------- Status line shown under the channel list until the next
// button press or send -- kept simple, no timed auto-clear needed since
// this is a single always-visible screen, not a menu tree. ----------
char statusLine[32] = "short=next  hold=send";

void setup() {
  Serial.begin(115200);
  delay(500);

  // OLED power rail: must happen before Wire.begin()/display.begin(),
  // same VEXT gotcha documented in pager_client.ino's own header comment.
  pinMode(VEXT_PIN, OUTPUT);
  digitalWrite(VEXT_PIN, LOW); // power ON

  Wire.begin(OLED_SDA_PIN, OLED_SCL_PIN);
  if (display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    // Adafruit_GFX defaults textcolor to a value drawPixel() never
    // recognizes -- every glyph silently no-ops without this explicit
    // call. Real bug found and fixed elsewhere in this project earlier
    // this session; setting it explicitly here from the start.
    display.setTextColor(SSD1306_WHITE);
  }

  pinMode(BUTTON_GPIO, INPUT_PULLUP);

  int state = radio.begin(
    CHANNELS[0].freqMhz,          // frequency (MHz)
    125.0,                        // bandwidth (kHz)
    8,                             // spreading factor -- matches Reticulum's real SF8
    5,                             // coding rate 4/5
    RETICULUM_PRIVATE_SYNC_WORD,
    14,                             // TX power (dBm) -- deliberately modest;
                                    // this is a same-room diagnostic tool,
                                    // not a real deployment, and these
                                    // frequencies don't all fall inside
                                    // EU868's high-power sub-band windows
    8                               // preamble length (symbols)
  );

  if (state != RADIOLIB_ERR_NONE) {
    Serial.printf("[!] Radio init failed: %d\n", state);
    snprintf(statusLine, sizeof(statusLine), "RADIO INIT FAILED %d", state);
  } else {
    Serial.println("[*] Reticulum channel test TX ready");
    Serial.println("[*] Short press = next channel, long press = send");
  }

  drawBootScreen();
  delay(1500);
  drawScreen();
}

void loop() {
  checkButton();
}

// ---------- Button handling ----------

void checkButton() {
  bool reading = digitalRead(BUTTON_GPIO);
  if (reading != lastRawReading) {
    lastEdgeMs = millis();
    lastRawReading = reading;
  }

  if (millis() - lastEdgeMs > DEBOUNCE_MS) {
    bool pressed = (reading == LOW);
    if (pressed && !debouncedPressed) {
      debouncedPressed = true;
      pressStartMs = millis();
      longPressFired = false;
    } else if (!pressed && debouncedPressed) {
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
  channelIdx = (channelIdx + 1) % NUM_CHANNELS;
  snprintf(statusLine, sizeof(statusLine), "short=next  hold=send");
  drawScreen();
}

void onLongPress() {
  sendTestMessage();
}

// ---------- Send ----------

void sendTestMessage() {
  const TestChannel &ch = CHANNELS[channelIdx];
  radio.setFrequency(ch.freqMhz);

  // JSON so a future decoder can cross-check the channel this payload
  // CLAIMS it was sent on ("channel"/"name") against the channel it was
  // actually RECEIVED on (the concentrator's own IF/frequency) -- the
  // whole point of this field, not just a nicer format.
  JsonDocument doc;
  doc["test"] = true;
  doc["channel"] = channelIdx;
  doc["name"] = ch.name;
  doc["count"] = txCount;

  char payload[96];
  size_t payloadLen = serializeJson(doc, payload, sizeof(payload));

  Serial.printf("[TX] %.3f MHz  %-12s  \"%s\" ... ", ch.freqMhz, ch.name, payload);
  int state = radio.transmit((uint8_t*)payload, payloadLen);

  if (state == RADIOLIB_ERR_NONE) {
    Serial.println("OK");
    snprintf(statusLine, sizeof(statusLine), "TX #%lu sent OK", (unsigned long)txCount);
    txCount++;
  } else {
    Serial.printf("FAIL (%d)\n", state);
    snprintf(statusLine, sizeof(statusLine), "TX FAILED (%d)", state);
  }

  drawScreen();
}

// ---------- Display ----------
//
// Scroll-list menu (highlighted selection + scrollbar), same visual idea
// as pager_client.ino's own Inbox/Outbox lists (previous/current/next
// rows + a scrollbar, modeled on github.com/upiir/arduino_oled_menu) --
// reused here at a smaller scale (one flat channel list, no nested
// screens) rather than re-implementing that project's fuller menu tree.

#define LIST_VISIBLE_ROWS 4
#define ROW_HEIGHT 10
#define LIST_TOP_Y 12

void drawCenteredLine(const char* text, int y) {
  int16_t x1, y1;
  uint16_t w, h;
  display.getTextBounds(text, 0, y, &x1, &y1, &w, &h);
  display.setCursor((OLED_WIDTH - w) / 2, y);
  display.println(text);
}

// Shown once in setup() before the main list -- same "three-line
// centered layout" idea as pager_client.ino's own boot screen, via
// getTextBounds() rather than manual glyph-width math (that file's own
// note on why: manual math breaks the moment the text changes).
void drawBootScreen() {
  display.clearDisplay();
  display.setTextSize(1);
  drawCenteredLine("Concentrator", 16);
  drawCenteredLine("Freq Tester", 30);
  char sub[24];
  snprintf(sub, sizeof(sub), "%d channels  sync 0x12", NUM_CHANNELS);
  drawCenteredLine(sub, 44);
  display.display();
}

void drawScreen() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("RETICULUM CH TEST");
  display.drawFastHLine(0, 10, OLED_WIDTH, SSD1306_WHITE);

  // Keep the selected channel inside the visible scroll window.
  int scrollOffset = 0;
  if (channelIdx >= LIST_VISIBLE_ROWS) {
    scrollOffset = channelIdx - LIST_VISIBLE_ROWS + 1;
  }
  if (scrollOffset > NUM_CHANNELS - LIST_VISIBLE_ROWS) {
    scrollOffset = NUM_CHANNELS - LIST_VISIBLE_ROWS;
  }
  if (scrollOffset < 0) scrollOffset = 0;

  for (int row = 0; row < LIST_VISIBLE_ROWS && (scrollOffset + row) < NUM_CHANNELS; row++) {
    int idx = scrollOffset + row;
    int y = LIST_TOP_Y + row * ROW_HEIGHT;
    bool selected = (idx == channelIdx);

    char line[24];
    snprintf(line, sizeof(line), "ch%d %s", idx, CHANNELS[idx].name);

    if (selected) {
      display.fillRect(0, y - 1, OLED_WIDTH - 4, ROW_HEIGHT, SSD1306_WHITE);
      display.setTextColor(SSD1306_BLACK);
    } else {
      display.setTextColor(SSD1306_WHITE);
    }
    display.setCursor(2, y);
    display.println(line);
  }
  display.setTextColor(SSD1306_WHITE); // restore for the status line below

  // Simple scrollbar on the right edge, proportional to scroll position.
  if (NUM_CHANNELS > LIST_VISIBLE_ROWS) {
    int trackTop = LIST_TOP_Y;
    int trackH = LIST_VISIBLE_ROWS * ROW_HEIGHT;
    display.drawRect(OLED_WIDTH - 3, trackTop, 3, trackH, SSD1306_WHITE);
    int maxOffset = NUM_CHANNELS - LIST_VISIBLE_ROWS;
    int thumbH = max(4, trackH * LIST_VISIBLE_ROWS / NUM_CHANNELS);
    int thumbY = trackTop + (trackH - thumbH) * scrollOffset / max(1, maxOffset);
    display.fillRect(OLED_WIDTH - 3, thumbY, 3, thumbH, SSD1306_WHITE);
  }

  display.setCursor(0, LIST_TOP_Y + LIST_VISIBLE_ROWS * ROW_HEIGHT + 2);
  display.println(statusLine);

  display.display();
}
