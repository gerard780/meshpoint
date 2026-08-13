"""Filter self-originated non-text traffic from a Meshtastic USB stick."""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class SerialSelfOriginFilter:
    """Drops a USB stick's self-telemetry/nodeinfo; keeps its own text.

    meshtastic-python publishes the stick's locally originated beacons on
    the same ``meshtastic.receive`` topic as over-the-air packets. Those
    beacons have no real RF signal (firmware leaves rxRssi/rxSnr at 0),
    so the pipeline would otherwise store spammy -100 dBm readings.

    Text from a BLE/WiFi client on the same stick is exempt: it is real
    chat content and must reach Messages even though ``from`` is the
    stick's own node id.

    Credit: javastraat/meshpoint ``db4de9f`` + ``c190b3e``.
    """

    _TEXT_PORTNUMS = frozenset({"TEXT_MESSAGE_APP", 1})

    def __init__(self, own_node_num: Optional[int] = None) -> None:
        self._own_node_num = own_node_num

    @property
    def own_node_num(self) -> Optional[int]:
        return self._own_node_num

    def set_own_node_num(self, node_num: Optional[int]) -> None:
        self._own_node_num = node_num

    @staticmethod
    def read_own_node_num(interface) -> Optional[int]:
        """Best-effort read of ``interface.myInfo.my_node_num``."""
        try:
            return int(interface.myInfo.my_node_num)
        except Exception:
            logger.debug(
                "Could not read own node number from serial interface",
                exc_info=True,
            )
            return None

    def should_drop(self, packet: dict) -> bool:
        if self._own_node_num is None:
            return False
        if packet.get("from") != self._own_node_num:
            return False
        return not self._is_text_message(packet)

    @classmethod
    def _is_text_message(cls, packet: dict) -> bool:
        decoded = packet.get("decoded")
        if not isinstance(decoded, dict):
            return False
        return decoded.get("portnum") in cls._TEXT_PORTNUMS
