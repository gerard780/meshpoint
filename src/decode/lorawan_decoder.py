"""LoRaWAN 1.0/1.1 MAC frame decoder.

Parses raw LoRaWAN frames received from the SX1302 concentrator and returns
a Packet with the decoded fields.  Payload decryption requires the session
keys (AppSKey / NwkSKey) which are not known to a passive listener, so
FRMPayload is kept as hex in decoded_payload and the packet is marked
decrypted=False.

Supported MType values:
  000  Join-Request     (uplink)
  001  Join-Accept      (downlink -- see below)
  010  Unconfirmed Data Up (uplink)
  100  Confirmed Data Up   (uplink)
  110  Rejoin-Request (LoRaWAN 1.1, uplink)

Join-Accept is a network-server-originated downlink, not something an
uplink-listening concentrator should normally expect to hear at all --
but there's no LoRa-PHY reason it couldn't, if the RX1/RX2 frequency+SF
the real serving gateway replies on happens to be inside this
concentrator's own monitored channel plan (uplink and downlink share the
same sync word; the uplink/downlink distinction only exists at the MAC
layer, after MHDR is already decoded). Recognized here so that's
findable empirically rather than assumed either way -- see project
memory ("LoRaWAN key store + payload decrypt") for why this matters:
deriving a session's real AppSKey for FRMPayload decrypt requires
NwkKey-decrypting a real captured Join-Accept. Kept undecrypted (no
NwkKey lookup here yet) -- this module stays a stateless parser; that
lookup and the AES decrypt/key-derivation happen one layer up, in
whatever wires in a configured key store.
"""
from __future__ import annotations

import logging
import struct
import time
from typing import Optional

from src.models.packet import Packet, PacketType, Protocol
from src.models.signal import SignalMetrics

logger = logging.getLogger(__name__)

# MHDR MType nibble values
_MTYPE_JOIN_REQUEST      = 0b000
_MTYPE_JOIN_ACCEPT       = 0b001
_MTYPE_UNCONF_DATA_UP    = 0b010
_MTYPE_UNCONF_DATA_DOWN  = 0b011
_MTYPE_CONF_DATA_UP      = 0b100
_MTYPE_CONF_DATA_DOWN    = 0b101
_MTYPE_REJOIN_REQUEST    = 0b110
_MTYPE_PROPRIETARY       = 0b111

# Minimum frame lengths
_MIN_JOIN_REQUEST = 23   # MHDR(1) + AppEUI(8) + DevEUI(8) + DevNonce(2) + MIC(4)
_MIN_DATA_FRAME   = 12   # MHDR(1) + DevAddr(4) + FCtrl(1) + FCnt(2) + MIC(4)
_MIN_REJOIN_0_2   = 19   # MHDR(1) + Type(1) + NetID(3) + DevEUI(8) + RJcount(2) + MIC(4)
_MIN_REJOIN_1    = 23   # MHDR(1) + Type(1) + JoinEUI(8) + DevEUI(8) + RJcount(2) + MIC(4)
# Join-Accept: MHDR(1) + AES-encrypted block, where the encrypted plaintext
# is JoinNonce(3)+NetID(3)+DevAddr(4)+DLSettings(1)+RxDelay(1)[+CFList(16)]+MIC(4)
# -- 16 bytes without CFList, 32 with, so the frame on the wire is 17 or 33
# bytes total. Both are valid; anything else isn't a real Join-Accept.
_JOIN_ACCEPT_LEN_NO_CFLIST = 17
_JOIN_ACCEPT_LEN_WITH_CFLIST = 33


def _eui_str(raw: bytes) -> str:
    """Format 8 LSB-first bytes as XX:XX:XX:XX:XX:XX:XX:XX."""
    return ":".join(f"{b:02X}" for b in reversed(raw))


def _hex(raw: bytes) -> str:
    return raw.hex().upper()


_JOIN_ACCEPT_CORRELATE_WINDOW_S = 10.0  # RX1/RX2 land within ~1-2s of the
# Join-Request in practice; 10s gives generous margin for a slow gateway
# without risking matching a stale, unrelated request from way earlier.


class LoRaWANDecoder:
    """LoRaWAN MAC frame parser. Mostly stateless, with one exception: it
    remembers the most recent Join-Request's DevEUI/DevNonce/time so a
    Join-Accept arriving shortly after can be tagged as "likely this
    device's" -- there's no DevEUI in a Join-Accept's own (still
    encrypted) bytes to identify it by otherwise. Best-effort only (two
    devices could join within the same window) -- real attribution needs
    an actual NwkKey decrypt, done one layer up, not here.
    """

    def __init__(self) -> None:
        self._last_join_request: Optional[dict] = None

    def decode(
        self,
        raw_bytes: bytes,
        signal: Optional[SignalMetrics] = None,
    ) -> Optional[Packet]:
        if len(raw_bytes) < 1:
            return None

        mhdr = raw_bytes[0]
        mtype = (mhdr >> 5) & 0x07
        major = mhdr & 0x03

        if major != 0:
            # LoRaWAN major version field is always 0 for 1.0/1.1
            logger.debug("LoRaWAN: unknown Major=%d, skipping", major)
            return None

        if mtype == _MTYPE_JOIN_REQUEST:
            return self._decode_join_request(raw_bytes, signal)
        if mtype == _MTYPE_JOIN_ACCEPT:
            return self._decode_join_accept(raw_bytes, signal)
        if mtype in (_MTYPE_UNCONF_DATA_UP, _MTYPE_CONF_DATA_UP):
            return self._decode_data_up(raw_bytes, mtype, signal)
        if mtype == _MTYPE_REJOIN_REQUEST:
            return self._decode_rejoin(raw_bytes, signal)

        # Other downlinks (Unconfirmed/Confirmed Data Down) aren't expected
        # to be heard by an uplink-oriented concentrator and aren't useful
        # here even if they were (no MAC-command handling downstream) --
        # unlike Join-Accept, there's nothing this app would do with one.
        logger.debug("LoRaWAN: MType=0x%02X not handled", mtype)
        return None

    # ── Join-Request ────────────────────────────────────────────────────────

    def _decode_join_request(
        self,
        raw: bytes,
        signal: Optional[SignalMetrics],
    ) -> Optional[Packet]:
        if len(raw) < _MIN_JOIN_REQUEST:
            logger.debug("LoRaWAN Join-Request too short: %d bytes", len(raw))
            return None

        app_eui   = raw[1:9]    # LSB
        dev_eui   = raw[9:17]   # LSB
        dev_nonce = struct.unpack_from("<H", raw, 17)[0]
        mic       = _hex(raw[19:23])

        app_eui_str = _eui_str(app_eui)
        dev_eui_str = _eui_str(dev_eui)

        logger.info(
            "LoRaWAN Join-Request: DevEUI=%s AppEUI=%s DevNonce=%d",
            dev_eui_str, app_eui_str, dev_nonce,
        )

        self._last_join_request = {
            "dev_eui": dev_eui_str,
            "app_eui": app_eui_str,
            "dev_nonce": dev_nonce,
            "at": time.monotonic(),
        }

        return Packet(
            packet_id=f"join:{dev_nonce:04X}:{_hex(dev_eui)}",
            source_id=dev_eui_str,
            destination_id="network-server",
            protocol=Protocol.LORAWAN,
            packet_type=PacketType.LORAWAN_JOIN,
            decoded_payload={
                "mtype": "JoinRequest",
                "app_eui": app_eui_str,
                "dev_eui": dev_eui_str,
                "dev_nonce": dev_nonce,
                "mic": mic,
            },
            decrypted=True,
            signal=signal,
            capture_source="concentrator",
        )

    # ── Join-Accept ──────────────────────────────────────────────────────────

    def _decode_join_accept(
        self,
        raw: bytes,
        signal: Optional[SignalMetrics],
    ) -> Optional[Packet]:
        if len(raw) not in (_JOIN_ACCEPT_LEN_NO_CFLIST, _JOIN_ACCEPT_LEN_WITH_CFLIST):
            logger.debug(
                "LoRaWAN: MType=JoinAccept but wrong length (%d bytes, "
                "expected %d or %d) -- not a real Join-Accept",
                len(raw), _JOIN_ACCEPT_LEN_NO_CFLIST, _JOIN_ACCEPT_LEN_WITH_CFLIST,
            )
            return None

        encrypted = raw[1:]
        has_cflist = len(raw) == _JOIN_ACCEPT_LEN_WITH_CFLIST

        likely_dev_eui = None
        if self._last_join_request is not None:
            age = time.monotonic() - self._last_join_request["at"]
            if age <= _JOIN_ACCEPT_CORRELATE_WINDOW_S:
                likely_dev_eui = self._last_join_request["dev_eui"]

        logger.info(
            "LoRaWAN Join-Accept: %d bytes (cflist=%s), likely for DevEUI=%s "
            "-- real fields need an NwkKey decrypt, not done here",
            len(raw), has_cflist, likely_dev_eui or "unknown",
        )

        return Packet(
            packet_id=f"joinaccept:{_hex(encrypted[:4])}",
            source_id="network-server",
            destination_id=likely_dev_eui or "unknown",
            protocol=Protocol.LORAWAN,
            packet_type=PacketType.LORAWAN_JOIN_ACCEPT,
            decoded_payload={
                "mtype": "JoinAccept",
                "likely_dev_eui": likely_dev_eui,
                "has_cflist": has_cflist,
                "encrypted_payload": _hex(encrypted),
            },
            decrypted=False,  # needs NwkKey to even parse the real fields, let alone verify
            signal=signal,
            capture_source="concentrator",
        )

    # ── Data Up (Unconfirmed / Confirmed) ───────────────────────────────────

    def _decode_data_up(
        self,
        raw: bytes,
        mtype: int,
        signal: Optional[SignalMetrics],
    ) -> Optional[Packet]:
        if len(raw) < _MIN_DATA_FRAME:
            logger.debug("LoRaWAN Data frame too short: %d bytes", len(raw))
            return None

        # FHDR
        dev_addr = struct.unpack_from("<I", raw, 1)[0]
        fctrl    = raw[5]
        fcnt     = struct.unpack_from("<H", raw, 6)[0]
        fopts_len = fctrl & 0x0F
        adr       = bool(fctrl & 0x80)
        ack       = bool(fctrl & 0x20)

        fhdr_end = 8 + fopts_len
        if len(raw) < fhdr_end + 4:   # need at least MIC after FHDR
            logger.debug("LoRaWAN Data frame too short for FOpts: %d bytes", len(raw))
            return None

        fopts = _hex(raw[8:fhdr_end]) if fopts_len else ""

        # FPort + FRMPayload
        mic_offset = len(raw) - 4
        mic        = _hex(raw[mic_offset:])
        fport      = None
        frm_payload = ""

        if fhdr_end < mic_offset:
            fport = raw[fhdr_end]
            frm_payload = _hex(raw[fhdr_end + 1: mic_offset])

        confirmed    = (mtype == _MTYPE_CONF_DATA_UP)
        dev_addr_str = f"{dev_addr:08X}"

        logger.info(
            "LoRaWAN Data Up (%s): DevAddr=%s FCnt=%d FPort=%s payload=%d bytes",
            "Confirmed" if confirmed else "Unconfirmed",
            dev_addr_str, fcnt, fport,
            len(raw[fhdr_end + 1: mic_offset]) if fport is not None else 0,
        )

        return Packet(
            packet_id=f"lora:{dev_addr_str}:{fcnt}",
            source_id=dev_addr_str,
            destination_id="network-server",
            protocol=Protocol.LORAWAN,
            packet_type=PacketType.LORAWAN_DATA,
            decoded_payload={
                "mtype": "ConfirmedDataUp" if confirmed else "UnconfirmedDataUp",
                "dev_addr": dev_addr_str,
                "fcnt": fcnt,
                "adr": adr,
                "ack": ack,
                "fport": fport,
                "fopts": fopts or None,
                "frm_payload": frm_payload or None,
                "mic": mic,
            },
            decrypted=False,   # FRMPayload encrypted; keys not available
            signal=signal,
            capture_source="concentrator",
        )

    # ── Rejoin-Request (LoRaWAN 1.1) ────────────────────────────────────────

    def _decode_rejoin(
        self,
        raw: bytes,
        signal: Optional[SignalMetrics],
    ) -> Optional[Packet]:
        if len(raw) < 2:
            return None

        rejoin_type = raw[1]
        mic = _hex(raw[-4:])

        if rejoin_type in (0, 2):
            if len(raw) < _MIN_REJOIN_0_2:
                logger.debug("LoRaWAN Rejoin-0/2 too short: %d bytes", len(raw))
                return None
            net_id    = _hex(raw[2:5])
            dev_eui   = _eui_str(raw[5:13])
            rjcount   = struct.unpack_from("<H", raw, 13)[0]
            payload   = {
                "mtype": f"RejoinRequest{rejoin_type}",
                "rejoin_type": rejoin_type,
                "net_id": net_id,
                "dev_eui": dev_eui,
                "rjcount": rjcount,
                "mic": mic,
            }
            src = dev_eui
        elif rejoin_type == 1:
            if len(raw) < _MIN_REJOIN_1:
                logger.debug("LoRaWAN Rejoin-1 too short: %d bytes", len(raw))
                return None
            join_eui = _eui_str(raw[2:10])
            dev_eui  = _eui_str(raw[10:18])
            rjcount  = struct.unpack_from("<H", raw, 18)[0]
            payload  = {
                "mtype": "RejoinRequest1",
                "rejoin_type": 1,
                "join_eui": join_eui,
                "dev_eui": dev_eui,
                "rjcount": rjcount,
                "mic": mic,
            }
            src = dev_eui
        else:
            logger.debug("LoRaWAN Rejoin: unknown type %d", rejoin_type)
            return None

        logger.info("LoRaWAN Rejoin-%d: DevEUI=%s", rejoin_type, src)

        return Packet(
            packet_id=f"rejoin:{rejoin_type}:{src}",
            source_id=src,
            destination_id="network-server",
            protocol=Protocol.LORAWAN,
            packet_type=PacketType.LORAWAN_REJOIN,
            decoded_payload=payload,
            decrypted=True,
            signal=signal,
            capture_source="concentrator",
        )
