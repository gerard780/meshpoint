"""Capture source for the POCSAG/DAPNET companion (extra/pocsag_companion).

Reads newline-delimited JSON off a USB serial connection to an ESP32
board running that sketch. Unlike the Meshtastic/MeshCore companions,
there is no request/response library here -- the board just prints one
JSON object per decoded page whenever it happens to receive one, plus
assorted plain-text boot/log lines this source simply ignores. The one
exception is a one-shot ``{"cmd":"status"}`` query sent right after
connecting, answered with ``{"type":"status","board":...,"callsign":...,
"freq":...}`` -- used for the topbar chip, not the packet feed.

pyserial's ``readline()`` is blocking, so the actual read loop runs in
a background thread (mirrors ``src/hal/gps_reader.py``'s fallback
path) and hands lines back to the asyncio side via
``loop.call_soon_threadsafe``, matching every other capture source's
``asyncio.Queue``-backed ``packets()`` shape.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any, AsyncIterator, Optional

from src.capture.base import CaptureSource
from src.models.packet import RawCapture
from src.models.signal import SignalMetrics

logger = logging.getLogger(__name__)

# The companion has no RF signal metrics on its JSON serial protocol at
# all -- this is a fixed placeholder for RawCapture's required (non-
# Optional) `signal` field only. The adapted Packet's own `signal`
# stays None; nothing downstream reads these placeholder numbers.
_NO_SIGNAL = SignalMetrics(
    rssi=0.0, snr=0.0, frequency_mhz=439.9875, spreading_factor=0, bandwidth_khz=0.0,
)


class DapnetSerialSource(CaptureSource):
    """Receives decoded POCSAG/DAPNET pages from a companion board over USB serial."""

    def __init__(
        self,
        serial_port: Optional[str] = None,
        serial_baud: int = 115200,
        label: str = "",
    ):
        self._port = serial_port
        self._baud = serial_baud
        self._label = label
        self._serial = None
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._running = False
        self._connected = False
        self._status: dict[str, Any] = {}
        self._reader_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def name(self) -> str:
        return f"dapnet_{self._label}" if self._label else "dapnet"

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def status(self) -> dict[str, Any]:
        """Cached reply from the one-shot {"cmd":"status"} query -- board/
        callsign/freq, or {} if the companion hasn't answered yet (query
        lost, or a firmware too old to understand "cmd")."""
        return self._status

    async def start(self) -> None:
        if not self._port:
            logger.warning(
                "%s: no serial_port configured, source will not run", self.name
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
        logger.info("%s: started on %s @ %d baud", self.name, self._port, self._baud)

    async def stop(self) -> None:
        self._running = False
        self._connected = False
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None

    async def packets(self) -> AsyncIterator[RawCapture]:
        while self._running:
            try:
                raw = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                yield raw
            except asyncio.TimeoutError:
                continue

    def _read_loop(self) -> None:
        """Runs in a background thread -- pyserial's readline() blocks."""
        try:
            self._serial.write(b'{"cmd":"status"}\n')
        except Exception:
            logger.debug("%s: failed to send status query", self.name)

        while self._running and self._serial is not None:
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
                # Boot banners, WiFi/OTA logs, "SEND BLOCKED"/"SEND FAILED"
                # lines, etc. -- expected and harmless, just not for us.
                continue
            if isinstance(data, dict) and data.get("type") == "status":
                self._status = {
                    "board": data.get("board"),
                    "callsign": data.get("callsign"),
                    "freq": data.get("freq"),
                }
                continue
            if self._loop is not None:
                self._loop.call_soon_threadsafe(self._enqueue, line)

    def _enqueue(self, line: bytes) -> None:
        try:
            self._queue.put_nowait(
                RawCapture(payload=line, signal=_NO_SIGNAL, capture_source=self.name)
            )
        except asyncio.QueueFull:
            logger.warning("%s: queue full, dropping line", self.name)


def _parse_json_line(line: bytes) -> Optional[dict]:
    """Parse a serial line as a JSON object, or None if it isn't one.

    Cheap pre-check on the first byte before ever calling json.loads --
    the sketch prints far more plain-text log lines than JSON lines."""
    stripped = line.strip()
    if not stripped or stripped[:1] != b"{":
        return None
    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None
