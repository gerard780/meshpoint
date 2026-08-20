"""LoRaWAN device key management for Configuration -> LoRaWAN.

Stores each device's OTAA root keys (AppKey/NwkKey, from TTN Console's
device registration page) keyed by DevEUI -- config.lorawan.devices, see
src/config.py's LoRaWANConfig. NOT the per-session AppSKey: that's
derived live from each device's own captured Join-Accept (see
lorawan_keystore.py/lorawan_crypto.py) and is never configured directly
-- a device configured here won't decrypt anything until its next real
OTAA join happens over the air and gets captured, unlike
Meshtastic/Meshcore's channel keys which apply immediately.

Same "list of entries, replace wholesale" PUT shape as
config_routes.py's own update_channels()/update_meshcore_channels(), and
the same "return real key material in GET, no server-side masking"
convention already established there -- this is a locally-hosted admin
dashboard behind auth, not a multi-tenant service.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims
from src.config import AppConfig, save_section_to_yaml
from src.decode.lorawan_keystore import LoRaWANKeyStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config", tags=["config"])

_config: AppConfig | None = None
_keystore: LoRaWANKeyStore | None = None


def init_routes(config: AppConfig, keystore: LoRaWANKeyStore | None = None) -> None:
    global _config, _keystore
    _config = config
    _keystore = keystore


def reset_routes() -> None:
    global _config, _keystore
    _config = None
    _keystore = None


def _validate_hex_key(value: str, field_name: str) -> str:
    value = value.strip()
    try:
        raw = bytes.fromhex(value)
    except ValueError:
        raise ValueError(f"{field_name} must be a hex string")
    if len(raw) != 16:
        raise ValueError(f"{field_name} must be 16 bytes (32 hex chars), got {len(raw)}")
    return value.upper()


class LoRaWANDeviceEntry(BaseModel):
    dev_eui: str
    app_key: str
    nwk_key: str

    @field_validator("app_key")
    @classmethod
    def _validate_app_key(cls, v: str) -> str:
        return _validate_hex_key(v, "app_key")

    @field_validator("nwk_key")
    @classmethod
    def _validate_nwk_key(cls, v: str) -> str:
        return _validate_hex_key(v, "nwk_key")


class LoRaWANDevicesUpdate(BaseModel):
    devices: list[LoRaWANDeviceEntry]


@router.get("/lorawan")
async def get_lorawan_config():
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    return {
        "devices": [
            {"dev_eui": dev_eui, "app_key": keys.get("app_key", ""), "nwk_key": keys.get("nwk_key", "")}
            for dev_eui, keys in _config.lorawan.devices.items()
        ]
    }


@router.put("/lorawan")
async def update_lorawan_config(
    req: LoRaWANDevicesUpdate,
    _claims: SessionClaims = Depends(require_admin),
):
    """Replace the configured device list wholesale. Applies to the live
    keystore immediately -- but a device only actually starts decrypting
    once its next real Join-Accept is captured and decrypted (see this
    module's own docstring for why session keys can't just be set here)."""
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    devices = {
        entry.dev_eui.upper(): {"app_key": entry.app_key, "nwk_key": entry.nwk_key}
        for entry in req.devices
    }

    _config.lorawan.devices = devices
    try:
        save_section_to_yaml("lorawan", {"devices": devices})
    except PermissionError as exc:
        raise HTTPException(403, str(exc))

    if _keystore is not None:
        for dev_eui, keys in devices.items():
            try:
                _keystore.add_device(dev_eui, keys["app_key"], keys["nwk_key"])
            except ValueError as exc:
                raise HTTPException(400, f"{dev_eui}: {exc}")

    logger.info("LoRaWAN: %d device(s) configured (%s)", len(devices), ", ".join(devices) or "none")

    return {"saved": True, "device_count": len(devices)}
