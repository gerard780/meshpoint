"""Apply MeshCore companion radio params over a live connection.

Mirrors ``meshpoint meshcore-radio`` CLI ``set_radio`` + ``reboot``,
but reuses the open USB handle so reconnect recovers via the capture
source instead of a cold CLI handshake.
Credit: javastraat/meshpoint 471d572
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.transmit.meshcore_tx_client import SendResult

logger = logging.getLogger(__name__)


class MeshcoreRadioApply:
    """Validate and apply frequency/BW/SF/CR on a raw meshcore handle."""

    async def apply(
        self,
        mc: Any,
        freq: float,
        bw: float,
        sf: int,
        cr: int,
    ) -> SendResult:
        if mc is None:
            return SendResult(success=False, error="Not connected")

        validation_error = self._validate(freq, bw, sf, cr)
        if validation_error:
            return SendResult(success=False, error=validation_error)

        try:
            from meshcore import EventType
        except Exception:
            return SendResult(
                success=False, error="meshcore library unavailable"
            )

        try:
            result = await asyncio.wait_for(
                mc.commands.set_radio(freq, bw, sf, cr),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            return SendResult(
                success=False, error="set_radio timed out", timed_out=True
            )
        except Exception as exc:
            logger.exception("MeshCore set_radio failed")
            return SendResult(success=False, error=str(exc))

        if hasattr(result, "type") and result.type == EventType.ERROR:
            detail = self._error_detail(result)
            error = (
                f"Companion rejected radio params: {detail}"
                if detail
                else "Companion rejected radio params"
            )
            return SendResult(success=False, error=error)

        try:
            await asyncio.wait_for(mc.commands.reboot(), timeout=10.0)
        except Exception:
            logger.debug(
                "MeshCore reboot after set_radio failed or timed out; "
                "companion may still reboot",
                exc_info=True,
            )

        return SendResult(success=True, event_type="set_radio")

    @staticmethod
    def _validate(freq: float, bw: float, sf: int, cr: int) -> str:
        if not (150.0 <= freq <= 2500.0):
            return f"Frequency {freq} MHz out of range (150-2500)"
        if not (7.0 <= bw <= 500.0):
            return f"Bandwidth {bw} kHz out of range (7-500)"
        if not (5 <= sf <= 12):
            return f"Spreading factor {sf} out of range (5-12)"
        if not (5 <= cr <= 8):
            return f"Coding rate {cr} out of range (5-8)"
        return ""

    @staticmethod
    def _error_detail(result: Any) -> str:
        payload = getattr(result, "payload", None)
        if isinstance(payload, dict):
            return str(
                payload.get("reason")
                or payload.get("error")
                or payload
            )
        if payload is not None:
            return str(payload)
        return ""
