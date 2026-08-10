"""MeshCore message transmission via USB or TCP companion.

Wraps the meshcore Python library for outbound messaging. Shares
the existing MeshCore connection from MeshcoreUsbCaptureSource
to avoid opening a second serial connection to the same port.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from src.transmit.meshcore_channel_sync import MeshcoreChannelSync

logger = logging.getLogger(__name__)

# Companion firmware caps the advert name at roughly 32 ASCII bytes; the
# exact ceiling varies with location/unicode payload per MeshCore docs.
# We enforce 32 UTF-8 bytes as a conservative upper bound that fits every
# documented variant.
MAX_COMPANION_NAME_BYTES = 32


@dataclass
class SendResult:
    """Outcome of a MeshCore send attempt.

    ``timed_out`` is distinct from a plain ``success=False``: a firmware
    ERROR means the connection is healthy and rejected the request. A
    timeout means no answer within the deadline (wedged command channel).
    Callers / TxClient use this to trigger an immediate reconnect.
    Credit: javastraat/meshpoint b04e91c
    """

    success: bool
    event_type: str = ""
    error: str = ""
    timed_out: bool = False


@dataclass
class RadioStatus:
    """MeshCore companion radio parameters."""

    frequency_mhz: float = 0.0
    bandwidth_khz: float = 0.0
    spreading_factor: int = 0
    coding_rate: int = 0
    tx_power: int = 0
    name: str = ""


class MeshCoreTxClient:
    """Sends messages through a MeshCore companion node.

    Designed to share the MeshCore connection already held by
    MeshcoreUsbCaptureSource. Use set_source() so the client always
    reads the source's *current* MeshCore instance: the capture source
    rebuilds it on every reconnect, and snapshotting the reference
    once at startup leaves the TX client stuck on a dead handle.
    """

    def __init__(self):
        self._owned_mc = None
        self._owned_connected = False
        self._source = None
        self._post_command_callback = None

    @property
    def _mc(self):
        """Live MeshCore handle. Prefers the shared source if attached."""
        if self._source is not None:
            return getattr(self._source, "_meshcore", None)
        return self._owned_mc

    @property
    def connected(self) -> bool:
        if self._source is not None:
            return (
                bool(getattr(self._source, "_connected", False))
                and self._mc is not None
            )
        return self._owned_connected and self._owned_mc is not None

    def set_source(self, source) -> None:
        """Attach the capture source so we always see live connect state."""
        self._source = source
        logger.info("MeshCore TX client bound to live capture source")

    def set_connection(self, mc_instance) -> None:
        """Legacy one-shot attach. Prefer set_source() for live state."""
        self._source = None
        self._owned_mc = mc_instance
        self._owned_connected = mc_instance is not None
        if self._owned_connected:
            logger.info("MeshCore TX client attached to shared connection")

    def set_post_command_callback(self, callback) -> None:
        """Register a coroutine to run after each command completes.

        Used to restart auto_message_fetching on the USB source after
        TX operations that may disrupt the event subscription loop.
        """
        self._post_command_callback = callback

    async def _run_post_command(self) -> None:
        if self._post_command_callback:
            try:
                await self._post_command_callback()
            except Exception:
                logger.debug("Post-command callback failed", exc_info=True)

    def _fail_timeout(self, reason: str) -> SendResult:
        """Mark timeout and kick MeshCore USB reconnect if bound.

        Credit: javastraat/meshpoint b04e91c
        """
        trigger = getattr(self._source, "_trigger_reconnect", None)
        if callable(trigger):
            trigger(reason)
        return SendResult(success=False, error=reason, timed_out=True)

    async def create_connection(
        self,
        port: str,
        baud_rate: int = 115200,
        connection_type: str = "serial",
        tcp_host: str = "",
        tcp_port: int = 0,
    ) -> bool:
        """Create a standalone connection (only if no shared one exists)."""
        if self.connected:
            return True
        try:
            from meshcore import MeshCore

            if connection_type == "tcp" and tcp_host:
                self._owned_mc = await MeshCore.create_tcp(tcp_host, tcp_port)
            else:
                self._owned_mc = await MeshCore.create_serial(port, baud_rate)
            if self._owned_mc is None:
                logger.error(
                    "MeshCore TX client handshake failed on %s "
                    "(meshcore returned None)",
                    port,
                )
                self._owned_connected = False
                return False
            self._source = None
            self._owned_connected = True
            logger.info("MeshCore TX client connected (%s)", connection_type)
            return True
        except Exception:
            logger.exception("MeshCore TX client connection failed")
            self._owned_connected = False
            return False

    async def send_channel_message(
        self, channel: int, text: str
    ) -> SendResult:
        """Send a broadcast message on a MeshCore channel."""
        if not self.connected:
            return SendResult(success=False, error="Not connected")
        try:
            result = await asyncio.wait_for(
                self._mc.commands.send_chan_msg(channel, text),
                timeout=10.0,
            )
            event_type = (
                result.type.value
                if hasattr(result.type, "value")
                else str(result.type)
            )
            logger.info(
                "MeshCore channel %d message sent: %s", channel, event_type
            )
            await self._run_post_command()
            return SendResult(success=True, event_type=event_type)
        except asyncio.TimeoutError:
            return self._fail_timeout("Send timed out")
        except Exception as exc:
            logger.exception("MeshCore channel send failed")
            await self._run_post_command()
            return SendResult(success=False, error=str(exc))

    async def send_direct_message(
        self, destination, text: str
    ) -> SendResult:
        """Send a direct message to a MeshCore contact."""
        if not self.connected:
            return SendResult(success=False, error="Not connected")
        try:
            result = await asyncio.wait_for(
                self._mc.commands.send_msg(destination, text),
                timeout=10.0,
            )
            event_type = (
                result.type.value
                if hasattr(result.type, "value")
                else str(result.type)
            )
            logger.info("MeshCore DM sent: %s", event_type)
            await self._run_post_command()
            return SendResult(success=True, event_type=event_type)
        except asyncio.TimeoutError:
            return self._fail_timeout("Send timed out")
        except Exception as exc:
            logger.exception("MeshCore DM send failed")
            await self._run_post_command()
            return SendResult(success=False, error=str(exc))

    async def send_advert(self, flood: bool = False) -> SendResult:
        """Broadcast a node advertisement."""
        if not self.connected:
            return SendResult(success=False, error="Not connected")
        try:
            result = await asyncio.wait_for(
                self._mc.commands.send_advert(flood=flood),
                timeout=10.0,
            )
            event_type = (
                result.type.value
                if hasattr(result.type, "value")
                else str(result.type)
            )
            logger.info("MeshCore advert sent: %s", event_type)
            await self._run_post_command()
            return SendResult(success=True, event_type=event_type)
        except asyncio.TimeoutError:
            return self._fail_timeout("Advert timed out")
        except Exception as exc:
            logger.exception("MeshCore advert send failed")
            await self._run_post_command()
            return SendResult(success=False, error=str(exc))

    async def set_companion_name(self, name: str) -> SendResult:
        """Rename the USB companion via CMD_SET_ADVERT_NAME (0x08).

        On OK we mutate the cached ``self_info["name"]`` so the
        Configuration card, top-bar chip, and packet attribution all
        reflect the rename without waiting for the next reconnect.
        ``set_name`` itself only returns OK/ERROR; it does not emit a
        fresh SELF_INFO, and meshcore 2.3.x exposes no public method to
        re-poll the device (``self_info`` is seeded once during the
        ``connect`` handshake's appstart and never auto-refreshed).
        Updating the dict locally is safe because the firmware just
        acknowledged the new name via ``command_ok``; the next
        reconnect will reseed ``self_info`` from the device anyway.

        Validation lives here so route handlers, future CLI callers,
        and the ``meshcore.companion_name`` yaml-on-connect path all
        use the same ceiling.
        """
        if not self.connected:
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
            return SendResult(success=False, error="meshcore library unavailable")

        try:
            result = await asyncio.wait_for(
                self._mc.commands.set_name(cleaned),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            return self._fail_timeout("set_name timed out")
        except Exception as exc:
            logger.exception("MeshCore set_name failed")
            await self._run_post_command()
            return SendResult(success=False, error=str(exc))

        if result.type == EventType.ERROR:
            payload = getattr(result, "payload", None)
            detail = ""
            if isinstance(payload, dict):
                detail = str(payload.get("reason") or payload.get("error") or payload)
            elif payload is not None:
                detail = str(payload)
            error = f"Companion rejected name: {detail}" if detail else "Companion rejected name"
            await self._run_post_command()
            return SendResult(success=False, error=error)

        # OK path: refresh self_info so callers see the new name immediately.
        # The meshcore library does not expose a method to re-poll the
        # device's identity (self_info is seeded once during connect's
        # appstart handshake and never automatically refreshed). Since
        # the firmware just acknowledged the rename via command_ok, we
        # know the new name is what the device holds: mutate the cached
        # dict directly so /api/config -> get_radio_info() returns the
        # new value on the next dashboard refresh. The next reconnect
        # will reseed self_info from the device anyway.
        try:
            cache = getattr(self._mc, "self_info", None)
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
        logger.info("MeshCore companion renamed to %r (%s)", cleaned, event_type)
        await self._run_post_command()
        return SendResult(success=True, event_type=event_type)

    async def set_radio_params(
        self,
        freq: float,
        bw: float,
        sf: int,
        cr: int,
    ) -> SendResult:
        """Set companion radio params over the live USB connection, then reboot.

        On success or timeout, kick reconnect so the capture source
        recovers the companion after reboot / wedge.
        Credit: javastraat/meshpoint 471d572
        """
        if not self.connected:
            return SendResult(success=False, error="Not connected")

        from src.transmit.meshcore_radio_apply import MeshcoreRadioApply

        result = await MeshcoreRadioApply().apply(self._mc, freq, bw, sf, cr)
        if result.timed_out:
            return self._fail_timeout(result.error or "set_radio timed out")
        if result.success:
            trigger = getattr(self._source, "_trigger_reconnect", None)
            if callable(trigger):
                trigger(
                    f"radio set to {freq:.3f} MHz / BW{bw:.1f} "
                    f"/ SF{sf} / CR{cr} -- rebooting"
                )
        return result

    @staticmethod
    def _normalize_contact_payload(payload) -> list[dict]:
        """Accept both dict-keyed-by-pubkey and list formats.

        Defensively filters values to dicts only. Some firmware
        revisions of the MeshCore companion return a payload like
        ``{"contact_count": 5, ...}`` where some values are ints
        and some are nested dicts; we only want the nested-dict
        contact entries. Non-dict values (ints, strings, lists)
        are silently dropped so a payload-shape change in the
        companion firmware can never crash get_contacts.
        """
        if isinstance(payload, dict):
            return [v for v in payload.values() if isinstance(v, dict)]
        if isinstance(payload, list):
            return [e for e in payload if isinstance(e, dict)]
        return []

    async def get_radio_info(self) -> Optional[RadioStatus]:
        """Read companion radio parameters from the cached SELF_INFO frame.

        SELF_INFO is captured during the handshake and is the authoritative
        source for radio_freq / radio_bw / radio_sf / radio_cr / tx_power /
        name. send_device_query() does not return those fields, so reading
        from there left the dashboard stuck on Unknown / ?.
        """
        if not self.connected:
            return None
        try:
            info = self._mc.self_info or {}
            if not info:
                return None
            return RadioStatus(
                frequency_mhz=float(info.get("radio_freq", 0.0)),
                bandwidth_khz=float(info.get("radio_bw", 0.0)),
                spreading_factor=int(info.get("radio_sf", 0)),
                coding_rate=int(info.get("radio_cr", 0)),
                tx_power=int(info.get("tx_power", 0)),
                name=info.get("name", ""),
            )
        except Exception:
            logger.exception("Failed to read MeshCore radio info")
            return None

    async def sync_channels(self, channel_keys: dict) -> None:
        """Sync configured channels to the companion device."""
        if not self.connected:
            logger.debug("sync_channels: not connected, skipping")
            return
        await MeshcoreChannelSync(
            self._mc,
            post_command=self._run_post_command,
        ).sync(channel_keys)

    async def get_contacts(self) -> list[dict]:
        """Retrieve the companion's contact list.

        Each entry inside the response can shape-shift between
        firmware versions, so the per-entry parse is wrapped in
        a defensive isinstance check + try/except so one weird
        contact never poisons the whole list.
        """
        if not self.connected:
            return []
        try:
            result = await asyncio.wait_for(
                self._mc.commands.get_contacts(),
                timeout=10.0,
            )
            entries = self._normalize_contact_payload(result.payload)
        except Exception:
            logger.exception("Failed to retrieve MeshCore contacts")
            return []

        contacts: list[dict] = []
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            try:
                name = (
                    entry.get("adv_name")
                    or entry.get("name")
                    or ""
                )
                pk = entry.get("public_key", "")
                if name and pk:
                    contacts.append({
                        "index": i,
                        "name": name,
                        "public_key": pk,
                        "last_seen": entry.get("lastmod", 0),
                    })
            except Exception:
                logger.debug(
                    "get_contacts: skipping malformed entry at index %d",
                    i, exc_info=True,
                )
                continue
        logger.info("get_contacts: %d contacts parsed", len(contacts))
        return contacts
