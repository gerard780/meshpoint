"""Tests for RfEnvCompanionScanService's scan-reply handling.

Scope: exercises ``_run_one_scan``'s reply parsing / SpectralScanResult
reuse / NoiseFloorTracker wiring, and the standalone ``_parse_json_line``
helper -- the same level ``test_spectral_scan_service.py`` exercises its
own service against a fake HAL wrapper. ``send_command`` itself (the
real reader-thread/Future request-response machinery, which needs an
actual or fake serial.Serial object) is monkeypatched rather than
exercised here -- there's no physical companion board or fake serial
transport to drive it against yet.
"""
from __future__ import annotations

import unittest

from src.api.telemetry.noise_floor import NoiseFloorTracker, SOURCE_PACKETS, SOURCE_SPECTRAL
from src.api.telemetry.rfenv_companion_scan_service import (
    RfEnvCompanionScanService,
    _parse_json_line,
)


def _histogram_reply(frequency_hz: int = 869_525_000, nb_scan: int = 512) -> dict:
    # 35 levels, non-zero counts only in a couple of bins so percentile
    # math has something real to chew on.
    levels = [-140 + i * 3 for i in range(35)]
    counts = [0] * 35
    counts[5] = 10   # -125 dBm
    counts[20] = 10  # -80 dBm
    return {
        "type": "scan_result",
        "frequency_hz": frequency_hz,
        "nb_scan": nb_scan,
        "levels_dbm": levels,
        "counts": counts,
    }


class ParseJsonLineTest(unittest.TestCase):
    def test_valid_json_object(self):
        self.assertEqual(_parse_json_line(b'{"type":"status"}\n'), {"type": "status"})

    def test_plain_text_line_ignored(self):
        self.assertIsNone(_parse_json_line(b"[*] RF Environment companion ready\n"))

    def test_malformed_json_ignored(self):
        self.assertIsNone(_parse_json_line(b'{"type":\n'))

    def test_json_array_not_a_dict_ignored(self):
        self.assertIsNone(_parse_json_line(b"[1,2,3]\n"))

    def test_empty_line_ignored(self):
        self.assertIsNone(_parse_json_line(b"\n"))


class RunOneScanTest(unittest.IsolatedAsyncioTestCase):
    def _service(self, frequency_hz: int = 869_525_000) -> tuple[RfEnvCompanionScanService, NoiseFloorTracker]:
        tracker = NoiseFloorTracker()
        service = RfEnvCompanionScanService(
            tracker=tracker,
            serial_port="/dev/ttyUSB9",
            frequency_hz=frequency_hz,
            bandwidth_khz=250,
            nb_scan=512,
            interval_seconds=60.0,
        )
        return service, tracker

    async def test_successful_scan_updates_histogram_and_tracker(self) -> None:
        service, tracker = self._service()
        reply = _histogram_reply()

        async def fake_send_command(command, expect_type, timeout):
            self.assertEqual(command["cmd"], "scan")
            self.assertEqual(command["frequency_hz"], 869_525_000)
            self.assertEqual(expect_type, "scan_result")
            return reply

        service.send_command = fake_send_command  # type: ignore[method-assign]
        await service._run_one_scan()

        self.assertEqual(service.scans_run, 1)
        self.assertEqual(service.scans_failed, 0)
        payload = service.histogram_payload()
        self.assertIsNotNone(payload)
        self.assertEqual(payload["levels_dbm"], reply["levels_dbm"])
        self.assertEqual(payload["counts"], reply["counts"])
        self.assertEqual(payload["total_samples"], 20)
        self.assertEqual(payload["frequency_hz"], 869_525_000)

        snap = tracker.snapshot()
        self.assertEqual(snap["source"], SOURCE_SPECTRAL)
        self.assertIsNotNone(snap["value_dbm"])

    async def test_timeout_increments_scans_failed_not_scans_run(self) -> None:
        service, tracker = self._service()

        async def fake_send_command(command, expect_type, timeout):
            return None

        service.send_command = fake_send_command  # type: ignore[method-assign]
        await service._run_one_scan()

        self.assertEqual(service.scans_run, 0)
        self.assertEqual(service.scans_failed, 1)
        self.assertIsNone(service.histogram_payload())
        self.assertEqual(tracker.snapshot()["source"], SOURCE_PACKETS)

    async def test_malformed_reply_increments_scans_failed(self) -> None:
        service, tracker = self._service()

        async def fake_send_command(command, expect_type, timeout):
            return {"type": "scan_result", "frequency_hz": 869_525_000}  # no levels_dbm/counts

        service.send_command = fake_send_command  # type: ignore[method-assign]
        await service._run_one_scan()

        self.assertEqual(service.scans_run, 0)
        self.assertEqual(service.scans_failed, 1)

    async def test_no_frequency_configured_skips_scan_entirely(self) -> None:
        service, _tracker = self._service(frequency_hz=0)
        called = False

        async def fake_send_command(command, expect_type, timeout):
            nonlocal called
            called = True
            return None

        service.send_command = fake_send_command  # type: ignore[method-assign]
        await service._run_one_scan()

        self.assertFalse(called)
        self.assertEqual(service.scans_run, 0)
        self.assertEqual(service.scans_failed, 0)

    async def test_all_zero_histogram_skips_tracker_but_keeps_histogram(self) -> None:
        # total_samples == 0 -> floor_dbm/median_dbm are None -- must not
        # be passed to NoiseFloorTracker.update_from_spectral (which
        # requires real floats), but the (empty) histogram is still
        # stored/served.
        service, tracker = self._service()
        empty_reply = _histogram_reply()
        empty_reply["counts"] = [0] * 35

        async def fake_send_command(command, expect_type, timeout):
            return empty_reply

        service.send_command = fake_send_command  # type: ignore[method-assign]
        await service._run_one_scan()

        self.assertEqual(service.scans_run, 1)
        self.assertIsNotNone(service.histogram_payload())
        self.assertEqual(tracker.snapshot()["source"], SOURCE_PACKETS)

    def test_is_companion_marker(self) -> None:
        service, _tracker = self._service()
        self.assertTrue(service.is_companion)


if __name__ == "__main__":
    unittest.main()
