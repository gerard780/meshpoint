"""Tests for MeshCore set_radio apply + timeout recovery."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.transmit.meshcore_radio_apply import (
    MeshcoreRadioApply,
    MeshcoreRadioTimeoutRecovery,
)
from src.transmit.meshcore_tx_client import (
    MeshCoreTxClient,
    RadioStatus,
    SendResult,
)


class TestMeshcoreRadioApply(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_returns_timed_out(self):
        mc = MagicMock()
        mc.stop_auto_message_fetching = AsyncMock()

        async def hang(_freq, _bw, _sf, _cr):
            await asyncio.sleep(60)

        mc.commands.set_radio = hang

        with patch(
            "src.transmit.meshcore_radio_apply._SET_RADIO_TIMEOUT_SECONDS",
            0.05,
        ):
            result = await MeshcoreRadioApply().apply(mc, 910.525, 62.5, 7, 5)

        self.assertFalse(result.success)
        self.assertTrue(result.timed_out)
        mc.stop_auto_message_fetching.assert_awaited()

    async def test_no_event_received_is_timed_out_not_reject(self):
        """meshcore_py ERROR reason=no_event_received is a timeout, not reject."""
        from meshcore import EventType
        from meshcore.events import Event

        mc = MagicMock()
        mc.stop_auto_message_fetching = AsyncMock()
        mc.commands.set_radio = AsyncMock(
            return_value=Event(
                EventType.ERROR, {"reason": "no_event_received"}
            )
        )

        result = await MeshcoreRadioApply().apply(mc, 910.525, 62.5, 7, 5)

        self.assertFalse(result.success)
        self.assertTrue(result.timed_out)
        self.assertIn("no_event_received", result.error)
        mc.commands.reboot.assert_not_called()


class TestMeshcoreRadioTimeoutRecovery(unittest.IsolatedAsyncioTestCase):
    async def test_verify_success_when_params_match(self):
        info = RadioStatus(
            frequency_mhz=910.525,
            bandwidth_khz=62.5,
            spreading_factor=7,
            coding_rate=5,
        )
        result = await MeshcoreRadioTimeoutRecovery().verify(
            wait_connected=AsyncMock(return_value=True),
            get_radio_info=AsyncMock(return_value=info),
            freq=910.525,
            bw=62.5,
            sf=7,
            cr=5,
        )
        self.assertTrue(result.success)

    async def test_verify_fails_when_params_differ(self):
        info = RadioStatus(
            frequency_mhz=869.618,
            bandwidth_khz=62.5,
            spreading_factor=8,
            coding_rate=8,
        )
        result = await MeshcoreRadioTimeoutRecovery().verify(
            wait_connected=AsyncMock(return_value=True),
            get_radio_info=AsyncMock(return_value=info),
            freq=910.525,
            bw=62.5,
            sf=7,
            cr=5,
        )
        self.assertFalse(result.success)
        self.assertTrue(result.timed_out)
        self.assertIn("869.618", result.error)

    def test_params_match_tolerance(self):
        info = RadioStatus(
            frequency_mhz=910.525,
            bandwidth_khz=62.5,
            spreading_factor=7,
            coding_rate=5,
        )
        self.assertTrue(
            MeshcoreRadioTimeoutRecovery.params_match(
                info, 910.525, 62.5, 7, 5
            )
        )
        self.assertFalse(
            MeshcoreRadioTimeoutRecovery.params_match(
                info, 869.618, 62.5, 8, 8
            )
        )


class TestSetRadioParamsTimeoutRecovery(unittest.IsolatedAsyncioTestCase):
    async def test_bound_source_uses_exclusive_apply(self):
        from src.transmit.meshcore_exclusive_radio import (
            MeshcoreExclusiveRadioApply,
        )

        client = MeshCoreTxClient()
        source = MagicMock()
        source._connected = True
        source._meshcore = MagicMock()
        client.set_source(source)

        with patch.object(
            MeshcoreExclusiveRadioApply,
            "apply_via_source",
            new=AsyncMock(
                return_value=SendResult(success=True, event_type="set_radio")
            ),
        ) as apply:
            result = await client.set_radio_params(910.525, 62.5, 7, 5)

        self.assertTrue(result.success)
        apply.assert_awaited_once()

    async def test_mismatch_retries_once_on_live_link(self):
        from src.transmit.meshcore_radio_apply import MeshcoreRadioSetCoordinator

        apply = AsyncMock(
            side_effect=[
                SendResult(
                    success=False, error="set_radio timed out", timed_out=True
                ),
                SendResult(success=True, event_type="set_radio"),
            ]
        )
        trigger = MagicMock()
        mismatch = SendResult(
            success=False,
            error="still on 869.618",
            timed_out=True,
        )

        with patch.object(
            MeshcoreRadioTimeoutRecovery,
            "verify",
            new=AsyncMock(return_value=mismatch),
        ), patch(
            "src.transmit.meshcore_radio_apply.asyncio.sleep",
            new=AsyncMock(),
        ):
            result = await MeshcoreRadioSetCoordinator().run(
                apply=apply,
                trigger_reconnect=trigger,
                wait_connected=AsyncMock(return_value=True),
                get_radio_info=AsyncMock(return_value=None),
                freq=910.525,
                bw=62.5,
                sf=7,
                cr=5,
            )

        self.assertTrue(result.success)
        self.assertEqual(apply.await_count, 2)
        self.assertEqual(trigger.call_count, 2)
        self.assertIn("retry", trigger.call_args_list[-1][0][0])


if __name__ == "__main__":
    unittest.main()
