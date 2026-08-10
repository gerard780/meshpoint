"""Tests for PUT /api/config/serial/* live write routes."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth.dependencies import require_admin, require_auth
from src.api.auth.jwt_session import ROLE_ADMIN, SessionClaims
from src.api.routes import serial_config_routes as routes


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[require_admin] = lambda: SessionClaims(
        "test-admin", ROLE_ADMIN, 1
    )
    app.dependency_overrides[require_auth] = lambda: SessionClaims(
        "test-admin", ROLE_ADMIN, 1
    )
    return app


def _reset() -> None:
    routes._config = None
    routes._serial_sources = []


class TestSerialConfigRoutes(unittest.TestCase):
    def setUp(self) -> None:
        _reset()
        self.app = _build_app()
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        _reset()

    def _wire(self, source) -> None:
        routes._config = MagicMock()
        source.name = "serial"
        routes._serial_sources = [source]

    def test_503_when_config_missing(self):
        res = self.client.put(
            "/api/config/serial/region",
            json={"region": "US"},
        )
        self.assertEqual(res.status_code, 503)

    def test_503_when_disconnected(self):
        source = MagicMock()
        source.connected = False
        source.set_region = MagicMock()
        self._wire(source)
        res = self.client.put(
            "/api/config/serial/region",
            json={"region": "US"},
        )
        self.assertEqual(res.status_code, 503)
        source.set_region.assert_not_called()

    def test_region_success(self):
        source = MagicMock()
        source.connected = True
        source.set_region = MagicMock(
            return_value={"success": True, "region": "EU_868"}
        )
        self._wire(source)
        res = self.client.put(
            "/api/config/serial/region",
            json={"region": "EU_868"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["region"], "EU_868")
        source.set_region.assert_called_once_with("EU_868")

    def test_modem_preset_400_on_device_error(self):
        source = MagicMock()
        source.connected = True
        source.set_modem_preset = MagicMock(
            return_value={"success": False, "error": "Unknown modem preset"}
        )
        self._wire(source)
        res = self.client.put(
            "/api/config/serial/modem-preset",
            json={"modem_preset": "NOPE"},
        )
        self.assertEqual(res.status_code, 400)

    def test_broadcast_intervals_requires_one_field(self):
        source = MagicMock()
        source.connected = True
        self._wire(source)
        res = self.client.put(
            "/api/config/serial/broadcast-intervals",
            json={},
        )
        self.assertEqual(res.status_code, 400)

    def test_bluetooth_success(self):
        source = MagicMock()
        source.connected = True
        source.set_bluetooth = MagicMock(
            return_value={
                "success": True,
                "enabled": False,
                "mode": "NO_PIN",
                "fixed_pin": None,
            }
        )
        self._wire(source)
        res = self.client.put(
            "/api/config/serial/bluetooth",
            json={"enabled": False, "mode": "NO_PIN"},
        )
        self.assertEqual(res.status_code, 200)
        source.set_bluetooth.assert_called_once()

    def test_label_resolves_named_source(self):
        bare = MagicMock()
        bare.name = "serial"
        bare.connected = True
        labeled = MagicMock()
        labeled.name = "serial_433"
        labeled.connected = True
        labeled.set_region = MagicMock(
            return_value={"success": True, "region": "US"}
        )
        routes._config = MagicMock()
        routes._serial_sources = [bare, labeled]
        res = self.client.put(
            "/api/config/serial/region",
            json={"label": "433", "region": "US"},
        )
        self.assertEqual(res.status_code, 200)
        labeled.set_region.assert_called_once_with("US")
        bare.set_region.assert_not_called()


if __name__ == "__main__":
    unittest.main()
