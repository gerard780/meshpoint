"""Unit tests for SerialDeviceConfigWriter live config writes."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class TestSerialDeviceConfigWriter(unittest.TestCase):
    def setUp(self) -> None:
        from src.capture.serial_device_config import SerialDeviceConfigWriter

        self.iface = MagicMock()
        self.node = MagicMock()
        self.iface.localNode = self.node
        self.info: dict = {}
        self.writer = SerialDeviceConfigWriter(self.iface, self.info, "serial")

    def test_set_region_updates_cache(self):
        mock_pb2 = MagicMock()
        mock_pb2.Config.LoRaConfig.RegionCode.Value.return_value = 1
        with patch.dict(
            "sys.modules",
            {
                "meshtastic": MagicMock(),
                "meshtastic.protobuf": MagicMock(),
                "meshtastic.protobuf.config_pb2": mock_pb2,
            },
        ):
            from src.capture.serial_device_config import SerialDeviceConfigWriter

            writer = SerialDeviceConfigWriter(self.iface, self.info, "serial")
            result = writer.set_region("US")
        self.assertTrue(result["success"])
        self.assertEqual(self.info["region"], "US")
        self.node.writeConfig.assert_called_with("lora")

    def test_set_region_unknown(self):
        with patch(
            "meshtastic.protobuf.config_pb2.Config.LoRaConfig.RegionCode.Value",
            side_effect=ValueError("bad"),
        ):
            result = self.writer.set_region("NOT_REAL")
        self.assertFalse(result["success"])
        self.node.writeConfig.assert_not_called()

    def test_set_modem_preset(self):
        mock_pb2 = MagicMock()
        mock_pb2.Config.LoRaConfig.ModemPreset.Value.return_value = 0
        with patch.dict(
            "sys.modules",
            {
                "meshtastic": MagicMock(),
                "meshtastic.protobuf": MagicMock(),
                "meshtastic.protobuf.config_pb2": mock_pb2,
            },
        ):
            from src.capture.serial_device_config import SerialDeviceConfigWriter

            writer = SerialDeviceConfigWriter(self.iface, self.info, "serial")
            result = writer.set_modem_preset("LONG_FAST")
        self.assertTrue(result["success"])
        self.assertEqual(self.info["modem_preset"], "LONG_FAST")
        self.assertTrue(self.info["use_preset"])

    def test_set_broadcast_intervals(self):
        result = self.writer.set_broadcast_intervals(
            node_info_secs=300, telemetry_secs=600
        )
        self.assertTrue(result["success"])
        self.assertEqual(self.info["node_info_broadcast_secs"], 300)
        self.assertEqual(self.info["telemetry_device_update_interval"], 600)
        calls = [c.args[0] for c in self.node.writeConfig.call_args_list]
        self.assertEqual(calls, ["device", "telemetry"])

    def test_set_broadcast_intervals_out_of_range(self):
        result = self.writer.set_broadcast_intervals(node_info_secs=999999)
        self.assertFalse(result["success"])

    def test_set_bluetooth(self):
        mock_pb2 = MagicMock()
        mock_pb2.Config.BluetoothConfig.PairingMode.Value.return_value = 1
        with patch.dict(
            "sys.modules",
            {
                "meshtastic": MagicMock(),
                "meshtastic.protobuf": MagicMock(),
                "meshtastic.protobuf.config_pb2": mock_pb2,
            },
        ):
            from src.capture.serial_device_config import SerialDeviceConfigWriter

            writer = SerialDeviceConfigWriter(self.iface, self.info, "serial")
            result = writer.set_bluetooth(
                enabled=True, mode="FIXED_PIN", fixed_pin=123456
            )
        self.assertTrue(result["success"])
        self.assertTrue(self.info["bluetooth_enabled"])
        self.assertEqual(self.info["bluetooth_mode"], "FIXED_PIN")
        self.node.writeConfig.assert_called_with("bluetooth")


if __name__ == "__main__":
    unittest.main()
