"""Background poller for the RF Environment companion (extra/rfenv_companion).

A Heltec V3 with its own SX1262, polled over USB serial for a real
ambient-RSSI histogram -- the fallback for boards (e.g. RAK2287)
confirmed to have no SX1261, where a real hardware spectral scan is
otherwise never possible (see ``rf_routes._FLEET_SPECTRAL_SCAN_NOTE``).

``RfEnvCompanionScanService`` exposes the same public surface
``rf_routes._spectral_status()`` already duck-types against for the real
HAL-backed ``SpectralScanService`` (``hardware_supported``, ``is_running``,
``scans_run``, ``scans_failed``, ``histogram_payload()``), plus an
``is_companion`` marker rf_routes.py uses to add a "via companion" note --
so this can be passed into ``rf_routes.init_routes`` as a drop-in stand-in
whenever the real service is unavailable. Server wiring only ever
constructs this when the real ``SpectralScanService`` is ``None``.

Wire protocol matches ``extra/rfenv_companion/rfenv_companion.ino``:
newline-delimited JSON, request/response, same idiom as
``DapnetSerialSource`` (``src/capture/dapnet_source.py``) -- a reader
thread + ``Future``-based request/response, since pyserial's
``readline()`` blocks. This is a new, self-contained implementation
modeled on that class's pattern rather than sharing code with it: this
isn't a ``CaptureSource`` (no packets flow into the pipeline -- this is
a telemetry poller, closer in spirit to ``SpectralScanService``), and
``DapnetSerialSource`` is already live/field-verified -- not worth
coupling to for a brand-new, unbuilt feature.
"""
from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import time
from typing import Optional

from src.api.telemetry.noise_floor import NoiseFloorTracker
from src.hal.sx1302_spectral_scan import SpectralScanResult, spectral_scan_result_payload

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS: float = 60.0
DEFAULT_NB_SCAN: int = 512
_SCAN_TIMEOUT_SECONDS: float = 8.0
_STATUS_TIMEOUT_SECONDS: float = 5.0


class RfEnvCompanionScanService:
    """Periodic scan-over-serial -> NoiseFloorTracker/histogram pump.

    Mirrors ``SpectralScanService``'s own role (scheduling + result
    plumbing) but drives a companion board over USB serial instead of
    the local HAL.
    """

    def __init__(
        self,
        tracker: NoiseFloorTracker,
        serial_port: Optional[str],
        serial_baud: int = 115200,
        frequency_hz: int = 0,
        bandwidth_khz: float = 0.0,
        nb_scan: int = DEFAULT_NB_SCAN,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        label: str = "",
    ) -> None:
        self._tracker = tracker
        self._port = serial_port
        self._baud = serial_baud
        self._frequency_hz = frequency_hz
        self._bandwidth_khz = bandwidth_khz
        self._nb_scan = nb_scan
        self._interval_seconds = max(5.0, interval_seconds)
        self._label = label
        self._serial = None
        self._running = False
        self._connected = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._poll_task: Optional[asyncio.Task] = None
        # Outgoing commands are handed to the reader thread through a
        # stdlib queue.Queue (not asyncio.Queue -- drained from that
        # thread, not the event loop), same reasoning as DapnetSerialSource.
        self._command_queue: "queue.Queue[bytes]" = queue.Queue()
        # Only one request/response in flight at a time -- the wire
        # protocol has no request-id, same constraint DapnetSerialSource
        # documents for its own send_command().
        self._command_lock = asyncio.Lock()
        self._pending_expect_type: Optional[str] = None
        self._pending_future: Optional[asyncio.Future] = None
        self._scans_run = 0
        self._scans_failed = 0
        self._last_result: Optional[SpectralScanResult] = None
        self._ever_connected = False

    @property
    def name(self) -> str:
        return f"rfenv_companion_{self._label}" if self._label else "rfenv_companion"

    @property
    def is_companion(self) -> bool:
        """Duck-typed marker rf_routes.py checks to add a "via companion"
        note -- distinguishes this from the real HAL-backed service."""
        return True

    @property
    def hardware_supported(self) -> bool:
        return self._ever_connected

    @property
    def is_running(self) -> bool:
        return self._poll_task is not None and not self._poll_task.done()

    @property
    def scans_run(self) -> int:
        return self._scans_run

    @property
    def scans_failed(self) -> int:
        return self._scans_failed

    def histogram_payload(self) -> Optional[dict]:
        return spectral_scan_result_payload(self._last_result)

    async def send_command(
        self, command: dict, expect_type: str, timeout: float,
    ) -> Optional[dict]:
        async with self._command_lock:
            if not self._connected or self._loop is None:
                return None
            future: asyncio.Future = self._loop.create_future()
            self._pending_expect_type = expect_type
            self._pending_future = future
            self._command_queue.put_nowait(json.dumps(command).encode() + b"\n")
            try:
                return await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError:
                return None
            finally:
                self._pending_expect_type = None
                self._pending_future = None

    async def start(self) -> None:
        if not self._port:
            logger.warning(
                "%s: no serial_port configured, service will not run", self.name
            )
            return
        try:
            import serial
            self._serial = serial.Serial(self._port, self._baud, timeout=1.0)
        except Exception:
            logger.exception("%s: failed to open serial port %s", self.name, self._port)
            return

        self._running = True
        self._connected = True
        self._loop = asyncio.get_running_loop()
        self._reader_thread = threading.Thread(
            target=self._read_loop, name=f"{self.name}-reader", daemon=True
        )
        self._reader_thread.start()
        self._poll_task = asyncio.create_task(self._poll_loop(), name=f"{self.name}-poll")
        logger.info("%s: started on %s @ %d baud", self.name, self._port, self._baud)

    async def stop(self) -> None:
        self._running = False
        self._connected = False
        if self._poll_task is not None:
            self._poll_task.cancel()
            self._poll_task = None
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None

    async def _poll_loop(self) -> None:
        try:
            # First status query confirms the companion is actually alive
            # before the RF Environment page starts reporting it as
            # "supported" -- hardware_supported stays False until either
            # this or a scan actually gets a reply.
            status = await self.send_command(
                {"cmd": "status"}, expect_type="status", timeout=_STATUS_TIMEOUT_SECONDS,
            )
            if status is not None:
                self._ever_connected = True
            while self._running:
                await self._run_one_scan()
                await asyncio.sleep(self._interval_seconds)
        except asyncio.CancelledError:
            pass

    async def _run_one_scan(self) -> None:
        if self._frequency_hz <= 0:
            logger.warning("%s: no frequency_hz configured, skipping scan", self.name)
            return
        reply = await self.send_command(
            {
                "cmd": "scan",
                "frequency_hz": self._frequency_hz,
                "nb_scan": self._nb_scan,
            },
            expect_type="scan_result",
            timeout=_SCAN_TIMEOUT_SECONDS,
        )
        if reply is None:
            self._scans_failed += 1
            logger.warning("%s: scan timed out or companion disconnected", self.name)
            return

        try:
            levels = tuple(int(v) for v in reply["levels_dbm"])
            counts = tuple(int(v) for v in reply["counts"])
            frequency_hz = int(reply.get("frequency_hz", self._frequency_hz))
            nb_scan = int(reply.get("nb_scan", self._nb_scan))
        except (KeyError, TypeError, ValueError):
            self._scans_failed += 1
            logger.warning("%s: malformed scan_result reply: %r", self.name, reply)
            return

        result = SpectralScanResult(
            levels_dbm=levels,
            counts=counts,
            frequency_hz=frequency_hz,
            nb_scan=nb_scan,
            timestamp=time.time(),
        )
        self._last_result = result
        self._scans_run += 1
        self._ever_connected = True

        # floor_dbm/median_dbm are None when total_samples is 0 (an
        # all-empty histogram) -- NoiseFloorTracker.update_from_spectral
        # requires real floats, so skip that call rather than pass None;
        # the histogram itself is still stored/served either way.
        if result.floor_dbm is not None and result.median_dbm is not None:
            self._tracker.update_from_spectral(
                floor_dbm=result.floor_dbm,
                median_dbm=result.median_dbm,
                frequency_hz=result.frequency_hz,
                bandwidth_khz=self._bandwidth_khz,
                samples=result.total_samples,
                timestamp=result.timestamp,
            )

    def _read_loop(self) -> None:
        """Runs in a background thread -- pyserial's readline() blocks."""
        while self._running and self._serial is not None:
            self._flush_command_queue()
            try:
                line = self._serial.readline()
            except Exception:
                logger.exception("%s: serial read failed on %s", self.name, self._port)
                self._connected = False
                break
            if not line or not line.strip():
                continue
            data = _parse_json_line(line)
            if data is None:
                # Boot banners and other plain-text log lines -- expected
                # and harmless, just not for us.
                continue
            if (
                self._pending_expect_type is not None
                and data.get("type") == self._pending_expect_type
            ):
                self._resolve_pending(data)

    def _flush_command_queue(self) -> None:
        """Write any queued outgoing commands -- called once per read-loop
        pass, so a command queued while readline() is blocked waits at
        most one read timeout (1s) before actually going out."""
        while True:
            try:
                cmd_line = self._command_queue.get_nowait()
            except queue.Empty:
                return
            try:
                self._serial.write(cmd_line)
            except Exception:
                logger.exception("%s: failed to write command", self.name)

    def _resolve_pending(self, data: dict) -> None:
        future = self._pending_future
        if future is None or self._loop is None:
            return

        def _set_result() -> None:
            if not future.done():
                future.set_result(data)

        self._loop.call_soon_threadsafe(_set_result)


def _parse_json_line(line: bytes) -> Optional[dict]:
    """Parse a serial line as a JSON object, or None if it isn't one."""
    stripped = line.strip()
    if not stripped or stripped[:1] != b"{":
        return None
    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None
