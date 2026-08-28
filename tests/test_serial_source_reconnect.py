"""SerialCaptureSource.start() used to raise straight out on a busy/wrong
port, permanently -- nothing ever tried again short of a manual service
restart. It should now retry in the background instead, mirroring
meshcore_usb_source.py's own proven reconnect loop."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from src.capture.serial_source import SerialCaptureSource


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(coro)
        pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
        if pending:
            for t in pending:
                t.cancel()
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        return result
    finally:
        loop.close()


class TestInitialConnect(unittest.TestCase):
    def test_clean_connect_does_not_schedule_a_reconnect_task(self):
        source = SerialCaptureSource(port="/dev/fake")

        def fake_blocking_connect():
            return object(), {"region": "US"}, {0: b"channel-key"}

        with patch.object(source, "_blocking_connect", side_effect=fake_blocking_connect):
            _run(source.start())

        self.assertTrue(source.connected)
        self.assertIsNone(source._reconnect_task)

    def test_import_error_still_raises_out_of_start(self):
        source = SerialCaptureSource(port="/dev/fake")

        def raise_import_error():
            raise ImportError("no meshtastic package")

        with patch.object(source, "_blocking_connect", side_effect=raise_import_error):
            with self.assertRaises(ImportError):
                _run(source.start())

        self.assertIsNone(source._reconnect_task)


class TestBackgroundReconnect(unittest.TestCase):
    def test_failed_initial_connect_schedules_background_retry_that_eventually_succeeds(self):
        source = SerialCaptureSource(port="/dev/fake")
        attempts = {"count": 0}

        def flaky_connect():
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise OSError("port busy")
            return object(), {"region": "US"}, {0: b"channel-key"}

        async def scenario():
            with patch("src.capture.serial_source._RECONNECT_BASE_DELAY_SECONDS", 0.01), \
                 patch("src.capture.serial_source._RECONNECT_MAX_DELAY_SECONDS", 0.02), \
                 patch.object(source, "_blocking_connect", side_effect=flaky_connect):
                await source.start()
                self.assertFalse(
                    source.connected,
                    "must not raise or block -- start() returns even though the first attempt failed",
                )
                self.assertIsNotNone(source._reconnect_task)
                await asyncio.wait_for(source._reconnect_task, timeout=2)

        _run(scenario())
        self.assertTrue(source.connected)
        self.assertGreaterEqual(attempts["count"], 3)

    def test_stop_cancels_an_in_progress_reconnect_loop(self):
        source = SerialCaptureSource(port="/dev/fake")

        def always_fails():
            raise OSError("port busy")

        async def scenario():
            with patch("src.capture.serial_source._RECONNECT_BASE_DELAY_SECONDS", 5), \
                 patch.object(source, "_blocking_connect", side_effect=always_fails):
                await source.start()
                self.assertIsNotNone(source._reconnect_task)
                task = source._reconnect_task
                await source.stop()
                self.assertTrue(task.cancelled() or task.done())
                self.assertIsNone(source._reconnect_task)
                self.assertFalse(source._running)

        _run(scenario())


if __name__ == "__main__":
    unittest.main()
