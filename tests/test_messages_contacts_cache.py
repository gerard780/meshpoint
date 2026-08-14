"""GET /api/messages/contacts must not hit the live MeshCore USB bus on
every call -- a short cache bounds it to ~1 round trip per picker-open."""

from __future__ import annotations

import asyncio
import unittest

from src.api.routes import messages


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _FakeMeshcoreTx:
    connected = True

    def __init__(self):
        self.call_count = 0

    async def get_contacts(self):
        self.call_count += 1
        return [{"public_key": "ab" * 10, "name": "Contact"}]


class TestContactsCache(unittest.TestCase):
    def setUp(self):
        # Reset module-level cache state between tests -- these are
        # process-global in messages.py, same as the real server.
        messages._contacts_cache = []
        messages._contacts_cache_at = 0.0
        self._orig_tx = messages._meshcore_tx
        messages._meshcore_tx = _FakeMeshcoreTx()

    def tearDown(self):
        messages._meshcore_tx = self._orig_tx

    def test_repeated_calls_within_ttl_hit_the_bus_once(self):
        _run(messages._cached_meshcore_contacts())
        _run(messages._cached_meshcore_contacts())
        _run(messages._cached_meshcore_contacts())
        self.assertEqual(messages._meshcore_tx.call_count, 1)

    def test_cache_expires_and_refetches(self):
        _run(messages._cached_meshcore_contacts())
        messages._contacts_cache_at -= messages._CONTACTS_CACHE_TTL_S + 1
        _run(messages._cached_meshcore_contacts())
        self.assertEqual(messages._meshcore_tx.call_count, 2)


if __name__ == "__main__":
    unittest.main()
