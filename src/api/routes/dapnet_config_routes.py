"""Per-device commands for the DAPNET/POCSAG companion (extra/pocsag_companion).

Mounted under ``/api/config/dapnet/*``. Distinct from the bare
``PUT /api/config/dapnet`` in ``system_config_routes.py`` (that one
saves the blacklist/ignore capcode lists) -- this module is for
commands sent to a specific connected companion over its live serial
connection, same split as serial_config_routes.py/
meshcore_config_routes.py owning their protocols' per-device actions.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config/dapnet", tags=["config", "dapnet"])

_dapnet_sources: list = []


def init_routes(dapnet_sources=None) -> None:
    global _dapnet_sources
    _dapnet_sources = dapnet_sources or []


def _resolve_dapnet_source(label: str):
    """Find the configured POCSAG companion source matching this label.

    Mirrors serial_config_routes.py's ``_resolve_serial_source`` --
    same ``dapnet_<label>``/bare ``dapnet`` naming convention.
    """
    name = f"dapnet_{label}" if label else "dapnet"
    for src in _dapnet_sources:
        if src.name == name:
            return src
    return None


class DapnetCallsignUpdate(BaseModel):
    label: str = ""
    callsign: str


@router.put("/callsign")
async def update_dapnet_callsign(
    req: DapnetCallsignUpdate,
    _claims: SessionClaims = Depends(require_admin),
) -> dict:
    """Set one POCSAG companion's operator callsign over its live serial
    connection.

    Unlike Serial/MeshCore identity renames, there is nothing to
    persist on the Meshpoint side afterward -- the callsign lives
    entirely in the companion's own NVS (set via the same validation
    cascade its web dashboard's /api/callsign already uses), not in
    local.yaml. A successful reply updates the source's cached status
    immediately so the config page / topbar chip reflect it without
    waiting for another status query (which only happens once, at
    connect).
    """
    source = _resolve_dapnet_source(req.label)
    if source is None or not source.connected:
        raise HTTPException(503, "POCSAG companion not connected")

    result = await source.send_command(
        {"cmd": "set_callsign", "callsign": req.callsign},
        expect_type="set_callsign_result",
        timeout=5.0,
    )
    if result is None:
        raise HTTPException(503, "No reply from companion (timed out)")
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "Rejected by companion")

    saved_callsign = result.get("callsign", "")
    source.note_new_callsign(saved_callsign)
    return {"saved": True, "callsign": saved_callsign}
