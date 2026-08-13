"""Rename a MeshCore USB companion via CMD_SET_ADVERT_NAME."""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)


class MeshcoreCompanionRename:
    """Validate and apply a companion advert name under the command lock."""

    async def run(
        self,
        *,
        mc,
        name: str,
        cmd_lock: asyncio.Lock,
        connected: bool,
        fail_timeout: Callable[[str], object],
        post_command: Callable[[], Awaitable[None]],
    ):
        from src.transmit.meshcore_tx_client import (
            MAX_COMPANION_NAME_BYTES,
            SendResult,
        )

        if not connected:
            return SendResult(success=False, error="Not connected")

        cleaned = (name or "").strip()
        if not cleaned:
            return SendResult(success=False, error="Name must not be empty")
        encoded_len = len(cleaned.encode("utf-8"))
        if encoded_len > MAX_COMPANION_NAME_BYTES:
            return SendResult(
                success=False,
                error=(
                    f"Name is {encoded_len} bytes (UTF-8); "
                    f"companion accepts at most {MAX_COMPANION_NAME_BYTES}."
                ),
            )

        try:
            from meshcore import EventType
        except Exception:
            return SendResult(
                success=False, error="meshcore library unavailable"
            )

        try:
            async with cmd_lock:
                if mc is None:
                    return SendResult(success=False, error="Not connected")
                result = await asyncio.wait_for(
                    mc.commands.set_name(cleaned),
                    timeout=10.0,
                )
        except asyncio.TimeoutError:
            return fail_timeout("set_name timed out")
        except Exception as exc:
            logger.exception("MeshCore set_name failed")
            await post_command()
            return SendResult(success=False, error=str(exc))

        if result is None:
            return fail_timeout("set_name timed out")

        if result.type == EventType.ERROR:
            payload = getattr(result, "payload", None)
            detail = ""
            if isinstance(payload, dict):
                detail = str(
                    payload.get("reason")
                    or payload.get("error")
                    or payload
                )
            elif payload is not None:
                detail = str(payload)
            error = (
                f"Companion rejected name: {detail}"
                if detail
                else "Companion rejected name"
            )
            await post_command()
            return SendResult(success=False, error=error)

        try:
            cache = getattr(mc, "self_info", None)
            if isinstance(cache, dict):
                cache["name"] = cleaned
        except Exception:
            logger.debug(
                "set_companion_name: could not update self_info cache; "
                "dashboard will lag by one reconnect cycle",
                exc_info=True,
            )

        event_type = (
            result.type.value
            if hasattr(result.type, "value")
            else str(result.type)
        )
        logger.info(
            "MeshCore companion renamed to %r (%s)", cleaned, event_type
        )
        await post_command()
        return SendResult(success=True, event_type=event_type)
