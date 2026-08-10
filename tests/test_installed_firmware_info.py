"""Tests for installed companion firmware version helpers."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.capture.serial_firmware_info import SerialFirmwareInfoReader
from src.transmit.meshcore_device_info import MeshcoreDeviceInfoQuery


class _FakeEventType:
    OK = "OK"
    ERROR = "ERROR"
    DEVICE_INFO = "DEVICE_INFO"


class TestMeshcoreDeviceInfoNormalize(unittest.TestCase):
    def test_normalize_maps_reader_keys(self):
        out = MeshcoreDeviceInfoQuery.normalize({
            "fw ver": 3,
            "ver": "v1.17.0",
            "model": "Heltec V3",
            "fw_build": "10 Aug 2026",
        })
        self.assertEqual(out["version"], "v1.17.0")
        self.assertEqual(out["model"], "Heltec V3")
        self.assertEqual(out["build"], "10 Aug 2026")
        self.assertEqual(out["fw_protocol"], 3)


class TestMeshcoreDeviceInfoQuery(unittest.IsolatedAsyncioTestCase):
    async def test_returns_none_when_disconnected(self):
        out = await MeshcoreDeviceInfoQuery().run(
            mc=MagicMock(),
            cmd_lock=AsyncMock(),
            connected=False,
        )
        self.assertIsNone(out)

    async def test_ok_path_returns_normalized(self):
        import asyncio

        lock = asyncio.Lock()
        mc = MagicMock()
        event = MagicMock()
        event.type = _FakeEventType.DEVICE_INFO
        event.payload = {
            "fw ver": 3,
            "ver": "v1.16.0",
            "model": "Heltec_v3",
            "fw_build": "01 Jan 2026",
        }
        mc.commands.send_device_query = AsyncMock(return_value=event)

        with patch.dict("sys.modules", {
            "meshcore": MagicMock(EventType=_FakeEventType),
        }):
            out = await MeshcoreDeviceInfoQuery().run(
                mc=mc, cmd_lock=lock, connected=True,
            )
        self.assertEqual(out["version"], "v1.16.0")
        self.assertEqual(out["model"], "Heltec_v3")


class TestSerialFirmwareInfoReader(unittest.TestCase):
    def test_reads_firmware_version_from_metadata(self):
        reader = SerialFirmwareInfoReader()
        iface = MagicMock()
        iface.metadata.firmware_version = "2.7.26.54e0d8d"
        iface.metadata.hw_model = "HELTEC_V3"
        iface.myInfo = None
        out = reader.read_from_interface(iface)
        self.assertEqual(out["version"], "2.7.26.54e0d8d")
        self.assertEqual(out["hw_model"], "HELTEC_V3")

    def test_falls_back_to_my_info(self):
        reader = SerialFirmwareInfoReader()
        iface = MagicMock(spec=["myInfo", "metadata"])
        iface.metadata = None
        iface.myInfo.firmware_version = "2.5.0"
        iface.myInfo.hw_model = "TBEAM"
        out = reader.read_from_interface(iface)
        self.assertEqual(out["version"], "2.5.0")
        self.assertEqual(out["hw_model"], "TBEAM")

    def test_short_port_name_prefers_tty(self):
        self.assertEqual(
            SerialFirmwareInfoReader.short_port_name("/dev/ttyACM0"),
            "ttyACM0",
        )
        self.assertEqual(
            SerialFirmwareInfoReader.short_port_name(
                "/dev/serial/by-path/platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.2:1.0"
            ),
            "USB",
        )

    def test_disconnected_source(self):
        reader = SerialFirmwareInfoReader()

        class _Source:
            connected = False
            name = "serial_Heltec"
            _port = "/dev/ttyACM0"

        out = reader.read_from_source(_Source())
        self.assertFalse(out["connected"])
        self.assertEqual(out["version"], "")
        self.assertEqual(out["port"], "/dev/ttyACM0")
        self.assertEqual(out["port_short"], "ttyACM0")


if __name__ == "__main__":
    unittest.main()
