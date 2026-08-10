"""Reticulum companion settings for Configuration -> Reticulum.

Covers the ``reticulum:`` block fields a user actually tunes by hand --
enabled/display_name plus the RNode interface and TCP backbone fields
that :mod:`scripts.write_rnsd_config` turns into rnsd's own config file.
``reticulum_config_dir``/``identity_path``/``lxmf_storage_dir`` are
internal storage paths, not exposed here.

Unlike most Configuration cards, a save here does not take effect just
by restarting meshpoint: the RNode/backbone fields are only ever read
by ``write_rnsd_config.py``, which only runs as rnsd's own
``ExecStartPre`` (see ``scripts/rnsd.service``) -- so applying those
needs an rnsd restart too, not just meshpoint's. ``restart_rnsd()``
below gives the card a direct way to trigger that, reusing the same
narrowly-scoped ``sudo systemctl ... rnsd`` helper the RNode firmware
flasher already uses.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from src.api.audit import AuditLogWriter
from src.api.audit.dependencies import get_audit_writer
from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims
from src.api.routes.rnode_firmware_routes import _run_systemctl
from src.config import AppConfig, save_section_to_yaml

router = APIRouter(prefix="/api/config", tags=["config"])

_config: AppConfig | None = None

# SX127x/SX126x (every RNode board) only accept these LoRa bandwidths --
# anything else silently fails to key up, so reject early rather than
# let a typo reach rnsd only to be discovered on the next restart.
_VALID_BANDWIDTHS_HZ = frozenset(
    {7800, 10400, 15600, 20800, 31250, 41700, 62500, 125000, 250000, 500000}
)


def init_routes(config: AppConfig) -> None:
    global _config
    _config = config


def reset_routes() -> None:
    global _config
    _config = None


class ReticulumUpdate(BaseModel):
    enabled: bool = False
    display_name: str = "Meshpoint"
    rnode_serial_port: str = ""
    rnode_frequency_hz: int = Field(..., ge=100_000_000, le=1_000_000_000)
    rnode_bandwidth_hz: int = 125_000
    rnode_tx_power: int = Field(20, ge=0, le=22)
    rnode_spreading_factor: int = Field(8, ge=5, le=12)
    rnode_coding_rate: int = Field(5, ge=5, le=8)
    backbone_host: str = "node.reticulumnet.nl"
    backbone_port: int = Field(4242, ge=1, le=65535)

    @field_validator("rnode_bandwidth_hz")
    @classmethod
    def _check_bandwidth(cls, value: int) -> int:
        if value not in _VALID_BANDWIDTHS_HZ:
            allowed = ", ".join(str(v) for v in sorted(_VALID_BANDWIDTHS_HZ))
            raise ValueError(f"rnode_bandwidth_hz must be one of: {allowed}")
        return value

    @field_validator("display_name", "backbone_host")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty")
        return stripped


@router.put("/reticulum")
async def update_reticulum(
    req: ReticulumUpdate,
    claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
):
    """Persist Reticulum/RNode/backbone settings. Requires restarting
    meshpoint AND rnsd (see this module's own docstring) to apply."""
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    rc = _config.reticulum
    updates = {
        "enabled": req.enabled,
        "display_name": req.display_name,
        "rnode_serial_port": req.rnode_serial_port.strip(),
        "rnode_frequency_hz": req.rnode_frequency_hz,
        "rnode_bandwidth_hz": req.rnode_bandwidth_hz,
        "rnode_tx_power": req.rnode_tx_power,
        "rnode_spreading_factor": req.rnode_spreading_factor,
        "rnode_coding_rate": req.rnode_coding_rate,
        "backbone_host": req.backbone_host,
        "backbone_port": req.backbone_port,
    }

    with audit.timed_action(
        user=claims.subject,
        action="config.reticulum_update",
        params={k: v for k, v in updates.items() if k != "rnode_serial_port"},
    ):
        rc.enabled = updates["enabled"]
        rc.display_name = updates["display_name"]
        rc.rnode_serial_port = updates["rnode_serial_port"]
        rc.rnode_frequency_hz = updates["rnode_frequency_hz"]
        rc.rnode_bandwidth_hz = updates["rnode_bandwidth_hz"]
        rc.rnode_tx_power = updates["rnode_tx_power"]
        rc.rnode_spreading_factor = updates["rnode_spreading_factor"]
        rc.rnode_coding_rate = updates["rnode_coding_rate"]
        rc.backbone_host = updates["backbone_host"]
        rc.backbone_port = updates["backbone_port"]

        try:
            save_section_to_yaml("reticulum", updates)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    return {"saved": True, "restart_required": True}


@router.post("/reticulum/restart-rnsd")
async def restart_rnsd(_claims: SessionClaims = Depends(require_admin)):
    """Restarts the opt-in ``rnsd`` systemd unit so it re-runs
    ``write_rnsd_config.py`` and reconnects with whatever RNode/backbone
    settings were just saved above. No-ops with a clear error if rnsd
    isn't installed as a service at all (opt-in, see scripts/rnsd.service)."""
    rc, out = await _run_systemctl("restart", "rnsd")
    if rc != 0:
        raise HTTPException(
            502,
            f"systemctl restart rnsd failed (exit {rc}): {out or 'no output'}",
        )
    return {"success": True, "output": out}
