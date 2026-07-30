"""Tests for PUT /api/config/meshcore/companion-radio.

Same harness as test_meshcore_companion_name_route.py -- validates the
route's contract (503/400/200 cases) via a fake companion source; the
actual set_radio()+reboot() sequence lives in
send_set_radio_params()/MeshcoreUsbCaptureSource.set_radio_params() and
is covered separately.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth.dependencies import require_admin, require_auth
from src.api.auth.jwt_session import ROLE_ADMIN, SessionClaims
from src.api.routes import meshcore_config_routes as mc_routes
from src.cli.meshcore_radio_config import REGION_PRESETS


class _RadioResult:
    def __init__(self, success: bool, error: str | None = None):
        self.success = success
        self.error = error


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(mc_routes.router)
    app.dependency_overrides[require_admin] = lambda: SessionClaims("test-admin", ROLE_ADMIN, 1)
    app.dependency_overrides[require_auth] = lambda: SessionClaims("test-admin", ROLE_ADMIN, 1)
    return app


def _reset_module_state() -> None:
    mc_routes._config = None
    mc_routes._tx_service = None
    mc_routes._meshcore_sources = []


class TestCompanionRadioEndpoint(unittest.TestCase):
    def setUp(self) -> None:
        _reset_module_state()
        self.app = _build_app()
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        _reset_module_state()

    def _wire(self, source) -> None:
        mc_routes._config = MagicMock()
        source.name = "meshcore_usb"
        mc_routes._meshcore_sources = [source]

    def test_503_when_config_not_loaded(self):
        res = self.client.put(
            "/api/config/meshcore/companion-radio",
            json={"preset": "EU_433_NARROW"},
        )
        self.assertEqual(res.status_code, 503)

    def test_400_for_unknown_preset(self):
        mc_routes._config = MagicMock()
        res = self.client.put(
            "/api/config/meshcore/companion-radio",
            json={"preset": "NOT_A_REAL_PRESET"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("unknown preset", res.json()["detail"].lower())

    def test_503_when_companion_not_resolved(self):
        mc_routes._config = MagicMock()
        mc_routes._meshcore_sources = []
        res = self.client.put(
            "/api/config/meshcore/companion-radio",
            json={"preset": "EU_433_NARROW"},
        )
        self.assertEqual(res.status_code, 503)

    def test_503_when_companion_disconnected(self):
        source = MagicMock()
        source.connected = False
        source.set_radio_params = AsyncMock()
        self._wire(source)
        res = self.client.put(
            "/api/config/meshcore/companion-radio",
            json={"preset": "EU_433_NARROW"},
        )
        self.assertEqual(res.status_code, 503)
        source.set_radio_params.assert_not_called()

    def test_success_resolves_preset_and_calls_set_radio_params(self):
        source = MagicMock()
        source.connected = True
        source.set_radio_params = AsyncMock(return_value=_RadioResult(success=True))
        self._wire(source)

        res = self.client.put(
            "/api/config/meshcore/companion-radio",
            json={"preset": "EU_433_NARROW"},
        )

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["saved"])
        self.assertEqual(body["preset"], "EU_433_NARROW")
        self.assertTrue(body["rebooting"])

        preset = REGION_PRESETS["EU_433_NARROW"]
        source.set_radio_params.assert_awaited_once_with(
            preset.frequency_mhz, preset.bandwidth_khz,
            preset.spreading_factor, preset.coding_rate,
        )

    def test_preset_key_resolves_case_insensitively(self):
        source = MagicMock()
        source.connected = True
        source.set_radio_params = AsyncMock(return_value=_RadioResult(success=True))
        self._wire(source)

        res = self.client.put(
            "/api/config/meshcore/companion-radio",
            json={"preset": "eu_433_narrow"},
        )
        self.assertEqual(res.status_code, 200)

    def test_400_when_companion_rejects(self):
        source = MagicMock()
        source.connected = True
        source.set_radio_params = AsyncMock(
            return_value=_RadioResult(success=False, error="Companion rejected radio params")
        )
        self._wire(source)

        res = self.client.put(
            "/api/config/meshcore/companion-radio",
            json={"preset": "EU_433_NARROW"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("rejected", res.json()["detail"].lower())

    def test_422_when_body_missing_preset(self):
        source = MagicMock()
        source.connected = True
        source.set_radio_params = AsyncMock()
        self._wire(source)

        res = self.client.put(
            "/api/config/meshcore/companion-radio",
            json={},
        )
        self.assertEqual(res.status_code, 422)
        source.set_radio_params.assert_not_called()

    def test_label_scopes_to_the_matching_companion(self):
        primary = MagicMock()
        primary.name = "meshcore_usb"
        primary.connected = True
        primary.set_radio_params = AsyncMock(return_value=_RadioResult(success=True))

        secondary = MagicMock()
        secondary.name = "meshcore_usb_433"
        secondary.connected = True
        secondary.set_radio_params = AsyncMock(return_value=_RadioResult(success=True))

        mc_routes._config = MagicMock()
        mc_routes._meshcore_sources = [primary, secondary]

        res = self.client.put(
            "/api/config/meshcore/companion-radio",
            json={"preset": "EU_433_NARROW", "label": "433"},
        )
        self.assertEqual(res.status_code, 200)
        secondary.set_radio_params.assert_awaited_once()
        primary.set_radio_params.assert_not_called()


if __name__ == "__main__":
    unittest.main()
