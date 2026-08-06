"""Live commands for the RF Environment companion (extra/rfenv_companion).

Mounted under ``/api/config/rfenv-companion/*``. Mirrors
dapnet_config_routes.py's own role exactly (commands sent to a
connected companion over its live serial connection, not config
persisted in local.yaml) -- but simpler in one respect: there's only
ever one configured `capture.rfenv_companion` device (see
``_build_rfenv_companion_service`` in server.py), so there's no
per-device ``label`` to resolve against a list of sources, just the one
module-level service reference.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config/rfenv-companion", tags=["config", "rfenv-companion"])

_service = None  # RfEnvCompanionScanService, or None if not configured/running


def init_routes(service=None) -> None:
    global _service
    _service = service


def _require_connected():
    if _service is None or not _service.is_running:
        raise HTTPException(503, "RF Environment companion not connected")
    return _service


class RfenvWebPasswordUpdate(BaseModel):
    password: str


@router.put("/web-password")
async def update_rfenv_web_password(
    req: RfenvWebPasswordUpdate,
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Set the companion's web dashboard login password over its live
    serial connection.

    Never cached, logged, or echoed back on this side -- Meshpoint is a
    pure relay here, same reasoning dapnet_config_routes.py's own
    identical route gives. Nothing persists in local.yaml either; it
    lives entirely in the companion's own NVS.
    """
    service = _require_connected()
    result = await service.send_command(
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
    ssid: str
    password: str = ""  # empty is valid -- open networks have no password


@router.put("/wifi")
async def update_rfenv_wifi(
    req: RfenvWifiUpdate,
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Set the companion's WiFi SSID/password over its live serial
    connection.

    Saving alone does NOT reconnect -- setupWifiOta() only runs once at
    boot. Call POST .../reboot afterward (or the companion's own web
    Reboot button, if still reachable) to actually apply it. Same
    caveat and reasoning as dapnet_config_routes.py's own /wifi route.
    """
    service = _require_connected()
    result = await service.send_command(
        {"cmd": "set_wifi", "ssid": req.ssid, "password": req.password},
        expect_type="set_wifi_result",
        timeout=5.0,
    )
    if result is None:
        raise HTTPException(503, "No reply from companion (timed out)")
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "Rejected by companion")

    return {"saved": True, "ssid": result.get("ssid", "")}


@router.post("/reboot")
async def reboot_rfenv_companion(
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Reboot the companion over its live serial connection -- e.g.
    right after saving new WiFi credentials, without needing the
    companion's own web dashboard (which the whole WiFi-set flow exists
    to route around in the first place, since bad credentials could
    make that dashboard unreachable too).

    NOTE: whether Meshpoint's own serial connection survives the reboot
    depends on the board's USB hardware, same as
    dapnet_config_routes.py's own identical caveat --
    RfEnvCompanionScanService has no reconnect loop (matching
    DapnetSerialSource's own documented limitation), so a Meshpoint
    service restart may be needed afterward if it doesn't.
    """
    service = _require_connected()
    result = await service.send_command(
        {"cmd": "reboot"}, expect_type="reboot_result", timeout=5.0,
    )
    if result is None:
        raise HTTPException(503, "No reply from companion (timed out)")
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "Rejected by companion")

    return {"saved": True}
