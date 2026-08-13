"""Apply MeshCore companion radio params over a live connection.

Mirrors ``meshpoint meshcore-radio`` CLI ``set_radio`` + ``reboot``,
but reuses the open USB handle so reconnect recovers via the capture
source instead of a cold CLI handshake.

Cross-band changes (e.g. EU → USA/Canada) sometimes reboot the
companion without an OK event. ``MeshcoreRadioTimeoutRecovery`` treats
that timeout as a possible silent reboot and verifies radio params
after reconnect.
Credit: javastraat/meshpoint 471d572
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

from src.transmit.meshcore_tx_client import RadioStatus, SendResult

logger = logging.getLogger(__name__)

# Band changes can take longer than short commands (set_name / advert).
_SET_RADIO_TIMEOUT_SECONDS = 20.0
_REBOOT_TIMEOUT_SECONDS = 10.0
# First reconnect attempt + DTR retry path observed ~30s on RAK V2.
_RECONNECT_VERIFY_SECONDS = 75.0
_FREQ_MATCH_TOLERANCE_MHZ = 0.002
_BW_MATCH_TOLERANCE_KHZ = 0.1


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

        freq = round(float(freq), 3)
        bw = round(float(bw), 1)
        sf = int(sf)
        cr = int(cr)

        validation_error = self._validate(freq, bw, sf, cr)
        if validation_error:
            return SendResult(success=False, error=validation_error)

        try:
            from meshcore import EventType
        except Exception:
            return SendResult(
                success=False, error="meshcore library unavailable"
            )

        await self._pause_auto_fetch(mc)

        try:
            result = await asyncio.wait_for(
                mc.commands.set_radio(freq, bw, sf, cr),
                timeout=_SET_RADIO_TIMEOUT_SECONDS,
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
            # meshcore_py returns these when the companion never ACKs
            # (common on cross-band set_radio that silent-reboots).
            # Treat as timeout so TxClient can reconnect + verify.
            if detail in ("no_event_received", "timeout"):
                return SendResult(
                    success=False,
                    error=f"set_radio timed out ({detail})",
                    timed_out=True,
                )
            error = (
                f"Companion rejected radio params: {detail}"
                if detail
                else "Companion rejected radio params"
            )
            return SendResult(success=False, error=error)

        try:
            await asyncio.wait_for(
                mc.commands.reboot(),
                timeout=_REBOOT_TIMEOUT_SECONDS,
            )
        except Exception:
            logger.debug(
                "MeshCore reboot after set_radio failed or timed out; "
                "companion may still reboot",
                exc_info=True,
            )

        return SendResult(success=True, event_type="set_radio")

    @staticmethod
    async def _pause_auto_fetch(mc: Any) -> None:
        """Stop background message polling so set_radio owns the command channel."""
        stop = getattr(mc, "stop_auto_message_fetching", None)
        if not callable(stop):
            return
        try:
            await stop()
        except Exception:
            logger.debug(
                "Could not pause MeshCore auto-fetch before set_radio",
                exc_info=True,
            )

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


class MeshcoreRadioTimeoutRecovery:
    """After set_radio timeout: wait for reconnect and confirm radio params."""

    async def verify(
        self,
        *,
        wait_connected: Callable[[float], Awaitable[bool]],
        get_radio_info: Callable[[], Awaitable[Optional[RadioStatus]]],
        freq: float,
        bw: float,
        sf: int,
        cr: int,
    ) -> SendResult:
        logger.warning(
            "set_radio timed out; waiting for companion reconnect to verify "
            "(silent reboot is common on cross-band changes)"
        )
        ok = await wait_connected(_RECONNECT_VERIFY_SECONDS)
        if not ok:
            return SendResult(
                success=False,
                error=(
                    "set_radio timed out and companion did not reconnect "
                    "in time; wait for MeshCore to reconnect and retry"
                ),
                timed_out=True,
            )

        info = await get_radio_info()
        if info is None:
            return SendResult(
                success=False,
                error=(
                    "set_radio timed out; companion reconnected but radio "
                    "info is unavailable; check preset and retry"
                ),
                timed_out=True,
            )

        if self.params_match(info, freq, bw, sf, cr):
            logger.info(
                "set_radio timeout recovered: companion radio matches "
                "%.3f MHz / BW%.1f / SF%d / CR%d",
                freq, bw, sf, cr,
            )
            return SendResult(success=True, event_type="set_radio")

        return SendResult(
            success=False,
            error=(
                "set_radio timed out; companion reconnected but radio "
                f"is {info.frequency_mhz:.3f} MHz / BW{info.bandwidth_khz:.1f} "
                f"/ SF{info.spreading_factor} / CR{info.coding_rate} "
                f"(wanted {freq:.3f} / BW{bw:.1f} / SF{sf} / CR{cr})"
            ),
            timed_out=True,
        )

    @staticmethod
    def params_match(
        info: RadioStatus,
        freq: float,
        bw: float,
        sf: int,
        cr: int,
    ) -> bool:
        return (
            abs(info.frequency_mhz - freq) <= _FREQ_MATCH_TOLERANCE_MHZ
            and abs(info.bandwidth_khz - bw) <= _BW_MATCH_TOLERANCE_KHZ
            and int(info.spreading_factor) == int(sf)
            and int(info.coding_rate) == int(cr)
        )


class MeshcoreRadioSetCoordinator:
    """Apply radio params with timeout reconnect-verify and one live retry.

    Observed on RAK V2: EU→USA/Canada often returns no_event_received and
    the companion comes back still on the old preset. A second set_radio
    on the freshly reconnected link usually succeeds (same as a manual
    re-click once MeshCore is green again).
    """

    _POST_RECONNECT_SETTLE_SECONDS = 1.5

    async def run(
        self,
        *,
        apply: Callable[..., Awaitable[SendResult]],
        trigger_reconnect: Callable[[str], None],
        wait_connected: Callable[[float], Awaitable[bool]],
        get_radio_info: Callable[[], Awaitable[Optional[RadioStatus]]],
        freq: float,
        bw: float,
        sf: int,
        cr: int,
    ) -> SendResult:
        result = await apply(freq, bw, sf, cr)
        if result.success:
            trigger_reconnect(
                f"radio set to {freq:.3f} MHz / BW{bw:.1f} "
                f"/ SF{sf} / CR{cr} -- rebooting"
            )
            return result
        if not result.timed_out:
            return result

        trigger_reconnect(result.error or "set_radio timed out")
        verified = await MeshcoreRadioTimeoutRecovery().verify(
            wait_connected=wait_connected,
            get_radio_info=get_radio_info,
            freq=freq,
            bw=bw,
            sf=sf,
            cr=cr,
        )
        if verified.success:
            return verified

        if not await wait_connected(5.0):
            return verified

        logger.warning(
            "set_radio still on old preset after reconnect; "
            "retrying once on live link"
        )
        await asyncio.sleep(self._POST_RECONNECT_SETTLE_SECONDS)
        retry = await apply(freq, bw, sf, cr)
        if retry.success:
            trigger_reconnect(
                f"radio set to {freq:.3f} MHz / BW{bw:.1f} "
                f"/ SF{sf} / CR{cr} -- rebooting (retry)"
            )
            return retry
        if retry.timed_out:
            trigger_reconnect(retry.error or "set_radio timed out")
            return await MeshcoreRadioTimeoutRecovery().verify(
                wait_connected=wait_connected,
                get_radio_info=get_radio_info,
                freq=freq,
                bw=bw,
                sf=sf,
                cr=cr,
            )
        return retry
