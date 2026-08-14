"""set_radio_params()'s timeout-recovery path: a clean success returns
immediately (no verify wait), but a timeout -- which is what a
cross-band change's silent reboot actually looks like -- waits for
reconnect, verifies the params actually stuck, and retries once live if
they didn't."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from src.capture import meshcore_usb_source as mus
from src.capture.meshcore_usb_source import MeshcoreUsbCaptureSource
from src.transmit.meshcore_tx_client import RadioStatus, SendResult


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(coro)
        # Let the fake _trigger_reconnect's own short-lived background
        # task (see _reconnect_after below) finish before the loop
        # closes -- otherwise it gets torn down mid-sleep, which is
        # harmless but prints a noisy "Task was destroyed" warning.
        pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        return result
    finally:
        loop.close()


def _make_source() -> MeshcoreUsbCaptureSource:
    source = MeshcoreUsbCaptureSource(serial_port="/dev/fake")
    source._connected = True
    source._meshcore = object()  # just needs to be non-None
    return source


def _reconnect_after(source, delay=0.01):
    """Fake `_trigger_reconnect` that flips `connected` back on shortly
    after, same shape a real successful `_reconnect()` would from
    `set_radio_params()`'s point of view."""

    def fake_trigger_reconnect(reason):
        source._connected = False

        async def _come_back():
            await asyncio.sleep(delay)
            source._connected = True

        asyncio.get_event_loop().create_task(_come_back())

    return fake_trigger_reconnect


class TestSetRadioParamsCleanSuccess(unittest.TestCase):
    def test_clean_success_returns_immediately_without_verifying(self):
        """The common case: no verify wait at all, matching config_routes.py's
        existing 'rebooting: true, don't expect an instant refresh' contract."""
        source = _make_source()
        get_radio_info_calls = 0

        async def fake_send_set_radio_params(mc, freq, bw, sf, cr):
            return SendResult(success=True)

        async def fake_get_radio_info():
            nonlocal get_radio_info_calls
            get_radio_info_calls += 1
            return None

        source._trigger_reconnect = _reconnect_after(source)
        source.get_radio_info = fake_get_radio_info

        with patch.object(mus, "send_set_radio_params", fake_send_set_radio_params):
            result = _run(source.set_radio_params(868.1, 250.0, 11, 5))

        self.assertTrue(result.success)
        self.assertEqual(get_radio_info_calls, 0, "a clean success must not trigger any verify read-back")

    def test_clean_rejection_returns_immediately(self):
        source = _make_source()

        async def fake_send_set_radio_params(mc, freq, bw, sf, cr):
            return SendResult(success=False, error="Frequency out of range")

        with patch.object(mus, "send_set_radio_params", fake_send_set_radio_params):
            result = _run(source.set_radio_params(9999.0, 250.0, 11, 5))

        self.assertFalse(result.success)
        self.assertEqual(result.error, "Frequency out of range")

    def test_not_connected_short_circuits_without_sending_anything(self):
        source = _make_source()
        source._connected = False
        result = _run(source.set_radio_params(868.1, 250.0, 11, 5))
        self.assertFalse(result.success)
        self.assertEqual(result.error, "Not connected")


class TestSetRadioParamsTimeoutRecovery(unittest.TestCase):
    def test_timeout_then_reconnect_with_matching_params_verifies_as_success(self):
        source = _make_source()
        set_calls = 0

        async def fake_send_set_radio_params(mc, freq, bw, sf, cr):
            nonlocal set_calls
            set_calls += 1
            return SendResult(success=False, error="set_radio timed out", timed_out=True)

        async def fake_get_radio_info():
            return RadioStatus(frequency_mhz=868.1, bandwidth_khz=250.0, spreading_factor=11, coding_rate=5)

        source._trigger_reconnect = _reconnect_after(source)
        source.get_radio_info = fake_get_radio_info

        with patch.object(mus, "send_set_radio_params", fake_send_set_radio_params):
            result = _run(source.set_radio_params(868.1, 250.0, 11, 5))

        self.assertTrue(result.success)
        self.assertEqual(set_calls, 1, "no retry needed -- the silent reboot already applied it")

    def test_timeout_then_wrong_params_retries_once_and_succeeds(self):
        source = _make_source()
        set_calls = 0
        # First read-back reports the OLD params (silent reboot came back
        # unchanged); second (post-retry) read-back reports the requested ones.
        readbacks = [
            RadioStatus(frequency_mhz=915.0, bandwidth_khz=250.0, spreading_factor=11, coding_rate=5),
            RadioStatus(frequency_mhz=868.1, bandwidth_khz=250.0, spreading_factor=11, coding_rate=5),
        ]

        async def fake_send_set_radio_params(mc, freq, bw, sf, cr):
            nonlocal set_calls
            set_calls += 1
            # First attempt times out (the actual bug this recovers from);
            # the live retry on the reconnected link succeeds cleanly.
            if set_calls == 1:
                return SendResult(success=False, error="set_radio timed out", timed_out=True)
            return SendResult(success=True)

        async def fake_get_radio_info():
            return readbacks.pop(0)

        source._trigger_reconnect = _reconnect_after(source)
        source.get_radio_info = fake_get_radio_info

        with patch.object(mus, "send_set_radio_params", fake_send_set_radio_params):
            result = _run(source.set_radio_params(868.1, 250.0, 11, 5))

        self.assertTrue(result.success)
        self.assertEqual(set_calls, 2, "should have retried exactly once")
        self.assertEqual(
            len(readbacks), 1,
            "only the first verify should have read radio info -- the retry's own clean success is "
            "trusted directly afterward, same as the main clean-success path never reading it back either",
        )

    def test_never_reconnects_reports_failure_without_hanging(self):
        source = _make_source()

        async def fake_send_set_radio_params(mc, freq, bw, sf, cr):
            return SendResult(success=False, error="set_radio timed out", timed_out=True)

        def fake_trigger_reconnect(reason):
            source._connected = False  # never comes back

        # Shrink the verify window so this test doesn't actually wait 75s.
        with patch.object(mus, "_RADIO_VERIFY_TIMEOUT_SECONDS", 0.05), \
             patch.object(mus, "_RADIO_VERIFY_POLL_INTERVAL_SECONDS", 0.01), \
             patch.object(mus, "_RADIO_RETRY_CONNECTED_CHECK_SECONDS", 0.02), \
             patch.object(mus, "send_set_radio_params", fake_send_set_radio_params):
            source._trigger_reconnect = fake_trigger_reconnect
            result = _run(source.set_radio_params(868.1, 250.0, 11, 5))

        self.assertFalse(result.success)
        self.assertTrue(result.timed_out)
        self.assertIn("did not reconnect", result.error)


if __name__ == "__main__":
    unittest.main()
