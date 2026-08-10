"""REST endpoints for live Meshtastic USB serial device configuration.

Mounted under ``/api/config/serial/*``. Live Region / modem preset /
broadcast intervals / Bluetooth writes over an open serial connection.
Credit: javastraat/meshpoint ``9bfbe56`` / ``9e06352`` / ``4a6055c``.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims
from src.config import AppConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config/serial", tags=["config", "serial"])

_config: AppConfig | None = None
_serial_sources: list = []


def init_routes(config: AppConfig, serial_sources=None) -> None:
    global _config, _serial_sources
    _config = config
    _serial_sources = serial_sources or []


def _resolve_serial_source(label: str):
    """Match ``serial`` / ``serial_<label>`` to a capture source."""
    name = f"serial_{label}" if label else "serial"
    for src in _serial_sources:
        if src.name == name:
            return src
    return None


def _require_connected_source(label: str):
    if _config is None:
        raise HTTPException(503, "Config not loaded")
    source = _resolve_serial_source(label or "")
    if source is None or not getattr(source, "connected", False):
        raise HTTPException(503, "Serial device not connected")
    return source


class SerialRegionUpdate(BaseModel):
    label: str = ""
    region: str


class SerialModemPresetUpdate(BaseModel):
    label: str = ""
    modem_preset: str


class SerialBroadcastIntervalsUpdate(BaseModel):
    label: str = ""
    node_info_broadcast_secs: Optional[int] = None
    telemetry_device_update_interval: Optional[int] = None


class SerialBluetoothUpdate(BaseModel):
    label: str = ""
    enabled: bool
    mode: Optional[str] = None
    fixed_pin: Optional[int] = None


@router.put("/region")
async def update_serial_region(
    req: SerialRegionUpdate,
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    source = _require_connected_source(req.label)
    result = source.set_region((req.region or "").strip())
    if not result.get("success"):
        raise HTTPException(400, result.get("error") or "Region update failed")
    return result


@router.put("/modem-preset")
async def update_serial_modem_preset(
    req: SerialModemPresetUpdate,
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    source = _require_connected_source(req.label)
    result = source.set_modem_preset((req.modem_preset or "").strip())
    if not result.get("success"):
        raise HTTPException(
            400, result.get("error") or "Modem preset update failed"
        )
    return result


@router.put("/broadcast-intervals")
async def update_serial_broadcast_intervals(
    req: SerialBroadcastIntervalsUpdate,
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    if (
        req.node_info_broadcast_secs is None
        and req.telemetry_device_update_interval is None
    ):
        raise HTTPException(
            400, "Provide node_info_broadcast_secs and/or "
            "telemetry_device_update_interval"
        )
    source = _require_connected_source(req.label)
    result = source.set_broadcast_intervals(
        node_info_secs=req.node_info_broadcast_secs,
        telemetry_secs=req.telemetry_device_update_interval,
    )
    if not result.get("success"):
        raise HTTPException(
            400, result.get("error") or "Broadcast interval update failed"
        )
    return result


@router.put("/bluetooth")
async def update_serial_bluetooth(
    req: SerialBluetoothUpdate,
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    source = _require_connected_source(req.label)
    result = source.set_bluetooth(
        enabled=req.enabled,
        mode=req.mode,
        fixed_pin=req.fixed_pin,
    )
    if not result.get("success"):
        raise HTTPException(
            400, result.get("error") or "Bluetooth update failed"
        )
    return result
