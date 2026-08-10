"""Exclusive-port MeshCore radio apply (CLI-style cold path).

Live shared-handle set_radio often returns no_event_received on
cross-band changes while the capture source owns the serial port.
Cold exclusive access (detach → set_radio → reboot → verify → reattach)
matches ``meshpoint meshcore-radio`` and was confirmed on RAK V2 hardware.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from src.transmit.meshcore_radio_apply import MeshcoreRadioTimeoutRecovery
from src.transmit.meshcore_tx_client import RadioStatus, SendResult

logger = logging.getLogger(__name__)

_HANDSHAKE_TIMEOUT_SECONDS = 15.0
_REBOOT_SETTLE_SECONDS = 8.0
_SET_RADIO_TIMEOUT_SECONDS = 20.0


class MeshcorePortLease:
    """Temporarily take the MeshCore USB serial port from the capture source."""

    async def detach(self, source: Any) -> Optional[str]:
        port = getattr(source, "_resolved_port", None)
        if not port:
            return None
        logger.info(
            "MeshCore USB detaching %s for exclusive radio config", port
        )
        await self._cancel_task(source, "_health_task")
        await self._cancel_task(source, "_reconnect_task")
        source._reconnect_in_progress = False
        disconnect = getattr(source, "_disconnect", None)
        if callable(disconnect):
            await disconnect()
        return port

    async def reattach(self, source: Any) -> None:
        if not getattr(source, "_running", False):
            return
        port = getattr(source, "_resolved_port", None)
        if not port:
            return
        resume = getattr(source, "_reconnect_until_connected", None)
        if not callable(resume):
            return
        logger.info("MeshCore USB reattaching after exclusive radio config")
        source._reconnect_task = asyncio.create_task(
            resume(),
            name="meshcore-post-config-reconnect",
        )

    @staticmethod
    async def _cancel_task(source: Any, attr: str) -> None:
        task = getattr(source, attr, None)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        setattr(source, attr, None)


class MeshcoreExclusiveRadioApply:
    """Apply radio params with exclusive ownership of the companion serial port."""

    async def apply_via_source(
        self,
        source: Any,
        freq: float,
        bw: float,
        sf: int,
        cr: int,
    ) -> SendResult:
        lease = MeshcorePortLease()
        port = await lease.detach(source)
        if not port:
            return SendResult(
                success=False, error="MeshCore serial port not resolved"
            )

        baud = int(getattr(source, "_baud_rate", 115200) or 115200)
        freq = round(float(freq), 3)
        bw = round(float(bw), 1)
        sf = int(sf)
        cr = int(cr)

        try:
            return await self._cold_apply(port, baud, freq, bw, sf, cr)
        finally:
            await lease.reattach(source)

    async def _cold_apply(
        self,
        port: str,
        baud: int,
        freq: float,
        bw: float,
        sf: int,
        cr: int,
    ) -> SendResult:
        try:
            from meshcore import MeshCore, EventType
        except Exception:
            return SendResult(
                success=False, error="meshcore library unavailable"
            )

        from src.capture.meshcore_dtr import pulse_dtr_reset

        await asyncio.to_thread(pulse_dtr_reset, port, baud)
        await asyncio.sleep(2.0)

        mc = await MeshCore.create_serial(
            port, baud, default_timeout=_HANDSHAKE_TIMEOUT_SECONDS
        )
        if mc is None:
            return SendResult(
                success=False,
                error="MeshCore handshake failed during exclusive radio set",
            )

        try:
            try:
                result = await asyncio.wait_for(
                    mc.commands.set_radio(freq, bw, sf, cr),
                    timeout=_SET_RADIO_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                return SendResult(
                    success=False,
                    error="set_radio timed out (exclusive)",
                    timed_out=True,
                )

            if hasattr(result, "type") and result.type == EventType.ERROR:
                detail = ""
                payload = getattr(result, "payload", None)
                if isinstance(payload, dict):
                    detail = str(
                        payload.get("reason")
                        or payload.get("error")
                        or payload
                    )
                if detail in ("no_event_received", "timeout"):
                    return SendResult(
                        success=False,
                        error=f"set_radio timed out ({detail})",
                        timed_out=True,
                    )
                return SendResult(
                    success=False,
                    error=(
                        f"Companion rejected radio params: {detail}"
                        if detail
                        else "Companion rejected radio params"
                    ),
                )

            try:
                await asyncio.wait_for(mc.commands.reboot(), timeout=10.0)
            except Exception:
                logger.debug(
                    "Exclusive reboot after set_radio failed; continuing",
                    exc_info=True,
                )
        finally:
            try:
                await mc.disconnect()
            except Exception:
                pass

        await asyncio.sleep(_REBOOT_SETTLE_SECONDS)
        await asyncio.to_thread(pulse_dtr_reset, port, baud)
        await asyncio.sleep(2.0)

        mc2 = await MeshCore.create_serial(
            port, baud, default_timeout=_HANDSHAKE_TIMEOUT_SECONDS
        )
        if mc2 is None:
            return SendResult(
                success=False,
                error=(
                    "set_radio sent but companion did not come back for verify"
                ),
                timed_out=True,
            )

        try:
            info = mc2.self_info or {}
            status = RadioStatus(
                frequency_mhz=float(info.get("radio_freq", 0.0) or 0.0),
                bandwidth_khz=float(info.get("radio_bw", 0.0) or 0.0),
                spreading_factor=int(info.get("radio_sf", 0) or 0),
                coding_rate=int(info.get("radio_cr", 0) or 0),
                name=str(info.get("name") or ""),
            )
        finally:
            try:
                await mc2.disconnect()
            except Exception:
                pass

        if MeshcoreRadioTimeoutRecovery.params_match(status, freq, bw, sf, cr):
            logger.info(
                "Exclusive set_radio OK: %.3f MHz / BW%.1f / SF%d / CR%d",
                freq, bw, sf, cr,
            )
            return SendResult(success=True, event_type="set_radio")

        return SendResult(
            success=False,
            error=(
                "Exclusive set_radio verify mismatch: "
                f"got {status.frequency_mhz:.3f} / BW{status.bandwidth_khz:.1f} "
                f"/ SF{status.spreading_factor} / CR{status.coding_rate} "
                f"(wanted {freq:.3f} / BW{bw:.1f} / SF{sf} / CR{cr})"
            ),
        )
