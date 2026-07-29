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
#include <ArduinoJson.h> // v7.4.3 -- JsonDocument/deserializeJson v7 API, see handleSerialJsonLine()


// ---------- Test tuning knobs ----------
//
// 0 = TX/serial-send mode (fleet round-robin + JSON serial send, all
//     the existing behavior below), 1 = RX/listen mode (new -- see the
//     "RX mode" section further down). Mutually exclusive in this pass
//     -- RX is receive-only for now, deliberately not combined with TX
//     in the same running sketch yet. Reasoning: RX's own correctness
//     is still an open question (untested against real hardware, unlike
//     TX which went through several rounds of live verification against
//     the real dashboard), so it's worth confirming RX works on its own
//     first rather than building simultaneous TX+RX mode-switching on
//     top of an unverified receive path. Once RX is confirmed live,
//     combining them (temporarily pausing RX to send a JSON-triggered
//     page, then resuming) is a straightforward next step -- half-duplex
//     only, same as any real pager transceiver, since it's one antenna.
#define POCSAG_MODE_RX 1

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
#define TX_INTERVAL_MS 3000       // delay between each pager's own burst -- bumped from 2000
                                   // to give more breathing room against real DAPNET traffic
                                   // sharing this channel (see the POCSAG_BAUD comment above --
                                   // this frequency is DAPNET's real German transmitter
                                   // frequency, not a quiet test channel)
#define ROUND_PAUSE_MS 3000       // extra pause after a full round through the fleet
#define SERIAL_DEFAULT_CAPCODE 2041152UL // JSON-serial default capcode when the line omits
                                   // "capcode" -- distinct from the pagers[] fleet's
                                   // 1234561-1234564. Defined up here (not next to
                                   // checkSerialInput()/handleSerialJsonLine() below,
                                   // where it's actually used) because it's a #define,
                                   // not a variable -- it must appear before its first
                                   // use textually (showReadyScreen() uses it too, and
                                   // that's defined earlier in the file).


// ---------- Virtual pager fleet ----------
//
// One named on/off switch per fake pager -- flip any of these to 0 to
// isolate a single message type while debugging, instead of counting
// positions in the pagers[] table below. Same convention as
// rtl433test.ino's lacrosse1On/nexus1On/etc switches.
const bool alpha1On = 0;
const bool alpha2On = 0;
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
//
// Alpha strings are deliberately padded with trailing spaces to a length
// that decodes cleanly -- CONFIRMED BUG in RadioLib 7.7.1's own
// PagerClient::transmit() (src/protocols/Pager/Pager.cpp): the BCD/numeric
// path explicitly space-pads any leftover 4-bit symbol slots in the last
// message code word before encoding it ("in BCD mode, pad the rest of the
// code word with spaces"), but the ASCII path has NO equivalent -- it
// just `break`s when real data runs out, leaving whatever leftover 7-bit
// symbol slots exist in that code word as raw zero bits (the buffer was
// memset(0) before any real data was written in). Those zero-bits decode
// as literal NUL bytes appended to the real text -- which is baked into
// the actual over-the-air transmission, not a receiver artifact. Proven
// by porting Pager.cpp's real message-building loop and Pager.cpp's real
// decode loop (readData()) verbatim into a standalone native C++ harness
// (no Arduino/hardware deps needed -- BCH.cpp is pure math) and round-
// tripping every string here through RadioLib's OWN actual algorithm:
// "Second pager, different capcode" (32 chars) already lands on a clean
// boundary with 0 leftover bits -- which is exactly why it's the only
// alpha message that was ever seen decoding successfully live, while
// "Meshpoint POCSAG test alpha message" (36 chars unpadded) leftover 2
// slots, meaning the real transmitted signal carried 2 trailing NUL
// bytes baked in -- almost certainly what silently kills that message
// before multimon-ng's decoded text line ever reaches the dashboard (a
// raw NUL mid-line breaks most C-string-based text handling). If you
// change either string, re-verify the padding needed (brute-force 0-19
// trailing spaces against RadioLib's real encode+decode logic -- do NOT
// just guess a number) before assuming a new alpha message will decode
// cleanly.
FakePager pagers[] = {
  { MSG_ALPHA,   alpha1On,   1234561, "Meshpoint POCSAG test alpha message  " }, // +2 spaces, see comment above
  { MSG_ALPHA,   alpha2On,   1234562, "Second pager, different capcode" },       // already clean, 0 padding needed
  { MSG_NUMERIC, numeric1On, 1234563, "0123456789*U -()" }, // only 0-9 * U - ( ) space allowed in BCD, per Pager.h
  { MSG_TONE,    tone1On,    1234564, nullptr },
};
const int NUM_PAGERS = sizeof(pagers) / sizeof(pagers[0]);
int currentPagerIdx = 0;
bool anyPagerEnabled = false; // computed once in setup(), used by loop() to
                               // skip round-robin bookkeeping/noise entirely
                               // when the whole fleet is off (serial-only testing)


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


// ---------- Alpha auto-padding for Serial-typed messages ----------
//
// RadioLibBCH is already linked in via RadioLib.h (it pulls in
// protocols/Pager/Pager.h, which pulls in utils/BCH.h -- no extra
// #include needed), so this reuses the real BCH encoder rather than
// re-deriving anything. simBuild()/simDecode() are a straight port of
// the same PagerClient::transmit()/readData() message-building and
// decode logic already verified against RadioLib's real source (see
// the long comment on the pagers[] array above for how that padding
// requirement was originally discovered for the two hardcoded
// strings) -- ported here so ANY typed message gets the same fix
// automatically, not just those two. Simulation only: builds and
// immediately decodes the same code words locally, never touches the
// radio, so it's safe to run before every Serial-triggered send.
RadioLibBCH padSimBch;

uint32_t *simBuild(const uint8_t *data, size_t len, uint32_t addr, size_t *outMsgLen, uint8_t *outFramePos) {
  const uint8_t symbolLength = 7; // ASCII only -- this helper is alpha-specific
  uint8_t framePos = 2 * (addr & 0x07);
  *outFramePos = framePos;

  size_t numDataBlocks = (len * symbolLength) / RADIOLIB_PAGER_MESSAGE_BITS_LENGTH;
  if ((len * symbolLength) % RADIOLIB_PAGER_MESSAGE_BITS_LENGTH > 0) numDataBlocks += 1;
  size_t numBatches = (framePos + numDataBlocks + RADIOLIB_PAGER_BATCH_LEN) / RADIOLIB_PAGER_BATCH_LEN;
  size_t msgLen = RADIOLIB_PAGER_PREAMBLE_LENGTH + (1 + RADIOLIB_PAGER_BATCH_LEN) * numBatches;

  uint32_t *msg = new uint32_t[msgLen];
  memset(msg, 0x00, msgLen * sizeof(uint32_t));
  for (size_t i = 0; i < RADIOLIB_PAGER_PREAMBLE_LENGTH; i++) msg[i] = RADIOLIB_PAGER_PREAMBLE_CODE_WORD;
  for (size_t i = RADIOLIB_PAGER_PREAMBLE_LENGTH; i < msgLen; i++) msg[i] = RADIOLIB_PAGER_IDLE_CODE_WORD;
  for (size_t i = 0; i < numBatches; i++) {
    msg[RADIOLIB_PAGER_PREAMBLE_LENGTH + i * (1 + RADIOLIB_PAGER_BATCH_LEN)] = RADIOLIB_PAGER_FRAME_SYNC_CODE_WORD;
  }

  uint32_t frameAddr = ((addr >> 3) << RADIOLIB_PAGER_ADDRESS_POS) | (RADIOLIB_PAGER_FUNC_BITS_ALPHA << RADIOLIB_PAGER_FUNC_BITS_POS);
  msg[RADIOLIB_PAGER_PREAMBLE_LENGTH + 1 + framePos] = padSimBch.encode(frameAddr);

  if (len > 0) {
    int8_t remBits = 0;
    size_t dataPos = 0;
    for (size_t i = 0; i < numDataBlocks + numBatches - 1; i++) {
      uint8_t blockPos = RADIOLIB_PAGER_PREAMBLE_LENGTH + 1 + framePos + 1 + i;
      if (((blockPos - RADIOLIB_PAGER_PREAMBLE_LENGTH) % (RADIOLIB_PAGER_BATCH_LEN + 1)) == 0) {
        blockPos++;
        i++;
      }
      msg[blockPos] = RADIOLIB_PAGER_MESSAGE_CODE_WORD << (RADIOLIB_PAGER_CODE_WORD_LEN - 1);
      if (remBits > 0) {
        uint8_t prev = rlb_reflect(data[dataPos - 1], 8);
        prev >>= 1;
        msg[blockPos] |= (uint32_t)prev << (RADIOLIB_PAGER_CODE_WORD_LEN - 1 - remBits);
      }
      int8_t symbolPos = RADIOLIB_PAGER_CODE_WORD_LEN - 1 - symbolLength - remBits;
      while (symbolPos > (RADIOLIB_PAGER_FUNC_BITS_POS - symbolLength)) {
        uint8_t symbol = data[dataPos++];
        symbol = rlb_reflect(symbol, 8);
        symbol >>= (8 - symbolLength);
        msg[blockPos] |= (uint32_t)symbol << symbolPos;
        symbolPos -= symbolLength;
        if (dataPos >= len) break;
      }
      msg[blockPos] &= ~(RADIOLIB_PAGER_BCH_BITS_MASK);
      remBits = RADIOLIB_PAGER_FUNC_BITS_POS - symbolPos - symbolLength;
      msg[blockPos] = padSimBch.encode(msg[blockPos]);
    }
  }

  *outMsgLen = msgLen;
  return msg;
}

String simDecode(uint32_t *codewords, size_t numCodewords, size_t startIdx) {
  const uint8_t symbolLength = 7;
  String out;
  uint32_t prevCw = 0;
  bool overflow = false;
  int8_t ovfBits = 0;

  for (size_t idx = startIdx; idx < numCodewords; idx++) {
    uint32_t cw = codewords[idx];
    if (cw == RADIOLIB_PAGER_IDLE_CODE_WORD) break;
    if (cw == RADIOLIB_PAGER_FRAME_SYNC_CODE_WORD) continue;

    uint8_t bitPos = RADIOLIB_PAGER_CODE_WORD_LEN - 1 - symbolLength;
    if (overflow) {
      overflow = false;
      uint8_t currPos = RADIOLIB_PAGER_CODE_WORD_LEN - 1 - symbolLength + ovfBits;
      uint8_t prevPos = RADIOLIB_PAGER_MESSAGE_END_POS;
      uint32_t prevMask = (0x7FUL << prevPos) & ~((uint32_t)0x7FUL << (RADIOLIB_PAGER_MESSAGE_END_POS + ovfBits));
      uint32_t currMask = (0x7FUL << currPos) & ~((uint32_t)1 << (RADIOLIB_PAGER_CODE_WORD_LEN - 1));
      uint8_t prevSymbol = (prevCw & prevMask) >> prevPos;
      uint8_t currSymbol = (cw & currMask) >> currPos;
      uint32_t symbol = prevSymbol << (symbolLength - ovfBits) | currSymbol;
      symbol = rlb_reflect((uint8_t)symbol, 8);
      symbol >>= (8 - symbolLength);
      out += (char)symbol;
      bitPos += ovfBits;
      bitPos -= symbolLength;
    }

    while (bitPos >= RADIOLIB_PAGER_MESSAGE_END_POS) {
      uint32_t symbol = (cw & (0x7FUL << bitPos)) >> bitPos;
      symbol = rlb_reflect((uint8_t)symbol, 8);
      symbol >>= (8 - symbolLength);
      out += (char)symbol;
      int8_t remBits = bitPos - RADIOLIB_PAGER_MESSAGE_END_POS;
      if (remBits < symbolLength) {
        prevCw = cw;
        overflow = true;
        ovfBits = remBits;
      }
      bitPos -= symbolLength;
    }
  }
  return out;
}

// Brute-forces 0..19 trailing spaces (same search range/method used to
// find the two hardcoded pagers[] paddings) and returns the first
// padded string that round-trips cleanly through the real encode+decode
// logic above. Falls back to the original text with a Serial warning if
// nothing in that range works (shouldn't happen in practice -- every
// length tried during development found a clean padding within a few
// characters).
String padAlphaForCleanDecode(const String &text, uint32_t addr) {
  for (int pad = 0; pad <= 19; pad++) {
    String candidate = text;
    for (int i = 0; i < pad; i++) candidate += ' ';

    size_t msgLen; uint8_t framePos;
    uint32_t *msg = simBuild((const uint8_t *)candidate.c_str(), candidate.length(), addr, &msgLen, &framePos);
    size_t addrIdx = RADIOLIB_PAGER_PREAMBLE_LENGTH + 1 + framePos;
    String decoded = simDecode(msg, msgLen, addrIdx + 1);
    delete[] msg;

    if (decoded == candidate) {
      if (pad > 0) {
        Serial.print("  (auto-padded with "); Serial.print(pad); Serial.println(" trailing space(s) for a clean decode)");
      }
      return candidate;
    }
  }
  Serial.println("  WARNING: no clean padding found in 0..19 -- sending unpadded, may decode with trailing garbage");
  return text;
}


#if POCSAG_MODE_RX
// ---------- RX mode: listen for real POCSAG traffic, no DIO2 wire ----------
//
// RadioLib's own receive-side PagerClient::startReceive() needs a GPIO
// wired to the SX1276's DIO2 (continuous-mode raw-bit output) -- per
// this file's own header, that pin isn't broken out on this board. This
// uses the chip's STANDARD FSK packet engine instead, entirely over
// SPI, no DIO2 involved at all:
//   - setSyncWord() configured to POCSAG's own frame-sync code word
//     (0x7CD215D8) -- the hardware bit-correlator finds it for us, we
//     never have to search for it in software.
//   - fixedPacketLengthMode(64) -- 64 bytes = 16 code words = exactly
//     one POCSAG batch's worth of DATA code words (the sync word itself
//     is consumed by the correlator match, never delivered as payload).
//     64 also happens to be RADIOLIB_SX127X_MAX_PACKET_LENGTH_FSK (see
//     SX127x.h) -- the SX127x FSK FIFO's own physical size -- so this
//     needs no mid-packet FIFO-refill handling, the numbers just line
//     up with the hardware's own limit.
//   - setCrcFiltering(false) -- POCSAG uses its own BCH(31,21), not the
//     chip's built-in CRC.
// UNLIKE TX (which bit-bangs its own bit timing via transmitDirect()
// and never touches the chip's bitrate/deviation registers, see the
// !POCSAG_MODE_RX setup() below), RX genuinely needs those registers
// set correctly -- the chip's own demodulator hardware is what decides
// each bit here, there's no software bit-bang to compensate for a wrong
// register value the way TX's direct mode does.
//
// No BCH error correction on decode -- RadioLib's own
// PagerClient::readData() doesn't do this either (its own literal
// "TODO BCH error correction here" comment in Pager.cpp). A code word
// with enough bit errors just fails to look like a valid address, or
// decodes to garbled text, and gets skipped/shown as-is -- the same
// tradeoff multimon-ng makes without a full BCH decoder.
#define POCSAG_RX_BANDWIDTH_KHZ 20.8f // Carson's rule for 1200bps/4.5kHz deviation
                                       // is ~11.4kHz; picked wider for tolerance to
                                       // real-world frequency error. RadioLib rounds
                                       // to the nearest hardware-supported value
                                       // regardless (calculateBWManExp()), so this
                                       // doesn't need to be exact.
#define POCSAG_RX_BATCH_BYTES 64      // 16 code words -- see the section comment above
// BITWISE-INVERTED RADIOLIB_PAGER_FRAME_SYNC_CODE_WORD (0x7CD215D8), not the
// plain value -- confirmed against RadioLib's own direct-mode receive code
// (PagerClient::startReceiveCommon() in Pager.cpp): "the logic here is
// inverted, because modules like SX1278 assume high frequency to be logic 1,
// which is opposite to POCSAG" -- it searches for
// ~RADIOLIB_PAGER_FRAME_SYNC_CODE_WORD when invert=false (our default, same
// as our own TX side uses), and its read() function inverts every full
// codeword the same way (`codeWord = ~codeWord`) -- see the payload-byte
// inversion in loopReceiver() below, applied for the identical reason.
// Live-confirmed necessary: real strong signal spikes (RSSI up to -17dBm
// from a ~-85dBm floor) never triggered DIO0/PayloadReady at all against
// the plain (non-inverted) sync word, no matter how strong the real signal.
const uint8_t POCSAG_SYNC_BYTES[4] = { 0x83, 0x2D, 0xEA, 0x27 };

int rxBatchCount = 0;

// Verbatim port of PagerClient::decodeBCD() (Pager.cpp) -- same special-
// code mapping the TX side's BCD encoder used, just inverted, so a
// numeric page round-trips to exactly what was sent.
char decodeBcdChar(uint8_t b) {
  switch (b) {
    case 0x0A: return '*';
    case 0x0B: return 'U';
    case 0x0C: return ' ';
    case 0x0D: return '-';
    case 0x0E: return ')';
    case 0x0F: return '(';
  }
  return (char)(b + '0');
}

// Decodes symbols out of consecutive MESSAGE code words starting at
// codewords[startIdx] -- same bit-level walk as simDecode() above, but
// generalized to any symbol length (4-bit BCD or 7-bit ASCII, matching
// PagerClient::readData()'s own "BCD for NUMERIC function, ASCII for
// everything else" rule) and stopping the moment it hits something
// that ISN'T a message code word (the next address code word, an idle
// code word, or a frame-sync code word), reporting how many code words
// it consumed so the caller can resume scanning right after them.
String decodeMessageSymbols(uint32_t *codewords, size_t n, size_t startIdx, uint8_t symbolLength, bool bcd, size_t *outConsumed) {
  String out;
  uint32_t prevCw = 0;
  bool overflow = false;
  int8_t ovfBits = 0;
  size_t idx = startIdx;

  for (; idx < n; idx++) {
    uint32_t cw = codewords[idx];
    bool isMessage = (cw & (RADIOLIB_PAGER_MESSAGE_CODE_WORD << (RADIOLIB_PAGER_CODE_WORD_LEN - 1))) != 0;
    if (cw == RADIOLIB_PAGER_IDLE_CODE_WORD || cw == RADIOLIB_PAGER_FRAME_SYNC_CODE_WORD || !isMessage) break;

    uint8_t bitPos = RADIOLIB_PAGER_CODE_WORD_LEN - 1 - symbolLength;
    if (overflow) {
      overflow = false;
      uint8_t currPos = RADIOLIB_PAGER_CODE_WORD_LEN - 1 - symbolLength + ovfBits;
      uint8_t prevPos = RADIOLIB_PAGER_MESSAGE_END_POS;
      uint32_t prevMask = (0x7FUL << prevPos) & ~((uint32_t)0x7FUL << (RADIOLIB_PAGER_MESSAGE_END_POS + ovfBits));
      uint32_t currMask = (0x7FUL << currPos) & ~((uint32_t)1 << (RADIOLIB_PAGER_CODE_WORD_LEN - 1));
      uint8_t prevSymbol = (prevCw & prevMask) >> prevPos;
      uint8_t currSymbol = (cw & currMask) >> currPos;
      uint32_t symbol = prevSymbol << (symbolLength - ovfBits) | currSymbol;
      symbol = rlb_reflect((uint8_t)symbol, 8);
      symbol >>= (8 - symbolLength);
      out += bcd ? decodeBcdChar((uint8_t)symbol) : (char)symbol;
      bitPos += ovfBits;
      bitPos -= symbolLength;
    }

    while (bitPos >= RADIOLIB_PAGER_MESSAGE_END_POS) {
      uint32_t symbol = (cw & (0x7FUL << bitPos)) >> bitPos;
      symbol = rlb_reflect((uint8_t)symbol, 8);
      symbol >>= (8 - symbolLength);
      out += bcd ? decodeBcdChar((uint8_t)symbol) : (char)symbol;
      int8_t remBits = bitPos - RADIOLIB_PAGER_MESSAGE_END_POS;
      if (remBits < symbolLength) {
        prevCw = cw;
        overflow = true;
        ovfBits = remBits;
      }
      bitPos -= symbolLength;
    }
  }
  *outConsumed = idx - startIdx;
  return out;
}

// Walks one full 16-code-word batch, finds every address code word in
// it (there can be more than one -- a batch can carry pages for up to
// 8 different capcodes, one per frame position), decodes each one's
// trailing message code words if it has any, and prints one JSON line
// per decoded page. Address-field/capcode reconstruction ported from
// PagerClient::readData() (Pager.cpp): its own `framePos` there is a
// 1-indexed "code words seen since the last sync word" counter,
// reconstructing capcode's low 3 bits as `framePos/2` -- since our own
// `i` here is 0-indexed and address code words only ever land on even
// i (matching the TX side's own `framePos = 2*(addr&7)` code word
// position), `i/2` is the exact same value under integer division
// (confirmed by hand for every even i in 0..14, not assumed).
// POCSAG has no message-length field, so the last code word's leftover,
// unused symbol slots decode as whatever bit pattern is actually there --
// LIVE-CONFIRMED trailing NUL byte(s) on real DAPNET traffic (e.g.
// "Test message1 ", "XTIME=...  "). Same ambiguity
// src/audio/pager_listener.py already works around for multimon-ng's own
// decode ("multimon-ng pads POCSAG alpha messages with literal '<NUL>'
// tokens ... strip trailing ones for a clean display") -- mirrored here.
void trimTrailingPadding(String &s) {
  while (s.length() > 0 && s[s.length() - 1] == '\0') {
    s.remove(s.length() - 1);
  }
  s.trim();
}

void decodeBatchAndEmit(uint32_t *cw, size_t n) {
  for (size_t i = 0; i < n; i++) {
    uint32_t w = cw[i];
    if (w == RADIOLIB_PAGER_IDLE_CODE_WORD || w == RADIOLIB_PAGER_FRAME_SYNC_CODE_WORD) continue;
    bool isAddress = (w & (RADIOLIB_PAGER_MESSAGE_CODE_WORD << (RADIOLIB_PAGER_CODE_WORD_LEN - 1))) == 0;
    if (!isAddress) continue; // a message code word we didn't consume as part of a preceding address -- skip defensively

    uint32_t addrField = (w & RADIOLIB_PAGER_ADDRESS_BITS_MASK) >> (RADIOLIB_PAGER_ADDRESS_POS - 3);
    uint32_t capcode = addrField | (i / 2);
    uint8_t function = (w & RADIOLIB_PAGER_FUNCTION_BITS_MASK) >> RADIOLIB_PAGER_FUNC_BITS_POS;
    bool bcd = (function == RADIOLIB_PAGER_FUNC_BITS_NUMERIC);
    uint8_t symbolLength = bcd ? 4 : 7;

    size_t consumed = 0;
    String text = decodeMessageSymbols(cw, n, i + 1, symbolLength, bcd, &consumed);
    trimTrailingPadding(text);

    JsonDocument out;
    out["capcode"] = capcode;
    out["function"] = function;
    switch (function) {
      case RADIOLIB_PAGER_FUNC_BITS_NUMERIC:    out["type"] = "numeric";    break;
      case RADIOLIB_PAGER_FUNC_BITS_TONE:       out["type"] = "tone";       break;
      case RADIOLIB_PAGER_FUNC_BITS_ACTIVATION: out["type"] = "activation"; break;
      default:                                  out["type"] = "alpha";     break;
    }
    if (text.length() > 0) out["text"] = text;
    serializeJson(out, Serial);
    Serial.println();

    i += consumed; // resume scanning right after the message code words just consumed
  }
}

void setupReceiver() {
  Serial.println("Radio init (FSK RX mode, no DIO2 needed)");

  int state = radio.beginFSK(POCSAG_FREQ_MHZ, POCSAG_BAUD / 1000.0f, 4.5, POCSAG_RX_BANDWIDTH_KHZ, 17, 16, false);
  if (state != RADIOLIB_ERR_NONE) {
    Serial.print("Radio error: "); Serial.println(state);
    oled("Radio FAIL", String(state));
    while (true) { delay(1000); }
  }

  radio.setSyncWord((uint8_t *)POCSAG_SYNC_BYTES, sizeof(POCSAG_SYNC_BYTES));
  radio.setCrcFiltering(false);
  radio.fixedPacketLengthMode(POCSAG_RX_BATCH_BYTES);
  radio.setEncoding(RADIOLIB_ENCODING_NRZ);
  radio.setDataShaping(RADIOLIB_SHAPING_NONE);

  Serial.println("========================================");
  Serial.println("POCSAG RX ready -- listening on 439.9875 MHz, no DIO2 needed");
  Serial.println("One JSON line per decoded page, e.g.:");
  Serial.println("  {\"capcode\":2041152,\"function\":3,\"type\":\"alpha\",\"text\":\"Hello\"}");
  Serial.println("No BCH error correction -- a code word with enough bit errors is");
  Serial.println("just skipped or shown garbled, same tradeoff multimon-ng makes");
  Serial.println("without a full BCH decoder. NOT LIVE-VERIFIED YET -- this is a");
  Serial.println("first attempt against real hardware, expect to need iteration.");
  Serial.println("========================================");

  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(2);
  display.setCursor(0, 0);
  display.print("RX");
  display.drawFastHLine(0, 20, OLED_WIDTH, SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 26);
  display.print("439.9875MHz  ");
  display.print(POCSAG_BAUD);
  display.print("bps");
  display.setCursor(0, 38);
  display.print("Listening...");
  display.display();
}

bool rxContinuousStarted = false;

void loopReceiver() {
  // FIXED a real flaw in the previous version of this diagnostic:
  // radio.receive(...) is a BLOCKING call that, per RadioLib's own
  // source (SX127x::finishReceive(), called internally on timeout),
  // puts the chip into STANDBY before returning -- meaning the RSSI
  // read right after receive() returned was reading a value AFTER the
  // receiver had already left active RX mode, not a live sample of
  // what the channel looked like during the listen window. Three
  // deliberately-timed real DAPNET sends still showed a flat RSSI
  // trace against that flawed version, which is suggestive but not
  // conclusive given the sampling bug. This version uses non-blocking
  // continuous RX (radio.startReceive(), returns immediately) and
  // polls RSSI at ~5x/sec while genuinely still listening the whole
  // time, checking the DIO0 pin directly (same pin+meaning
  // SX127x::receive()'s own blocking wait polls internally --
  // PayloadReady goes high on a real packet match) for an actual
  // packet without ever leaving RX mode in between samples.
  if (!rxContinuousStarted) {
    // Never checked this return value before -- if startReceive() itself
    // is silently failing, the chip just sits in standby the whole time
    // and getRSSI() returns a frozen value (whatever it was at the
    // moment standby was entered), which would exactly explain a
    // perfectly static reading across many samples (real RF noise
    // essentially never holds bit-identical that long).
    int rxState = radio.startReceive();
    if (rxState != RADIOLIB_ERR_NONE) {
      Serial.print("[rx] startReceive() FAILED, code="); Serial.println(rxState);
    }
    rxContinuousStarted = true;
  }

  static unsigned long lastRssiPrint = 0;
  if (millis() - lastRssiPrint >= 200) {
    lastRssiPrint = millis();
    // skipReceive=true is load-bearing, not cosmetic: SX127x::getRSSICommon()'s
    // FSK branch, by default (skipReceive=false, what plain getRSSI() uses),
    // silently does its OWN startReceive()+read+standby() cycle EVERY call --
    // completely independent of and conflicting with the continuous RX we
    // already armed above. That was undoing our own startReceive() and
    // forcing standby roughly every 200ms, which is almost certainly why
    // nothing was ever received in every earlier test: the receiver was
    // spending nearly all its time in standby because of this diagnostic
    // itself, not actually listening long enough to catch anything.
    // Quiet the log down to just the interesting moments -- printing every
    // ~85dBm noise-floor sample was drowning out the real spikes we're
    // actually looking for. -80dBm is comfortably above the observed ~-80
    // to -89dBm noise floor and comfortably below the real signal spikes
    // confirmed live (-17 to -21dBm), so it only ever suppresses genuine
    // quiet-channel noise, never a real signal.
    float rssi = radio.getRSSI(false, true);
    if (rssi > -80.0f) {
      Serial.print("[rx] live RSSI="); Serial.print(rssi);
      Serial.print(" dBm  DIO0="); Serial.println(digitalRead(LORA_DIO0));
    }
  }

  if (digitalRead(LORA_DIO0)) {
    uint8_t payload[POCSAG_RX_BATCH_BYTES];
    int state = radio.readData(payload, sizeof(payload));
    rxContinuousStarted = false; // re-armed via startReceive() next loop() call

    if (state == RADIOLIB_ERR_NONE) {
      // Big-endian -- POCSAG code words are MSB-first, matching the
      // same bit convention BitWriter/PagerClient use throughout the
      // TX side of this file. Every byte is also INVERTED before use --
      // see POCSAG_SYNC_BYTES' own comment above for why (the chip's
      // hardware demodulator's bit sense is backwards relative to
      // POCSAG's real convention).
      uint32_t cw[16];
      for (int i = 0; i < 16; i++) {
        uint8_t b0 = ~payload[i * 4], b1 = ~payload[i * 4 + 1], b2 = ~payload[i * 4 + 2], b3 = ~payload[i * 4 + 3];
        cw[i] = ((uint32_t)b0 << 24) | ((uint32_t)b1 << 16) | ((uint32_t)b2 << 8) | (uint32_t)b3;
      }
      rxBatchCount++;
      Serial.println("[rx] PACKET RECEIVED");
      decodeBatchAndEmit(cw, 16);

      display.clearDisplay();
      display.setTextColor(SSD1306_WHITE);
      display.setTextSize(2);
      display.setCursor(0, 0);
      display.print("RX #");
      display.print(rxBatchCount);
      display.drawFastHLine(0, 20, OLED_WIDTH, SSD1306_WHITE);
      display.setTextSize(1);
      display.setCursor(0, 26);
      display.println("batch decoded,");
      display.println("see Serial for JSON");
      display.display();
    } else {
      Serial.print("[rx] readData error "); Serial.println(state);
    }
  }
}
#endif // POCSAG_MODE_RX


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

// Boot-complete screen -- shown once in setup() and held until the
// first real TX (fleet or serial) overwrites it via showStats(). Styled
// like showStats() (big header, dividers, dense info rows) instead of
// oled()'s plain two-liner, since this is the screen that sits on
// screen the longest of any of them (from boot until you actually send
// something) and deserves to look more like a real "ready" state than
// a debug message.
void showReadyScreen(int enabledCount) {
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);

  display.setTextSize(2);
  display.setCursor(0, 0);
  display.print("READY");
  display.drawFastHLine(0, 20, OLED_WIDTH, SSD1306_WHITE);

  display.setTextSize(1);
  display.setCursor(0, 26);
  display.print("439.9875MHz  ");
  display.print(POCSAG_BAUD);
  display.print("bps");

  display.setCursor(0, 38);
  display.print("Fleet: ");
  display.print(enabledCount);
  display.print("/");
  display.print(NUM_PAGERS);
  display.print(enabledCount > 0 ? " active" : " (all off)");

  display.setCursor(0, 50);
  display.print("Serial cap: ");
  display.print(SERIAL_DEFAULT_CAPCODE);

  display.display();
}

void showStats(const FakePager &p, int idx, int state) {
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);

  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print(msgTypeLabel(p.type));
  display.print(" ");
  if (idx < 0) {
    display.print("SERIAL SEND"); // manually triggered, not part of the round-robin fleet
  } else {
    display.print(idx + 1);
    display.print("/");
    display.print(NUM_PAGERS);
  }
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
    // Truncate to what fits on two 21-char lines at text size 1. (The
    // "SERIAL SEND" header above already distinguishes a manual send
    // from the round-robin fleet, so both cases get the full two lines
    // for the actual message text rather than spending one on a label.)
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


// ---------- Serial input: JSON-in to send a message live ----------
//
// First half of a JSON line-protocol over serial (one JSON object per
// line) so meshpoint itself could eventually drive this board as a
// real send/receive POCSAG companion -- the same shape as the existing
// Meshtastic/MeshCore USB companion sources in
// src/audio/pager_listener.py's siblings (capture.meshtastic_usb /
// capture.meshcore_usb already talk to a USB-attached radio over
// serial for those protocols), so a `capture.pocsag_usb`-style source
// reusing that same pattern is a believable next step. Input (this
// half) is done; output (receiving real pages back out over serial as
// JSON) is next, deliberately not built yet.
//
// Line format -- one JSON object, capcode optional (defaults to
// SERIAL_DEFAULT_CAPCODE if omitted):
//   {"text": "Hello from the keyboard"}
//   {"capcode": 112, "text": "Hello from the keyboard"}
// Non-blocking (only acts once a full line has arrived), but note the
// round-robin loop below spends most of its time inside delay() calls
// (TX_INTERVAL_MS/ROUND_PAUSE_MS), so a typed line can sit in the UART's
// own hardware buffer for a few seconds before this actually runs --
// expected for a synchronous test sketch, not a bug.
String serialLineBuf;

void checkSerialInput() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    // Treat EITHER \r or \n as "line complete" -- not every serial
    // monitor sends \n specifically (some send \r, some \r\n, depending
    // on the tool and its line-ending setting), and only ever triggering
    // on \n meant a monitor that sends \r alone would silently pile
    // everything into serialLineBuf forever with no send and no error --
    // exactly what "nothing goes out" with no feedback at all looks
    // like. A \r immediately followed by \n (or vice versa) just fires
    // this branch twice with an already-empty buffer the second time,
    // which is a harmless no-op.
    if (c == '\n' || c == '\r') {
      serialLineBuf.trim();
      if (serialLineBuf.length() > 0) {
        // Fires the INSTANT a full line is seen, before any parsing/TX
        // logic runs -- if you see this line but nothing after it, the
        // sketch received your input fine and the problem is downstream
        // (parsing/radio); if you never see even THIS line after typing
        // and pressing Enter, the sketch isn't seeing your input at all
        // (wrong port, wrong baud, or a monitor that isn't actually
        // sending a line ending -- see checkSerialInput()'s own comment).
        Serial.print("[serial] received line: \""); Serial.print(serialLineBuf); Serial.println("\"");
        handleSerialJsonLine(serialLineBuf);
      }
      serialLineBuf = "";
    } else {
      serialLineBuf += c;
    }
  }
}

void handleSerialJsonLine(const String &line) {
  // ArduinoJson v7's JsonDocument auto-sizes its own memory pool, no
  // template capacity guess needed (unlike v6's StaticJsonDocument<N>).
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, line);
  if (err) {
    Serial.print("[serial] JSON parse error: "); Serial.println(err.c_str());
    Serial.println("[serial] expected e.g. {\"text\": \"hello\"} or {\"capcode\": 112, \"text\": \"hello\"}");
    return;
  }

  // `doc["field"] | default` is ArduinoJson's own idiom for "this key,
  // or a fallback if it's missing/null/the wrong type" -- capcode is
  // genuinely optional (falls back to SERIAL_DEFAULT_CAPCODE), text is
  // not (falls back to an empty string, checked for below).
  uint32_t capcode = doc["capcode"] | SERIAL_DEFAULT_CAPCODE;
  String text = doc["text"] | "";
  text.trim();

  if (text.length() == 0) {
    Serial.println("[serial] no (non-empty) \"text\" field, ignored");
    return;
  }
  if (capcode == 0 || capcode > RADIOLIB_PAGER_ADDRESS_MAX) {
    Serial.print("[serial] capcode "); Serial.print(capcode);
    Serial.print(" out of range (1-"); Serial.print(RADIOLIB_PAGER_ADDRESS_MAX); Serial.println("), ignored");
    return;
  }

  sendPocsagAlpha(capcode, text);
}

// Does the actual transmit + feedback -- split out from
// handleSerialJsonLine() so a future JSON output/receive path (or any
// other future caller) can trigger a send without going through JSON
// parsing again.
void sendPocsagAlpha(uint32_t capcode, const String &text) {
  Serial.println("========================================");
  Serial.print("[serial] SENDING  capcode="); Serial.print(capcode);
  Serial.print("  text=\""); Serial.print(text); Serial.println("\"");

  String padded = padAlphaForCleanDecode(text, capcode);
  int state = pager.transmit(padded.c_str(), capcode, RADIOLIB_PAGER_ASCII);
  lastTxOk = (state == RADIOLIB_ERR_NONE);
  txCount++;

  if (lastTxOk) {
    Serial.println("[serial] SENT OK");
  } else {
    Serial.print("[serial] SEND FAILED, code="); Serial.println(state);
  }
  Serial.println("========================================");

  FakePager serialPager = { MSG_ALPHA, true, capcode, padded.c_str() };
  showStats(serialPager, -1, state);
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

#if POCSAG_MODE_RX
  setupReceiver();
  return;
#endif

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

  // Needed before padAlphaForCleanDecode()/simBuild() can be used --
  // same BCH(31,21) constants PagerClient::begin() sets up internally
  // for the radio's own encoder, just a separate instance for
  // simulation (see the comment above simBuild()).
  padSimBch.begin(RADIOLIB_PAGER_BCH_N, RADIOLIB_PAGER_BCH_K, RADIOLIB_PAGER_BCH_PRIMITIVE_POLY);

  // Real enabled count, not just NUM_PAGERS (the array length) -- the
  // boot log/OLED previously always said "4 fake pagers ready" even
  // with every one of them switched off for serial-only testing, which
  // just isn't true.
  int enabledCount = 0;
  for (int i = 0; i < NUM_PAGERS; i++) if (pagers[i].enabled) enabledCount++;
  anyPagerEnabled = (enabledCount > 0);

  Serial.println("========================================");
  Serial.println("Radio + Pager OK");
  Serial.print("Fake pager fleet: "); Serial.print(enabledCount);
  Serial.print("/"); Serial.print(NUM_PAGERS); Serial.println(" enabled");
  for (int i = 0; i < NUM_PAGERS; i++) {
    Serial.print(pagers[i].enabled ? "  #" : "  (disabled) #"); Serial.print(i);
    Serial.print(" "); Serial.print(msgTypeLabel(pagers[i].type));
    Serial.print(" capcode="); Serial.print(pagers[i].capcode);
    if (pagers[i].text) { Serial.print(" text=\""); Serial.print(pagers[i].text); Serial.print("\""); }
    Serial.println();
  }

  Serial.println();
  Serial.println("Serial TX is always available, regardless of the fleet above --");
  Serial.println("send a JSON line + Enter to transmit it live as an alpha page:");
  Serial.print("  {\"text\": \"Hello from meshpoint\"}                  -> sent to default capcode ");
  Serial.println(SERIAL_DEFAULT_CAPCODE);
  Serial.println("  {\"capcode\": 112, \"text\": \"Hello\"}    -> sent to that specific capcode instead");
  Serial.println("(auto-padded for a clean decode -- see padAlphaForCleanDecode())");
  Serial.println("========================================");

  // Holds until the first real TX (fleet or serial) calls showStats()
  // and overwrites it -- see loop()/handleSerialJsonLine().
  showReadyScreen(enabledCount);
}


void loop() {
#if POCSAG_MODE_RX
  loopReceiver();
  return;
#endif

  checkSerialInput();

  if (!anyPagerEnabled) {
    // Whole fleet is off (serial-only testing) -- there's no "round" to
    // speak of, so skip the round-robin bookkeeping/logging entirely
    // instead of printing "round complete" every ~3s for a fleet that's
    // never actually transmitting anything. Small delay so this doesn't
    // spin the CPU pointlessly while still checking Serial often enough
    // to feel responsive.
    delay(50);
    return;
  }

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
