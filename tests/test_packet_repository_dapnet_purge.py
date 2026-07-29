"""PacketRepository.delete_dapnet_capcodes -- real in-memory DB round trip.

Same harness as test_node_metrics_history.py (aiosqlite in-memory DB),
so CI-only, not runnable on the Mac dev machine (no aiosqlite there).
"""

import unittest
from datetime import datetime, timezone

from src.models.packet import Packet, PacketType, Protocol
from src.storage.database import DatabaseManager
from src.storage.packet_repository import PacketRepository


class TestDeleteDapnetCapcodes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = DatabaseManager(":memory:")
        await self.db.connect()
        self.repo = PacketRepository(self.db)

    async def asyncTearDown(self):
        await self.db.disconnect()

    async def _insert_dapnet(self, capcode: str):
        await self.repo.insert(Packet(
            packet_id=f"pkt-{capcode}",
            source_id=capcode,
            destination_id="broadcast",
            protocol=Protocol.DAPNET,
            packet_type=PacketType.DAPNET_ALPHA,
            timestamp=datetime.now(timezone.utc),
        ))

    async def test_deletes_only_matching_capcodes(self):
        await self._insert_dapnet("4512")
        await self._insert_dapnet("4520")
        await self._insert_dapnet("9999")

        removed = await self.repo.delete_dapnet_capcodes([4512, 4520])

        self.assertEqual(removed, 2)
        remaining = await self.repo.get_recent(limit=10)
        remaining_ids = {p.source_id for p in remaining}
        self.assertEqual(remaining_ids, {"9999"})

    async def test_does_not_touch_other_protocols_with_same_source_id(self):
        await self.repo.insert(Packet(
            packet_id="mt-pkt",
            source_id="4512",
            destination_id="broadcast",
            protocol=Protocol.MESHTASTIC,
            packet_type=PacketType.TEXT,
            timestamp=datetime.now(timezone.utc),
        ))
        await self._insert_dapnet("4512")

        removed = await self.repo.delete_dapnet_capcodes([4512])

        self.assertEqual(removed, 1)
        remaining = await self.repo.get_recent(limit=10)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].protocol, Protocol.MESHTASTIC)

    async def test_empty_capcode_list_is_a_noop(self):
        await self._insert_dapnet("4512")
        removed = await self.repo.delete_dapnet_capcodes([])
        self.assertEqual(removed, 0)
        remaining = await self.repo.get_recent(limit=10)
        self.assertEqual(len(remaining), 1)


if __name__ == "__main__":
    unittest.main()
