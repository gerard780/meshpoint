"""Tests for PUT /api/config/meshcore/companion-radio.

Credit: javastraat/meshpoint 471d572 (adapted to TxClient architecture)
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
    app.dependency_overrides[require_admin] = lambda: SessionClaims(
        "test-admin", ROLE_ADMIN, 1
    )
    app.dependency_overrides[require_auth] = lambda: SessionClaims(
        "test-admin", ROLE_ADMIN, 1
    )
    return app


def _reset_module_state() -> None:
    mc_routes._config = None
    mc_routes._tx_service = None


class TestCompanionRadioEndpoint(unittest.TestCase):
    def setUp(self) -> None:
        _reset_module_state()
        self.app = _build_app()
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        _reset_module_state()

    def _wire_tx(self, mc_tx) -> None:
        mc_routes._config = MagicMock()
        tx = MagicMock()
        tx._meshcore_tx = mc_tx
        mc_routes._tx_service = tx

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

    def test_503_when_companion_disconnected(self):
        mc_tx = MagicMock()
        mc_tx.connected = False
        mc_tx.set_radio_params = AsyncMock()
        self._wire_tx(mc_tx)
        res = self.client.put(
            "/api/config/meshcore/companion-radio",
            json={"preset": "EU_433_NARROW"},
        )
        self.assertEqual(res.status_code, 503)
        mc_tx.set_radio_params.assert_not_called()

    def test_success_resolves_preset_and_calls_set_radio_params(self):
        mc_tx = MagicMock()
        mc_tx.connected = True
        mc_tx.set_radio_params = AsyncMock(
            return_value=_RadioResult(success=True)
        )
        self._wire_tx(mc_tx)

        res = self.client.put(
            "/api/config/meshcore/companion-radio",
            json={"preset": "EU_433_NARROW"},
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["saved"])
        self.assertEqual(body["preset"], "EU_433_NARROW")
        preset = REGION_PRESETS["EU_433_NARROW"]
        mc_tx.set_radio_params.assert_awaited_once_with(
            preset.frequency_mhz,
            preset.bandwidth_khz,
            preset.spreading_factor,
            preset.coding_rate,
        )

    def test_400_when_set_radio_fails(self):
        mc_tx = MagicMock()
        mc_tx.connected = True
        mc_tx.set_radio_params = AsyncMock(
            return_value=_RadioResult(success=False, error="bad params")
        )
        self._wire_tx(mc_tx)
        res = self.client.put(
            "/api/config/meshcore/companion-radio",
            json={"preset": "USA_CANADA"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("bad params", res.json()["detail"])


if __name__ == "__main__":
    unittest.main()
