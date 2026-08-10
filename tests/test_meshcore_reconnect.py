"""MeshCore USB reconnect on command timeout (javastraat port).

Credit: javastraat/meshpoint b04e91c / c1bc3b8
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.transmit.meshcore_tx_client import MeshCoreTxClient, SendResult


class TestReconnectReentrancyGuard(unittest.IsolatedAsyncioTestCase):
    """_reconnect_in_progress serializes health vs timeout reconnects."""

    async def test_reconnect_no_ops_while_already_in_progress(self):
        from src.capture.meshcore_usb_source import MeshcoreUsbCaptureSource

        source = MeshcoreUsbCaptureSource(
            serial_port="/dev/ttyFAKE", auto_detect=False
        )
        source._reconnect_in_progress = True
        source._disconnect = AsyncMock()  # type: ignore[method-assign]

        await source._reconnect()

        source._disconnect.assert_not_called()

    async def test_flag_is_set_during_and_cleared_after_a_real_run(self):
        from src.capture.meshcore_usb_source import MeshcoreUsbCaptureSource

        source = MeshcoreUsbCaptureSource(
            serial_port="/dev/ttyFAKE", auto_detect=False
        )
        source._running = True
        source._resolved_port = "/dev/ttyFAKE"
        flag_during_connect = None

        async def fake_disconnect():
            return None

        async def fake_connect(port):
            nonlocal flag_during_connect
            flag_during_connect = source._reconnect_in_progress
            source._connected = True

        source._disconnect = fake_disconnect  # type: ignore[method-assign]
        source._connect = fake_connect  # type: ignore[assignment]

        self.assertFalse(source._reconnect_in_progress)
        with patch(
            "src.capture.meshcore_usb_source.asyncio.sleep", AsyncMock()
        ):
            await source._reconnect()

        self.assertTrue(flag_during_connect)
        self.assertFalse(source._reconnect_in_progress)

    async def test_flag_clears_even_if_reconnect_raises(self):
        from src.capture.meshcore_usb_source import MeshcoreUsbCaptureSource

        source = MeshcoreUsbCaptureSource(
            serial_port="/dev/ttyFAKE", auto_detect=False
        )

        async def raise_disconnect():
            raise RuntimeError("boom")

        source._disconnect = raise_disconnect  # type: ignore[method-assign]

        with self.assertRaises(RuntimeError):
            await source._reconnect()

        self.assertFalse(source._reconnect_in_progress)

    async def test_trigger_reconnect_skips_when_already_in_progress(self):
        from src.capture.meshcore_usb_source import MeshcoreUsbCaptureSource

        source = MeshcoreUsbCaptureSource(
            serial_port="/dev/ttyFAKE", auto_detect=False
        )
        source._connected = True
        source._reconnect_in_progress = True

        async def fake_health_loop():
            await asyncio.sleep(60)

        source._health_task = asyncio.create_task(fake_health_loop())

        try:
            source._trigger_reconnect("some command timed out")
            self.assertIsNotNone(source._health_task)
            self.assertFalse(source._health_task.done())
            self.assertIsNone(source._reconnect_task)
            self.assertTrue(source._connected)
        finally:
            source._health_task.cancel()
            try:
                await source._health_task
            except asyncio.CancelledError:
                pass


class TestTxClientTimeoutTriggersReconnect(unittest.IsolatedAsyncioTestCase):
    """TxClient command timeouts kick the bound USB source."""

    async def test_set_name_timeout_sets_timed_out_and_triggers(self):
        client = MeshCoreTxClient()
        source = MagicMock()
        source._connected = True
        source._meshcore = MagicMock()
        source._meshcore.commands.set_name = AsyncMock()
        source._meshcore.self_info = {"name": "old-name"}
        source._trigger_reconnect = MagicMock()
        client.set_source(source)

        meshcore_mod = MagicMock()
        meshcore_mod.EventType = MagicMock()

        async def raise_timeout(coro, *_args, **_kwargs):
            if hasattr(coro, "close"):
                coro.close()
            raise asyncio.TimeoutError()

        with patch.dict("sys.modules", {"meshcore": meshcore_mod}):
            with patch(
                "src.transmit.meshcore_tx_client.asyncio.wait_for",
                side_effect=raise_timeout,
            ):
                result = await client.set_companion_name("Mesh Lab East")

        self.assertFalse(result.success)
        self.assertTrue(result.timed_out)
        source._trigger_reconnect.assert_called_once_with("set_name timed out")
        self.assertEqual(source._meshcore.self_info["name"], "old-name")

    async def test_channel_send_timeout_triggers(self):
        client = MeshCoreTxClient()
        source = MagicMock()
        source._connected = True
        source._meshcore = MagicMock()
        source._meshcore.commands.send_chan_msg = AsyncMock()
        source._trigger_reconnect = MagicMock()
        client.set_source(source)

        async def raise_timeout(coro, *_args, **_kwargs):
            if hasattr(coro, "close"):
                coro.close()
            raise asyncio.TimeoutError()

        with patch(
            "src.transmit.meshcore_tx_client.asyncio.wait_for",
            side_effect=raise_timeout,
        ):
            result = await client.send_channel_message(0, "hi")

        self.assertTrue(result.timed_out)
        source._trigger_reconnect.assert_called_once_with("Send timed out")

    async def test_firmware_error_does_not_set_timed_out(self):
        result = SendResult(success=False, error="rejected", timed_out=False)
        self.assertFalse(result.timed_out)

    async def test_set_radio_success_triggers_reconnect(self):
        from src.transmit.meshcore_radio_apply import MeshcoreRadioApply

        client = MeshCoreTxClient()
        source = MagicMock()
        source._connected = True
        source._meshcore = MagicMock()
        source._trigger_reconnect = MagicMock()
        client.set_source(source)

        with patch.object(
            MeshcoreRadioApply,
            "apply",
            new=AsyncMock(
                return_value=SendResult(success=True, event_type="set_radio")
            ),
        ):
            result = await client.set_radio_params(910.525, 62.5, 7, 5)

        self.assertTrue(result.success)
        source._trigger_reconnect.assert_called_once()
        self.assertIn("rebooting", source._trigger_reconnect.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
