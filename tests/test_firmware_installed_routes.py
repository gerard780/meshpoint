"""GET .../firmware/installed for both Meshtastic and MeshCore -- surfaces
each configured device's already-known firmware version so an operator can
see what they're upgrading FROM on the Configuration -> Firmware cards,
without a new live query on the MeshCore side (get_device_info() already
caches) or any live query at all on the Meshtastic side (firmware_version/
hw_model are already read into _radio_info at connect time).

Needs FastAPI to import the route modules (only syntax-checked on this Mac,
per this repo's standing no-venv-here convention) -- run for real via:
    /opt/meshpoint/venv/bin/python -m unittest tests.test_firmware_installed_routes -v
"""

from __future__ import annotations

import asyncio
import unittest

from src.api.routes import meshcore_firmware_routes, meshtastic_firmware_routes
from src.transmit.meshcore_tx_client import DeviceInfo


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _FakeSerialSource:
    def __init__(self, name, connected, port, firmware_version="", hw_model=None):
        self.name = name
        self.connected = connected
        self._port = port
        self._radio_info = {"firmware_version": firmware_version, "hw_model": hw_model}

    def get_radio_info(self):
        return dict(self._radio_info)


class _FakeMeshcoreSource:
    def __init__(self, name, connected, port, device_info=None):
        self.name = name
        self.connected = connected
        self._resolved_port = port
        self._device_info = device_info

    async def get_device_info(self):
        return self._device_info


class TestMeshtasticInstalled(unittest.TestCase):
    def setUp(self):
        self._orig = meshtastic_firmware_routes._serial_sources

    def tearDown(self):
        meshtastic_firmware_routes._serial_sources = self._orig

    def test_connected_source_reports_its_own_cached_firmware(self):
        meshtastic_firmware_routes._serial_sources = [
            _FakeSerialSource("serial", True, "/dev/ttyUSB0", "2.5.1", 43),
        ]
        result = _run(meshtastic_firmware_routes.firmware_installed())
        self.assertEqual(result["devices"], [{
            "name": "serial", "connected": True, "port": "/dev/ttyUSB0",
            "version": "2.5.1", "hw_model": 43,
        }])

    def test_disconnected_source_reports_no_version_without_touching_radio_info(self):
        source = _FakeSerialSource("serial", False, "/dev/ttyUSB0", "2.5.1", 43)
        meshtastic_firmware_routes._serial_sources = [source]
        result = _run(meshtastic_firmware_routes.firmware_installed())
        self.assertEqual(result["devices"][0]["version"], "")
        self.assertFalse(result["devices"][0]["connected"])

    def test_no_configured_sources_returns_empty_list(self):
        meshtastic_firmware_routes._serial_sources = []
        result = _run(meshtastic_firmware_routes.firmware_installed())
        self.assertEqual(result["devices"], [])


class TestMeshcoreInstalled(unittest.TestCase):
    def setUp(self):
        self._orig = meshcore_firmware_routes._meshcore_sources

    def tearDown(self):
        meshcore_firmware_routes._meshcore_sources = self._orig

    def test_connected_source_reports_cached_device_info(self):
        info = DeviceInfo(firmware_version="v1.16.0", model="Heltec V3", build_date="2026-07-01")
        meshcore_firmware_routes._meshcore_sources = [
            _FakeMeshcoreSource("meshcore_usb", True, "/dev/ttyACM0", info),
        ]
        result = _run(meshcore_firmware_routes.firmware_installed())
        self.assertEqual(result["devices"], [{
            "name": "meshcore_usb", "connected": True, "port": "/dev/ttyACM0",
            "version": "v1.16.0", "model": "Heltec V3", "build": "2026-07-01",
        }])

    def test_disconnected_source_never_awaits_get_device_info(self):
        source = _FakeMeshcoreSource("meshcore_usb", False, "/dev/ttyACM0", None)
        called = False

        async def fail_if_called():
            nonlocal called
            called = True
            return None

        source.get_device_info = fail_if_called
        meshcore_firmware_routes._meshcore_sources = [source]
        result = _run(meshcore_firmware_routes.firmware_installed())
        self.assertFalse(called)
        self.assertEqual(result["devices"][0]["version"], "")

    def test_connected_but_no_device_info_yet_reports_empty_not_a_crash(self):
        meshcore_firmware_routes._meshcore_sources = [
            _FakeMeshcoreSource("meshcore_usb", True, "/dev/ttyACM0", None),
        ]
        result = _run(meshcore_firmware_routes.firmware_installed())
        self.assertEqual(result["devices"][0]["version"], "")
        self.assertTrue(result["devices"][0]["connected"])


if __name__ == "__main__":
    unittest.main()
