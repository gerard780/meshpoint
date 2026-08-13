"""DTR soft-reset helper for MeshCore USB companions."""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

_DTR_RESET_PULSE_SECONDS = 0.1


def pulse_dtr_reset(port: str, baud_rate: int) -> None:
    """Toggle DTR low to soft-reset an ESP32 companion. Best-effort."""
    try:
        import serial
    except ImportError:
        return
    try:
        with serial.Serial(port, baud_rate, timeout=0.5) as ser:
            ser.dtr = False
            time.sleep(_DTR_RESET_PULSE_SECONDS)
            ser.dtr = True
        logger.info(
            "MeshCore USB pulsed DTR on %s to attempt soft reset",
            port,
        )
    except Exception as exc:
        logger.debug("MeshCore USB DTR pulse skipped on %s: %s", port, exc)
