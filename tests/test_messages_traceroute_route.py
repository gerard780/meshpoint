"""Tests for the dashboard Meshtastic traceroute endpoint."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException

from src.api.auth.dependencies import require_admin
from src.api.routes import messages as messages_module
from src.transmit.tx_service import SendResult


class TestSendTracerouteEndpoint(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        messages_module._tx_service = None

    def tearDown(self) -> None:
        messages_module._tx_service = None

    async def test_503_when_transmit_service_missing(self):
        with self.assertRaises(HTTPException) as ctx:
            await messages_module.send_traceroute(
                messages_module.TracerouteRequest(destination="11223344")
            )
        self.assertEqual(ctx.exception.status_code, 503)

    async def test_success_calls_tx_service_and_returns_packet_id(self):
        tx = MagicMock()
        tx.send_traceroute = AsyncMock(return_value=SendResult(
            success=True,
            packet_id="01020304",
            protocol="meshtastic",
            timestamp=123.0,
            airtime_ms=87,
        ))
        messages_module._tx_service = tx

        result = await messages_module.send_traceroute(
            messages_module.TracerouteRequest(
                destination="!11223344",
                channel=2,
            )
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["packet_id"], "01020304")
        tx.send_traceroute.assert_awaited_once_with(
            destination="!11223344",
            channel=2,
        )

    async def test_tx_failure_is_returned_to_dashboard(self):
        tx = MagicMock()
        tx.send_traceroute = AsyncMock(return_value=SendResult(
            success=False,
            protocol="meshtastic",
            error="Duty cycle limit reached",
        ))
        messages_module._tx_service = tx

        result = await messages_module.send_traceroute(
            messages_module.TracerouteRequest(destination="11223344")
        )

        self.assertFalse(result["success"])
        self.assertIn("Duty cycle", result["error"])

    async def test_rejects_invalid_channel(self):
        messages_module._tx_service = MagicMock()
        with self.assertRaises(HTTPException) as ctx:
            await messages_module.send_traceroute(
                messages_module.TracerouteRequest(
                    destination="11223344",
                    channel=8,
                )
            )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_route_requires_admin_dependency(self):
        route = next(
            route for route in messages_module.router.routes
            if route.path == "/api/messages/traceroute"
        )
        dependencies = [dep.call for dep in route.dependant.dependencies]
        self.assertIn(require_admin, dependencies)


if __name__ == "__main__":
    unittest.main()
