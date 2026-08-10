"""Tests for MeshcoreContactParser (get_contacts soft-fail paths)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.transmit.meshcore_contacts import MeshcoreContactParser


class TestMeshcoreContactParser(unittest.TestCase):

    def test_none_result_returns_empty(self):
        self.assertEqual(
            MeshcoreContactParser.from_command_result(None),
            [],
        )

    def test_error_event_returns_empty(self):
        fake_event_type = MagicMock()
        fake_event_type.ERROR = "ERROR"
        result = SimpleNamespace(
            type=fake_event_type.ERROR,
            payload={"reason": "no_event_received"},
        )
        with patch.dict(
            "sys.modules",
            {"meshcore": MagicMock(EventType=fake_event_type)},
        ):
            # Re-import path uses meshcore inside _is_error_event
            with patch(
                "src.transmit.meshcore_contacts.MeshcoreContactParser."
                "_is_error_event",
                return_value=True,
            ):
                self.assertEqual(
                    MeshcoreContactParser.from_command_result(result),
                    [],
                )

    def test_valid_payload_parses_contacts(self):
        result = SimpleNamespace(
            payload={
                "aabb0011223344": {
                    "adv_name": "Alice",
                    "public_key": "aabb0011223344",
                    "lastmod": 9,
                },
            },
        )
        with patch(
            "src.transmit.meshcore_contacts.MeshcoreContactParser."
            "_is_error_event",
            return_value=False,
        ):
            contacts = MeshcoreContactParser.from_command_result(result)
        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0]["name"], "Alice")
        self.assertEqual(contacts[0]["public_key"], "aabb0011223344")
        self.assertEqual(contacts[0]["last_seen"], 9)

    def test_normalize_payload_dict_and_list(self):
        self.assertEqual(
            len(MeshcoreContactParser.normalize_payload({
                "k": {"adv_name": "A", "public_key": "aa"},
                "n": 1,
            })),
            1,
        )
        self.assertEqual(
            MeshcoreContactParser.normalize_payload(None),
            [],
        )


if __name__ == "__main__":
    unittest.main()
