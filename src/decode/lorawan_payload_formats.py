"""User-defined LoRaWAN application payload field decoding.

FPort/FRMPayload have no fixed meaning in LoRaWAN itself -- both are
entirely up to the application, unlike the MAC-layer fields decoded
elsewhere in lorawan_decoder.py. This decodes a device's own known
payload shape from a declarative field list configured per-DevEUI (see
LoRaWANConfig.devices[...]['payload_fields'] in src/config.py, loaded
into LoRaWANKeyStore) -- e.g. this device's own TTN payload formatter,

    var raw = (bytes[0] << 8) | bytes[1];
    if (raw & 0x8000) raw -= 0x10000;
    return { data: { temperature: raw / 100 } };

becomes

    payload_fields:
      - name: temperature_c
        type: int16_be
        scale: 0.01

Declarative on purpose, not a real scripting language (no eval() of
arbitrary user-supplied code from a config file) -- covers the common
case (scaled integer sensor fields) safely. Never applied as a blanket
rule based on FPort alone; only for devices that explicitly configure it.
"""
from __future__ import annotations

import struct
from typing import Optional, TypedDict

# name -> (struct format char, byte size)
_FIELD_TYPES: dict[str, tuple[str, int]] = {
    "int8": ("b", 1),
    "uint8": ("B", 1),
    "int16_be": (">h", 2),
    "int16_le": ("<h", 2),
    "uint16_be": (">H", 2),
    "uint16_le": ("<H", 2),
    "int32_be": (">i", 4),
    "int32_le": ("<i", 4),
    "uint32_be": (">I", 4),
    "uint32_le": ("<I", 4),
}

KNOWN_FIELD_TYPES = frozenset(_FIELD_TYPES.keys())


class PayloadField(TypedDict, total=False):
    name: str
    type: str
    offset: int    # optional -- defaults to right after the previous field
    scale: float    # optional -- defaults to 1.0 (raw integer, unscaled)


def decode_payload(fields: list[PayloadField], payload: bytes) -> dict:
    """Extracts each configured field from payload. Best-effort: a field
    whose offset+size runs past the end of payload, or whose type isn't
    recognized, is silently skipped rather than failing the whole decode
    -- matches this module's "opt-in, never surprising" philosophy; a
    malformed/short packet shouldn't hide the fields that DO fit.
    """
    result: dict = {}
    cursor = 0
    for field in fields:
        field_type = field.get("type", "")
        spec = _FIELD_TYPES.get(field_type)
        name = field.get("name")
        offset = field.get("offset", cursor)

        if spec is None or not name:
            continue

        fmt, size = spec
        if offset + size > len(payload):
            cursor = offset + size
            continue

        raw = struct.unpack_from(fmt, payload, offset)[0]
        scale = field.get("scale", 1.0)
        # round(..., 6) -- binary float multiplication (e.g. 33 * 0.1)
        # routinely produces trailing noise (3.3000000000000003) that has
        # nothing to do with the actual sensor's real precision; round it
        # away rather than show it in the dashboard. 6 decimals is well
        # past any realistic sensor scale factor's meaningful precision.
        result[name] = round(raw * scale, 6) if scale != 1.0 else raw

        cursor = offset + size

    return result
