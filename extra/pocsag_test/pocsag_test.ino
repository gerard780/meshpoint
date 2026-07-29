/*
  TTGO LoRa32 V2.1.6 -- fake POCSAG pager transmitter for meshpoint's
  Pagers/POCSAG tabs (rtl_fm | multimon-ng, see src/audio/pager_listener.py)

  Round-robins a small fleet of virtual pagers -- alpha (ASCII text),
  numeric (BCD digits), and tone-only alerts -- on 439.9875 MHz, the
  exact frequency src/audio/pager_listener.py's "pocsag" kind tunes to
  (`frequency_hz: 439_987_500`). multimon-ng is started there with
  `-a POCSAG512 -a POCSAG1200 -a POCSAG2400` (all three baud rates
  live simultaneously), so any of them decodes -- this sketch defaults
  to 1200 (POCSAG_BAUD below), matching the real capture already
  confirmed against this decoder (docs/CHANGELOG.md v0.7.7: "POCSAG1200:
  Address: 2041152  Function: 3  Alpha: Test message").

  Unlike extra/rtl433test/rtl433test.ino (which fakes six different OOK
  sensor protocols by hand-rendering an oversampled NRZ bitstream one
  chip at a time, because those decoders read raw pulse widths/gaps),
  POCSAG is real 2-FSK and RadioLib ships a complete, maintained POCSAG
  encoder for it: PagerClient (src/protocols/Pager/Pager.{h,cpp} in the
  installed RadioLib library -- confirmed present locally at
  ~/Documents/Arduino/libraries/RadioLib, v7.7.1, same copy Arduino IDE
  uses to compile this and the other extra/*_test sketches). It builds
  the entire preamble/sync/idle/BCH(31,21)-FEC frame structure
  correctly and transmits it via the chip's DIRECT mode: one raw SPI
  carrier-frequency register write per bit (phyLayer->transmitDirect(),
  software-timed to the bit period), not the packet-mode FIFO -- so
  there is no packet-length ceiling to fight (rtl433test.ino's central
  problem, worked around there by chip-rate tricks and hitting
  RadioLib's 63-byte FSK/OOK transmit() cap). This also means DIO2
  (the SX1276's continuous-mode data pin, not broken out on this board
  either -- same constraint rtl433test.ino's header notes) is never
  touched for transmit: PagerClient::write() only ever calls
  transmitDirect(freq) over SPI, so no extra wiring is needed beyond
  what's already used for LoRa mode and rtl433test.

  Should also work unchanged on a Heltec WiFi LoRa32 V3 (SX1262, see
  extra/heltec_lorawan_test_tx/) -- PagerClient only talks to the
  PhysicalLayer interface both chips implement, transmitDirect() is
  common code, not SX127x-specific. Swap the `SX1276 radio = ...` line
  for `SX1262 radio = new Module(8, 14, 12, 13);` (NSS, DIO1, RST,
  BUSY -- see extra/heltec_lorawan_test_tx's own pin comment) and drop
  the OLED block if that board's display differs. Not needed for this
  test as written: the TTGO already has everything this sketch uses.

  POCSAG protocol constants used internally by PagerClient, confirmed
  directly from RadioLib's own Pager.h (not re-derived/guessed here):
    - Preamble: 18x 0xAAAAAAAA code words (576 bits alternating 1010...)
      for bit/carrier sync.
    - Frame sync code word: 0x7CD215D8, one per 17-code-word batch.
    - Idle code word (fills unused frame slots): 0x7A89C197.
    - Each 21-bit address (RIC/capcode) splits into an 18-bit address
      field (top bits, capcode>>3) placed in the BATCH FRAME matching
      capcode's low 3 bits, plus a 2-bit function code (0=numeric,
      1=tone, 2=activation, 3=alphanumeric) -- exactly what the
      dashboard's POCSAG tab shows as "Address"/"Function".
    - Frequency shift +-4.5 kHz (RADIOLIB_PAGER_FREQ_SHIFT_HZ), matching
      the POCSAG standard multimon-ng itself expects.

  Pins (TTGO LoRa32 V2.1.6, same as extra/rtl433test/rtl433test.ino):
  SPI:
    SCK  5
    MISO 19
    MOSI 27
    CS   18

  LoRa:
    RST 14
    DIO0 26

  OLED:
    SDA 21
    SCL 22
*/

#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>

#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#include <RadioLib.h>


// ---------- Test tuning knobs ----------
#define POCSAG_FREQ_MHZ 439.9875f
#define POCSAG_BAUD 1200          // 512, 1200, or 2400 -- multimon-ng listens for all three,
                                   // but 1200/NORMAL polarity is DAPNET's real German
                                   // transmitter standard on this exact 439.9875 MHz
                                   // frequency, so this is the real target, not just a
                                   // pick. LIVE-VERIFIED working at 1200: real captures
                                   // showed exact capcode matches with correct decoded
                                   // content for all three message types -- alpha text
                                   // ("Second pager, different capcode"), numeric BCD
                                   // ("0123456789.U -[]", same digits as sent, just
                                   // multimon-ng's own glyphs for the special BCD codes
                                   // instead of RadioLib's -- *()  vs .[]  -- cosmetic,
                                   // not a bug), and tone-only (Function: 1, no text,
                                   // correct). An earlier test session saw only garbled
                                   // addresses and no text and briefly suspected the
                                   // SX1276's PLL settling time at 1200 baud -- that
                                   // theory did not hold up (512 baud, more settling
                                   // margin per bit, produced nothing at all instead of
                                   // improving things) and was superseded by this result.
                                   // Do not "fix" this back to 512 -- 1200 is confirmed
                                   // correct and is the real DAPNET-compatible target.
                                   // The flood of "Address: 0-7, Function: 0" entries
                                   // multimon-ng shows alongside real messages is just
                                   // this project's own idle-codeword padding (each of
                                   // our batches is mostly idle-padded, since these are
                                   // short single-message test bursts, not continuous
                                   // real-world POCSAG traffic) being decoded literally --
                                   // expected, harmless, not evidence of a problem.
#define TX_INTERVAL_MS 2000       // delay between each pager's own burst
#define ROUND_PAUSE_MS 5000       // extra pause after a full round through the fleet


// ---------- Virtual pager fleet ----------
//
// One named on/off switch per fake pager -- flip any of these to 0 to
// isolate a single message type while debugging, instead of counting
// positions in the pagers[] table below. Same convention as
// rtl433test.ino's lacrosse1On/nexus1On/etc switches.
const bool alpha1On = 1;
const bool alpha2On = 1;
const bool numeric1On = 0;
const bool tone1On = 0;

enum PagerMsgType { MSG_ALPHA, MSG_NUMERIC, MSG_TONE };

struct FakePager {
  PagerMsgType type;
  bool enabled;
  uint32_t capcode;   // RIC address, 0..2097151 -- see RADIOLIB_PAGER_ADDRESS_MAX
  const char *text;   // unused for MSG_TONE
};

// Capcodes are arbitrary test values in a safe unassigned-looking range,
// each ending in a different low-3-bits value on purpose (capcode & 7
// selects which of the 8 frames in a POCSAG batch carries the address --
// see PagerClient::transmit()'s own framePos calculation) so a real
// capture exercises more than one frame position, not just frame 0.
FakePager pagers[] = {
  { MSG_ALPHA,   alpha1On,   1234561, "Meshpoint POCSAG test alpha message" },
  { MSG_ALPHA,   alpha2On,   1234562, "Second pager, different capcode" },
  { MSG_NUMERIC, numeric1On, 1234563, "0123456789*U -()" }, // only 0-9 * U - ( ) space allowed in BCD, per Pager.h
  { MSG_TONE,    tone1On,    1234564, nullptr },
};
const int NUM_PAGERS = sizeof(pagers) / sizeof(pagers[0]);
int currentPagerIdx = 0;


// ---------- OLED ----------

#define OLED_WIDTH 128
#define OLED_HEIGHT 64

Adafruit_SSD1306 display(
  OLED_WIDTH,
  OLED_HEIGHT,
  &Wire,
  -1
);


// ---------- Radio ----------

#define LORA_CS   18
#define LORA_RST  14
#define LORA_DIO0 26

SX1276 radio = new Module(
  LORA_CS,
  LORA_DIO0,
  LORA_RST,
  -1
);

// PagerClient wraps the radio module and does all the POCSAG framing --
// see the file header for what it handles internally.
PagerClient pager(&radio);


// ---------- Helpers ----------

const char *msgTypeLabel(PagerMsgType t) {
  switch (t) {
    case MSG_ALPHA:   return "ALPHA";
    case MSG_NUMERIC: return "NUMERIC";
    case MSG_TONE:    return "TONE";
  }
  return "?";
}

int txCount = 0;
bool lastTxOk = false;

void oled(const String &line1, const String &line2) {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println(line1);
  display.setCursor(0, 20);
  display.println(line2);
  display.display();
}

void showStats(const FakePager &p, int idx, int state) {
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);

  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print(msgTypeLabel(p.type));
  display.print(" ");
  display.print(idx + 1);
  display.print("/");
  display.print(NUM_PAGERS);
  display.drawFastHLine(0, 10, OLED_WIDTH, SSD1306_WHITE);

  display.setCursor(0, 14);
  display.print("Cap:");
  display.print(p.capcode);
  display.print(" TX#");
  display.print(txCount);

  display.setCursor(0, 26);
  display.setTextSize(1);
  if (p.type == MSG_TONE) {
    display.println("(tone only, no text)");
  } else {
    // Truncate to what fits on two 21-char lines at text size 1.
    String msg = String(p.text);
    display.println(msg.substring(0, 21));
    if (msg.length() > 21) display.println(msg.substring(21, 42));
  }

  display.drawFastHLine(0, 46, OLED_WIDTH, SSD1306_WHITE);
  display.setCursor(0, 50);
  display.print("439.9875MHz  ");
  display.print(POCSAG_BAUD);
  display.print("bps");

  display.setCursor(10, 58);
  if (lastTxOk) display.fillCircle(3, 60, 2, SSD1306_WHITE);
  else          display.drawCircle(3, 60, 2, SSD1306_WHITE);
  display.print(lastTxOk ? "Last TX OK" : String("Last TX FAILED (") + state + ")");

  display.display();
}


void setup() {
  Serial.begin(115200);
  delay(1000);

  // OLED
  Wire.begin(21, 22);
  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("OLED FAIL");
  }
  oled("POCSAG test", "starting...");

  // SPI
  SPI.begin(5, 19, 27, 18);

  Serial.println("Radio init (FSK mode)");

  // FSK init -- br/freqDev/rxBw here just need to be valid register
  // values; PagerClient::write() never uses the chip's own bitrate/
  // deviation registers for TX (it bit-bangs transmitDirect() calls on
  // its own software timer instead), so these matter far less than
  // they did for rtl433test.ino's OOK approach.
  int state = radio.beginFSK(POCSAG_FREQ_MHZ, 4.8, 5.0, 125.0, 17, 16, false);
  if (state != RADIOLIB_ERR_NONE) {
    Serial.print("Radio error: ");
    Serial.println(state);
    oled("Radio FAIL", String(state));
    while (true) { delay(1000); }
  }
  // 17 dBm (up from an unjustified 10 dBm copied from rtl433test.ino's
  // default) -- still plain PA_BOOST range (SX1278::setOutputPower()
  // only needs the special high-current +20dBm PA_DAC boost path for
  // power==20 exactly), no extra register dance needed. Live testing
  // showed short bursts (tone: 0 message code words; numeric: ~4, at
  // BCD's 4 bits/symbol) decoding reliably while alpha (~12-13 code
  // words for our ~32-36 char test strings, at ASCII's 7 bits/symbol)
  // almost never came through clean -- consistent with a low
  // background bit-error rate that's tolerable over a short burst but
  // increasingly likely to hit at least one of a long burst's many
  // independently-BCH-checked code words. More TX power directly
  // addresses that if the cause is marginal SNR (the most likely
  // explanation, since framing/baud/polarity are already confirmed
  // correct by the short messages decoding perfectly).
  radio.setOutputPower(17);

  // PagerClient::begin() computes its own frequency/bit-timing from
  // these two arguments and puts the module into direct mode
  // (phyLayer->startDirect()) -- see the file header for what this
  // does under the hood. invert/shift left at their defaults (false,
  // 4500 Hz), matching what multimon-ng's POCSAG demodulator expects.
  state = pager.begin(POCSAG_FREQ_MHZ, POCSAG_BAUD);
  if (state != RADIOLIB_ERR_NONE) {
    Serial.print("Pager init error: ");
    Serial.println(state);
    oled("Pager init FAIL", String(state));
    while (true) { delay(1000); }
  }

  Serial.println("Radio + Pager OK");
  Serial.println("Fake pager fleet:");
  for (int i = 0; i < NUM_PAGERS; i++) {
    Serial.print(pagers[i].enabled ? "  #" : "  (disabled) #"); Serial.print(i);
    Serial.print(" "); Serial.print(msgTypeLabel(pagers[i].type));
    Serial.print(" capcode="); Serial.print(pagers[i].capcode);
    if (pagers[i].text) { Serial.print(" text=\""); Serial.print(pagers[i].text); Serial.print("\""); }
    Serial.println();
  }

  oled("Pager OK", String(NUM_PAGERS) + " fake pagers ready");
}


void loop() {
  FakePager &p = pagers[currentPagerIdx];

  if (!p.enabled) {
    // Same skip-without-delay convention as rtl433test.ino's loop().
    bool roundComplete = (currentPagerIdx == NUM_PAGERS - 1);
    currentPagerIdx = (currentPagerIdx + 1) % NUM_PAGERS;
    if (roundComplete) {
      Serial.println("-- round complete (last pager disabled), pausing before next sequence --");
      delay(ROUND_PAUSE_MS);
    }
    return;
  }

  Serial.print("TX ");
  Serial.print(msgTypeLabel(p.type));
  Serial.print(" [");
  Serial.print(currentPagerIdx + 1);
  Serial.print("/");
  Serial.print(NUM_PAGERS);
  Serial.print("] capcode=");
  Serial.print(p.capcode);

  int state;
  switch (p.type) {
    case MSG_ALPHA:
      Serial.print(" text=\""); Serial.print(p.text); Serial.print("\"");
      state = pager.transmit(p.text, p.capcode, RADIOLIB_PAGER_ASCII);
      break;
    case MSG_NUMERIC:
      Serial.print(" digits=\""); Serial.print(p.text); Serial.print("\"");
      state = pager.transmit(p.text, p.capcode, RADIOLIB_PAGER_BCD);
      break;
    case MSG_TONE:
    default:
      state = pager.sendTone(p.capcode);
      break;
  }
  Serial.println();

  lastTxOk = (state == RADIOLIB_ERR_NONE);
  txCount++;

  if (lastTxOk) {
    Serial.println("TX OK");
  } else {
    Serial.print("TX error ");
    Serial.println(state);
  }

  showStats(p, currentPagerIdx, state);

  bool roundComplete = (currentPagerIdx == NUM_PAGERS - 1);
  currentPagerIdx = (currentPagerIdx + 1) % NUM_PAGERS;

  delay(TX_INTERVAL_MS);

  if (roundComplete) {
    Serial.println("-- round complete, pausing before next sequence --");
    delay(ROUND_PAUSE_MS);
  }
}
