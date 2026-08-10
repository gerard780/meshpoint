"""Query MeshCore companion DEVICE_INFO (firmware version / model)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class MeshcoreDeviceInfoQuery:
    """Fetch and normalize ``send_device_query`` / DEVICE_INFO under the cmd lock."""

    async def run(
        self,
        *,
        mc,
        cmd_lock: Optional[asyncio.Lock],
        connected: bool,
        timeout_seconds: float = 10.0,
    ) -> Optional[dict[str, Any]]:
        if not connected or mc is None:
            return None

        try:
            from meshcore import EventType
        except Exception:
            logger.warning("meshcore library unavailable for device query")
            return None

        try:
            if cmd_lock is None:
                result = await asyncio.wait_for(
                    mc.commands.send_device_query(),
                    timeout=timeout_seconds,
                )
            else:
                async with cmd_lock:
                    if mc is None:
                        return None
                    result = await asyncio.wait_for(
                        mc.commands.send_device_query(),
                        timeout=timeout_seconds,
                    )
        except asyncio.TimeoutError:
            logger.warning("MeshCore send_device_query timed out")
            return None
        except Exception:
            logger.exception("MeshCore send_device_query failed")
            return None

        if result is None or result.type == EventType.ERROR:
            return None

        payload = getattr(result, "payload", None)
        if not isinstance(payload, dict):
            return None
        return self.normalize(payload)

    @staticmethod
    def normalize(payload: dict) -> dict[str, Any]:
        """Map meshcore reader keys to a stable dashboard shape."""
        version = str(payload.get("ver") or "").strip()
        model = str(payload.get("model") or "").strip()
        build = str(payload.get("fw_build") or "").strip()
        return {
            "version": version,
            "model": model,
            "build": build,
            "fw_protocol": payload.get("fw ver"),
        }
