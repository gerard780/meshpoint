"""Tests for PUT /api/config/dapnet.

Same harness style as test_serial_devices_route.py -- calls the route
handler directly with a fake PacketRepository (an async mock, not a
real DB) so this stays runnable without aiosqlite. Focus is the purge
behavior added alongside the capcode-list save: adding a capcode to
the ignore list should also delete any already-stored dapnet pages for
that capcode, not just block future ones (see
PacketRepository.delete_dapnet_capcodes's own docstring for why).
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI  # noqa: F401 -- import-time dependency probe

from src.api.audit import AuditLogWriter
from src.api.auth.jwt_session import SessionClaims
from src.api.routes import system_config_routes as routes
from src.config import AppConfig


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _FakePacketRepo:
    def __init__(self):
        self.calls: list[list[int]] = []
        self.next_result = 0

    async def delete_dapnet_capcodes(self, capcodes):
        self.calls.append(list(capcodes))
        return self.next_result


class UpdateDapnetTest(unittest.TestCase):
    def setUp(self):
        self.config = AppConfig()
        self.packet_repo = _FakePacketRepo()
        routes.init_routes(self.config, packet_repo=self.packet_repo)
        self.addCleanup(routes.reset_routes)

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.audit = AuditLogWriter(log_path=Path(self.tmp.name) / "audit.jsonl")
        self.claims = SessionClaims("test-admin", "admin", 1)

    def _put(self, blacklist, ignore):
        req = routes.DapnetUpdate(blacklist_capcodes=blacklist, ignore_capcodes=ignore)
        with mock.patch.object(routes, "save_section_to_yaml") as mock_save:
            result = _run(routes.update_dapnet(
                req, _claims=self.claims, audit=self.audit,
            ))
        return result, mock_save

    def test_saves_both_lists_to_config(self):
        self._put([200, 208], [4512, 4520])
        self.assertEqual(self.config.dapnet.blacklist_capcodes, [200, 208])
        self.assertEqual(self.config.dapnet.ignore_capcodes, [4512, 4520])

    def test_purges_stored_packets_for_newly_ignored_capcodes(self):
        self.packet_repo.next_result = 7
        result, _ = self._put([], [4512, 4520])
        self.assertEqual(self.packet_repo.calls, [[4512, 4520]])
        self.assertEqual(result["purged"], 7)

    def test_purges_stored_packets_for_newly_blacklisted_capcodes_too(self):
        # blacklist_capcodes also promise "never stored" -- a capcode just
        # added to blacklist has the same stale-history problem as ignore.
        self.packet_repo.next_result = 3
        result, _ = self._put([200], [])
        self.assertEqual(self.packet_repo.calls, [[200]])
        self.assertEqual(result["purged"], 3)

    def test_purges_the_union_of_both_lists_deduped(self):
        self._put([200, 4512], [4512, 4520])
        self.assertEqual(self.packet_repo.calls, [[200, 4512, 4520]])

    def test_both_lists_empty_does_not_call_purge(self):
        result, _ = self._put([], [])
        self.assertEqual(self.packet_repo.calls, [])
        self.assertEqual(result["purged"], 0)

    def test_no_packet_repo_wired_skips_purge_without_error(self):
        routes.init_routes(self.config, packet_repo=None)
        result, _ = self._put([], [4512])
        self.assertEqual(result["saved"], True)
        self.assertEqual(result["purged"], 0)

    def test_raises_503_when_config_not_loaded(self):
        routes.reset_routes()
        from fastapi import HTTPException
        req = routes.DapnetUpdate(blacklist_capcodes=[], ignore_capcodes=[])
        with self.assertRaises(HTTPException) as ctx:
            _run(routes.update_dapnet(
                req, _claims=self.claims, audit=self.audit,
            ))
        self.assertEqual(ctx.exception.status_code, 503)
        routes.init_routes(self.config, packet_repo=self.packet_repo)


if __name__ == "__main__":
    unittest.main()
