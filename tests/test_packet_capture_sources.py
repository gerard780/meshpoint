"""Receive-interface lookups for deduplicated message packets."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, Mock

from src.storage.packet_repository import PacketRepository


class TestPacketCaptureSources(unittest.IsolatedAsyncioTestCase):
    async def test_returns_distinct_interfaces_in_first_seen_order(self):
        db = Mock()
        db.fetch_all = AsyncMock(return_value=[
            {
                "packet_id": "01020304",
                "protocol": "meshtastic",
                "capture_source": "concentrator",
                "first_seen": "2026-08-28T12:00:00+00:00",
            },
            {
                "packet_id": "01020304",
                "protocol": "meshtastic",
                "capture_source": "serial_433",
                "first_seen": "2026-08-28T12:00:01+00:00",
            },
            # The SQL intentionally uses the cross-product of packet IDs
            # and protocols to stay batched. The repository filters any
            # cross-product row that was not in the requested tuple set.
            {
                "packet_id": "missing",
                "protocol": "meshcore",
                "capture_source": "meshcore_usb",
                "first_seen": "2026-08-28T12:00:02+00:00",
            },
        ])
        repo = PacketRepository(db)

        sources = await repo.get_capture_sources(
            "01020304", "meshtastic"
        )
        batch = await repo.get_capture_sources_by_packet_ids([
            ("01020304", "meshtastic"),
            ("missing", "meshtastic"),
        ])

        self.assertEqual(sources, ["concentrator", "serial_433"])
        self.assertEqual(
            batch,
            {("01020304", "meshtastic"): ["concentrator", "serial_433"]},
        )


if __name__ == "__main__":
    unittest.main()
