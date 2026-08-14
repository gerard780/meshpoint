"""One capture source failing to start must not abort the others."""

from __future__ import annotations

import asyncio
import unittest

from src.capture.base import CaptureSource
from src.capture.capture_coordinator import CaptureCoordinator


class _StubSource(CaptureSource):
    def __init__(self, name: str, fail: Exception | None = None):
        self._name = name
        self._fail = fail
        self.started = False

    @property
    def name(self) -> str:
        return self._name

    async def start(self) -> None:
        if self._fail is not None:
            raise self._fail
        self.started = True

    async def stop(self) -> None:
        pass

    async def packets(self):
        return
        yield  # pragma: no cover


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestCaptureCoordinatorSoftFail(unittest.TestCase):
    def test_one_source_raising_does_not_abort_the_rest(self):
        coordinator = CaptureCoordinator()
        busy = _StubSource("busy-serial", fail=OSError("port is busy"))
        concentrator = _StubSource("concentrator")
        other = _StubSource("other-companion")
        coordinator.add_source(busy)
        coordinator.add_source(concentrator)
        coordinator.add_source(other)

        # Must not raise -- the whole point of the fix.
        _run(coordinator.start())

        self.assertFalse(busy.started)
        self.assertTrue(concentrator.started)
        self.assertTrue(other.started)
        _run(coordinator.stop())

    def test_import_error_still_aborts(self):
        coordinator = CaptureCoordinator()
        coordinator.add_source(_StubSource("missing-dep", fail=ImportError("no module")))
        coordinator.add_source(_StubSource("never-reached"))

        with self.assertRaises(ImportError):
            _run(coordinator.start())


if __name__ == "__main__":
    unittest.main()
