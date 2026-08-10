"""Live Meshtastic USB stick config writes over an open serial link.

Uses ``Node.writeConfig`` AdminMessage paths (region, modem preset,
broadcast intervals, Bluetooth). Credit: javastraat/meshpoint
``9bfbe56`` / ``9e06352`` / ``4a6055c``.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SerialDeviceConfigWriter:
    """Mutates one stick's localConfig / moduleConfig via writeConfig."""

    def __init__(
        self,
        interface: Any,
        radio_info: dict,
        log_name: str,
    ) -> None:
        self._interface = interface
        self._radio_info = radio_info
        self._log_name = log_name

    def set_region(self, region: str) -> dict:
        """Set LoRa region enum by name (e.g. ``EU_868``)."""
        try:
            from meshtastic.protobuf import config_pb2

            region_value = config_pb2.Config.LoRaConfig.RegionCode.Value(
                region
            )
        except ValueError:
            return {"success": False, "error": f"Unknown region: {region}"}

        try:
            node = self._interface.localNode
            node.localConfig.lora.region = region_value
            node.writeConfig("lora")
        except SystemExit:
            logger.error(
                "%s: writeConfig(lora) hit sys.exit", self._log_name
            )
            return {"success": False, "error": "Internal error setting region"}
        except Exception as exc:
            logger.exception("%s: set_region failed", self._log_name)
            return {"success": False, "error": str(exc)}

        self._radio_info["region"] = region
        logger.info("%s: region set to %s", self._log_name, region)
        return {"success": True, "region": region}

    def set_modem_preset(self, preset: str) -> dict:
        """Set named modem preset; always forces ``use_preset=True``."""
        try:
            from meshtastic.protobuf import config_pb2

            preset_value = config_pb2.Config.LoRaConfig.ModemPreset.Value(
                preset
            )
        except ValueError:
            return {
                "success": False,
                "error": f"Unknown modem preset: {preset}",
            }

        try:
            node = self._interface.localNode
            node.localConfig.lora.use_preset = True
            node.localConfig.lora.modem_preset = preset_value
            node.writeConfig("lora")
        except SystemExit:
            logger.error(
                "%s: writeConfig(lora) hit sys.exit", self._log_name
            )
            return {
                "success": False,
                "error": "Internal error setting modem preset",
            }
        except Exception as exc:
            logger.exception("%s: set_modem_preset failed", self._log_name)
            return {"success": False, "error": str(exc)}

        self._radio_info["modem_preset"] = preset
        self._radio_info["use_preset"] = True
        logger.info("%s: modem preset set to %s", self._log_name, preset)
        return {"success": True, "modem_preset": preset}

    def set_broadcast_intervals(
        self,
        node_info_secs: Optional[int] = None,
        telemetry_secs: Optional[int] = None,
    ) -> dict:
        """Set stick NodeInfo and/or device-telemetry broadcast cadence."""
        for label, value in (
            ("NodeInfo", node_info_secs),
            ("telemetry", telemetry_secs),
        ):
            if value is not None and not (0 <= value <= 86400):
                return {
                    "success": False,
                    "error": (
                        f"{label} interval must be between 0 and "
                        "86400 seconds"
                    ),
                }

        try:
            node = self._interface.localNode
            if node_info_secs is not None:
                node.localConfig.device.node_info_broadcast_secs = (
                    node_info_secs
                )
                node.writeConfig("device")
                self._radio_info["node_info_broadcast_secs"] = node_info_secs
            if telemetry_secs is not None:
                node.moduleConfig.telemetry.device_update_interval = (
                    telemetry_secs
                )
                node.writeConfig("telemetry")
                self._radio_info["telemetry_device_update_interval"] = (
                    telemetry_secs
                )
        except SystemExit:
            logger.error(
                "%s: writeConfig(device/telemetry) hit sys.exit",
                self._log_name,
            )
            return {
                "success": False,
                "error": "Internal error setting broadcast intervals",
            }
        except Exception as exc:
            logger.exception(
                "%s: set_broadcast_intervals failed", self._log_name
            )
            return {"success": False, "error": str(exc)}

        logger.info(
            "%s: broadcast intervals set (node_info_secs=%s "
            "telemetry_secs=%s)",
            self._log_name,
            node_info_secs,
            telemetry_secs,
        )
        return {
            "success": True,
            "node_info_broadcast_secs": node_info_secs,
            "telemetry_device_update_interval": telemetry_secs,
        }

    def set_bluetooth(
        self,
        enabled: bool,
        mode: Optional[str] = None,
        fixed_pin: Optional[int] = None,
    ) -> dict:
        """Enable/disable Bluetooth and optional pairing mode / PIN."""
        mode_value = None
        if mode is not None:
            try:
                from meshtastic.protobuf import config_pb2

                mode_value = (
                    config_pb2.Config.BluetoothConfig.PairingMode.Value(mode)
                )
            except ValueError:
                return {
                    "success": False,
                    "error": f"Unknown pairing mode: {mode}",
                }

        if fixed_pin is not None and not (0 <= fixed_pin <= 999999):
            return {
                "success": False,
                "error": "PIN must be a 6-digit number (0-999999)",
            }

        try:
            node = self._interface.localNode
            node.localConfig.bluetooth.enabled = enabled
            if mode_value is not None:
                node.localConfig.bluetooth.mode = mode_value
            if fixed_pin is not None:
                node.localConfig.bluetooth.fixed_pin = fixed_pin
            node.writeConfig("bluetooth")
        except SystemExit:
            logger.error(
                "%s: writeConfig(bluetooth) hit sys.exit", self._log_name
            )
            return {
                "success": False,
                "error": "Internal error setting Bluetooth config",
            }
        except Exception as exc:
            logger.exception("%s: set_bluetooth failed", self._log_name)
            return {"success": False, "error": str(exc)}

        self._radio_info["bluetooth_enabled"] = enabled
        if mode is not None:
            self._radio_info["bluetooth_mode"] = mode
        logger.info(
            "%s: bluetooth set (enabled=%s mode=%s)",
            self._log_name,
            enabled,
            mode,
        )
        return {
            "success": True,
            "enabled": enabled,
            "mode": mode,
            "fixed_pin": fixed_pin,
        }
