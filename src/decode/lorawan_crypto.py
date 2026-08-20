"""LoRaWAN 1.1 Join-Accept decrypt, session-key derivation, and FRMPayload
decrypt (LoRaWAN 1.1 spec sections 6.2.4, 6.2.5, 4.3.3).

Pure functions, no state -- mirrors crypto_service.py's style (static
methods, byte-level struct packing, pycryptodome AES primitives) but a
separate module since the wire formats/key material are unrelated to
Meshtastic/Meshcore's own AES-CTR scheme.

NOT independently verified against an official LoRaWAN test vector or a
second implementation -- built directly from the spec's own algorithm
description and round-trip-tested (encrypt-then-decrypt recovers the
original plaintext) for internal consistency, which catches offset/
byte-order bugs in this code but can't catch a spec misreading shared
between the encrypt and decrypt sides of the same round-trip. Before
trusting a real decrypted AppSKey/plaintext for anything beyond
diagnostics, cross-check it against an independent source (e.g. an
open-source LoRaWAN library, or TTN's own payload view if it ever
exposes derived session keys) at least once.
"""
from __future__ import annotations

import struct
from typing import Optional, TypedDict

from Crypto.Cipher import AES  # nosec B413 -- pycryptodome, not deprecated pyCrypto


class JoinAcceptFields(TypedDict):
    join_nonce: bytes   # 3 bytes, on-the-wire order (LSB-first)
    net_id: bytes        # 3 bytes, on-the-wire order
    dev_addr: int         # 32-bit
    dl_settings: int       # 1 byte
    rx_delay: int            # 1 byte
    cflist: Optional[bytes]   # 16 bytes if present, else None
    mic: bytes                 # 4 bytes


def decrypt_join_accept(nwk_key: bytes, encrypted: bytes) -> Optional[JoinAcceptFields]:
    """Recover a Join-Accept's plaintext fields.

    The network server encrypts Join-Accept content using an AES128
    *decrypt* operation with NwkKey (spec 6.2.4) -- deliberately, so
    that end devices, which only need AES *encrypt* in hardware, can
    recover the plaintext by running the same operation in reverse:
    AES128-ECB *encrypt* the ciphertext with NwkKey. Meshpoint is a
    passive listener here, not the device, but the same trick applies
    -- we just need the plaintext, not to actually be the device.

    ``encrypted`` is the frame's bytes after MHDR (16 bytes without a
    CFList, 32 with) -- exactly what lorawan_decoder.py's
    ``decoded_payload["encrypted_payload"]`` already carries.
    """
    if len(encrypted) not in (16, 32):
        return None

    cipher = AES.new(nwk_key, AES.MODE_ECB)
    plaintext = cipher.encrypt(encrypted)

    has_cflist = len(plaintext) == 32
    return JoinAcceptFields(
        join_nonce=plaintext[0:3],
        net_id=plaintext[3:6],
        dev_addr=struct.unpack_from("<I", plaintext, 6)[0],
        dl_settings=plaintext[10],
        rx_delay=plaintext[11],
        cflist=plaintext[12:28] if has_cflist else None,
        mic=plaintext[-4:],
    )


def derive_app_skey(
    app_key: bytes, join_nonce: bytes, join_eui: bytes, dev_nonce: int
) -> bytes:
    """AppSKey = aes128_encrypt(AppKey, 0x02 | JoinNonce | JoinEUI | DevNonce | pad16)

    Spec 6.2.5. Keyed by AppKey, NOT NwkKey -- different key than the one
    that decrypted the Join-Accept itself (that used NwkKey, spec 6.2.4).
    ``join_nonce``/``join_eui`` must be the raw on-the-wire byte order
    (join_nonce as returned by decrypt_join_accept(), join_eui as raw
    bytes from the Join-Request -- NOT the reversed/colon-formatted
    string _eui_str() produces for display, that's a human-readable
    transform only).
    """
    block = (
        bytes([0x02])
        + join_nonce
        + join_eui
        + struct.pack("<H", dev_nonce)
    )
    block = block.ljust(16, b"\x00")  # 1+3+8+2=14 bytes, pad to 16 per spec

    cipher = AES.new(app_key, AES.MODE_ECB)
    return cipher.encrypt(block)


def decrypt_frm_payload(
    app_skey: bytes,
    frm_payload: bytes,
    dev_addr: int,
    fcnt: int,
    uplink: bool = True,
) -> bytes:
    """FRMPayload decrypt (spec 4.3.3) -- and encrypt, symmetric XOR cipher.

    Builds a keystream from AES128-ECB-encrypted counter blocks (LoRaWAN's
    own construction; not a generic CTR-mode library call, since the
    per-block layout below doesn't map onto a plain nonce+counter the way
    AES.MODE_CTR expects) and XORs it with the payload.

    ``fcnt`` is the frame's own 16-bit FCnt zero-extended to 32 bits --
    correct as long as this session hasn't rolled over 65536 frames yet;
    full 32-bit FCnt recovery across rollovers isn't implemented, matching
    the v1 scope written up in project memory (AppSKey-only, FPort>0,
    no MIC verify).
    """
    direction = 0 if uplink else 1
    cipher = AES.new(app_skey, AES.MODE_ECB)

    num_blocks = (len(frm_payload) + 15) // 16
    keystream = b""
    for i in range(1, num_blocks + 1):
        a_block = (
            bytes([0x01, 0x00, 0x00, 0x00, 0x00, direction])
            + struct.pack("<I", dev_addr)
            + struct.pack("<I", fcnt)
            + bytes([0x00, i])
        )
        keystream += cipher.encrypt(a_block)

    return bytes(b ^ k for b, k in zip(frm_payload, keystream))
