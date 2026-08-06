"""Live commands for the RF Environment companion (extra/rfenv_companion).

Mounted under ``/api/config/rfenv-companion/*``. Every command here
targets a ``port`` the caller explicitly picks -- the same "Device to
flash" USB-serial port already selectable on the Firmware page -- via
a short-lived, one-off serial connection, rather than requiring that
device to already be the one persistent ``capture.rfenv_companion``
device Meshpoint happens to be polling. Provisioning a brand new board
(setting its WiFi/web password right after flashing, before it's ever
registered as a companion at all) is the main use case, so tying this
to an already-configured/connected service would rule that out
entirely.

If the chosen port happens to be the currently-configured companion's
own port, the live ``RfEnvCompanionScanService`` is briefly released
(stopped) so the one-off connection can use the port without a
device-busy conflict, then handed back -- same release/reconnect
pattern ``rfenv_companion_firmware_routes.py``'s own flash route
already uses for the identical reason.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims
from src.config import AppConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config/rfenv-companion", tags=["config", "rfenv-companion"])

_BAUD = 115200  # matches rfenv_companion.ino's Serial.begin(115200)

_config: AppConfig | None = None
_service = None  # RfEnvCompanionScanService, or None if not configured/running


def init_routes(config: AppConfig | None = None, service=None) -> None:
    global _config, _service
    _config = config
    _service = service


def _validate_port(port: str) -> None:
    from src.hal.usb_classifier import list_serial_ports_with_stable_paths
    real_ports = {
        value
        for dev in list_serial_ports_with_stable_paths()
        if dev.vid is not None
        for value in (dev.device, dev.stable_path, dev.by_id, dev.by_path)
        if value
    }
    if port not in real_ports:
        raise HTTPException(400, "Selected port is not a currently connected USB-serial device")


def _blocking_send(port: str, command: dict, expect_type: str, timeout: float) -> dict | None:
    """Runs in a worker thread (pyserial is blocking) -- opens its own
    short-lived serial connection, writes one command, reads lines
    until a matching reply or ``timeout``, then closes. Parses the
    same newline-JSON-with-a-``type``-field wire format
    RfEnvCompanionScanService's own reader thread does, but as a
    deliberate one-shot rather than a long-lived connection -- there's
    no background thread or pending-future bookkeeping to share here.
    """
    import serial

    ser = serial.Serial(port, _BAUD, timeout=1.0)
    try:
        ser.write(json.dumps(command).encode() + b"\n")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = ser.readline()
            if not line or not line.strip():
                continue
            stripped = line.strip()
            if stripped[:1] != b"{":
                continue  # boot banners / plain-text log lines -- not for us
            try:
                data = json.loads(stripped)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if isinstance(data, dict) and data.get("type") == expect_type:
                return data
        return None
    finally:
        ser.close()


async def _send_command(port: str, command: dict, expect_type: str, timeout: float) -> dict | None:
    _validate_port(port)
    owns_port = (
        _service is not None
        and getattr(_service, "port", None) == port
        and _service.is_running
    )
    if not owns_port:
        return await asyncio.to_thread(_blocking_send, port, command, expect_type, timeout)

    logger.info("rfenv-companion live command: releasing %s from the running companion service", port)
    await _service.stop()
    try:
        return await asyncio.to_thread(_blocking_send, port, command, expect_type, timeout)
    finally:
        await _service.start()


class RfenvWebPasswordUpdate(BaseModel):
    port: str
    password: str


@router.put("/web-password")
async def update_rfenv_web_password(
    req: RfenvWebPasswordUpdate,
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Set the companion's web dashboard login password over a direct
    one-off serial connection to ``req.port``.

    Never cached, logged, or echoed back on this side -- Meshpoint is a
    pure relay here. Nothing persists in local.yaml either; it lives
    entirely in the companion's own NVS.
    """
    result = await _send_command(
        req.port,
        {"cmd": "set_web_password", "password": req.password},
        expect_type="set_web_password_result",
        timeout=5.0,
    )
    if result is None:
        raise HTTPException(503, "No reply from companion (timed out)")
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "Rejected by companion")

    return {"saved": True}


class RfenvWifiUpdate(BaseModel):
    port: str
    ssid: str
    password: str = ""  # empty is valid -- open networks have no password


@router.put("/wifi")
async def update_rfenv_wifi(
    req: RfenvWifiUpdate,
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Set the companion's WiFi SSID/password over a direct one-off
    serial connection to ``req.port``.

    Saving alone does NOT reconnect -- setupWifiOta() only runs once at
    boot. Call POST .../reboot afterward (or the companion's own web
    Reboot button, if still reachable) to actually apply it.
    """
    result = await _send_command(
        req.port,
        {"cmd": "set_wifi", "ssid": req.ssid, "password": req.password},
        expect_type="set_wifi_result",
        timeout=5.0,
    )
    if result is None:
        raise HTTPException(503, "No reply from companion (timed out)")
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "Rejected by companion")

    return {"saved": True, "ssid": result.get("ssid", "")}


class RfenvPortAction(BaseModel):
    port: str


@router.post("/reboot")
async def reboot_rfenv_companion(
    req: RfenvPortAction,
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Reboot the companion at ``req.port`` over a direct one-off
    serial connection -- e.g. right after saving new WiFi credentials.

    NOTE: whether Meshpoint's own persistent serial connection (if
    this port is the configured companion) survives the reboot depends
    on the board's USB hardware -- RfEnvCompanionScanService has no
    reconnect loop, so a Meshpoint service restart may be needed
    afterward if it doesn't reconnect on its own.
    """
    result = await _send_command(
        req.port, {"cmd": "reboot"}, expect_type="reboot_result", timeout=5.0,
    )
    if result is None:
        raise HTTPException(503, "No reply from companion (timed out)")
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "Rejected by companion")

    return {"saved": True}
