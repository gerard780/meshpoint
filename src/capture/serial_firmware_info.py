"""Read firmware version from an open Meshtastic serial interface."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_TTY_RE = re.compile(r"(tty(?:USB|ACM|AMA)\d+)", re.IGNORECASE)


class SerialFirmwareInfoReader:
    """Best-effort firmware version from Meshtastic ``metadata`` / ``myInfo``."""

    def read_from_source(self, source) -> dict[str, Any]:
        """Return installed firmware fields for a ``SerialCaptureSource``."""
        connected = bool(getattr(source, "connected", False))
        port = (
            getattr(source, "_resolved_port", None)
            or getattr(source, "_port", None)
            or getattr(source, "serial_port", None)
            or ""
        )
        entry: dict[str, Any] = {
            "name": getattr(source, "name", "serial"),
            "connected": connected,
            "port": port or None,
            "port_short": self.short_port_name(port) if port else None,
            "version": "",
            "hw_model": None,
        }
        if not connected:
            return entry

        interface = getattr(source, "_interface", None)
        info = self.read_from_interface(interface)
        entry.update(info)
        return entry

    def read_from_interface(self, interface) -> dict[str, Any]:
        if interface is None:
            return {"version": "", "hw_model": None}
        try:
            # Modern Meshtastic puts version on DeviceMetadata, not MyNodeInfo.
            metadata = getattr(interface, "metadata", None)
            my_info = getattr(interface, "myInfo", None)
            version = (
                self._coerce_version(metadata)
                or self._coerce_version(my_info)
            )
            hw_model = (
                self._coerce_hw_model(metadata)
                or self._coerce_hw_model(my_info)
            )
            return {"version": version, "hw_model": hw_model}
        except Exception:
            logger.debug("Could not read Meshtastic firmware fields", exc_info=True)
            return {"version": "", "hw_model": None}

    @classmethod
    def short_port_name(cls, port: str) -> str:
        """Prefer ``ttyUSB0`` / ``ttyACM0`` over long by-path strings."""
        if not port:
            return ""
        base = Path(port).name
        if base.startswith("tty"):
            return base
        match = _TTY_RE.search(port)
        if match:
            return match.group(1)
        try:
            from src.hal.usb_classifier import list_serial_ports_with_stable_paths

            real = os.path.realpath(port)
            for dev in list_serial_ports_with_stable_paths():
                aliases = {
                    value
                    for value in (
                        dev.device,
                        dev.stable_path,
                        dev.by_id,
                        dev.by_path,
                    )
                    if value
                }
                if port in aliases or real in {
                    os.path.realpath(a) for a in aliases
                }:
                    return Path(dev.device).name
        except Exception:
            logger.debug("Could not resolve short serial port name", exc_info=True)
        if base.startswith("platform-") or "pci-" in base:
            return "USB"
        return base

    @staticmethod
    def _coerce_version(obj) -> str:
        if obj is None:
            return ""
        for attr in ("firmware_version", "firmwareVersion", "version"):
            value = getattr(obj, attr, None)
            if value:
                return str(value).strip()
        if isinstance(obj, dict):
            for key in ("firmware_version", "firmwareVersion", "version"):
                value = obj.get(key)
                if value:
                    return str(value).strip()
        return ""

    @staticmethod
    def _coerce_hw_model(obj) -> Optional[str]:
        if obj is None:
            return None
        value = getattr(obj, "hw_model", None)
        if value is None and isinstance(obj, dict):
            value = obj.get("hw_model")
        if value is None:
            return None
        return str(value).strip() or None
