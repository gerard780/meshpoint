"""DTR soft-reset helper for MeshCore USB companions.

Standalone (not a MeshcoreUsbCaptureSource method) so both the source's
own reconnect loop and the exclusive-lease radio-apply path
(meshcore_exclusive_radio.py, which operates on a bare port string with
no capture-source instance during its cold connection) can use it.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

_DTR_RESET_PULSE_SECONDS = 0.1


def pulse_dtr_reset(port: str, baud_rate: int) -> None:
    """Toggle DTR low to soft-reset an ESP32 companion. Best-effort.

    Call via ``asyncio.to_thread`` -- pyserial's open and the DTR sleep
    are blocking. Safe to fail silently: if the host's serial driver
    doesn't expose DTR or the port is unavailable, the caller's own
    connect attempt is what actually matters, not this reset.
    """
    try:
        import serial  # transitive dep via meshcore lib
    except ImportError:
        return
    try:
        with serial.Serial(port, baud_rate, timeout=0.5) as ser:
            ser.dtr = False
            time.sleep(_DTR_RESET_PULSE_SECONDS)
            ser.dtr = True
        logger.info("MeshCore USB pulsed DTR on %s to attempt soft reset", port)
    except Exception as exc:
        logger.debug("MeshCore USB DTR pulse skipped on %s: %s", port, exc)
