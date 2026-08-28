"""Messaging API coverage for TX selection and RX interface metadata."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, Mock

from src.api.routes import messages
from src.config import AppConfig
from src.transmit.tx_service import SendResult


class TestMessageTransmitSources(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._globals = {
            name: getattr(messages, name)
            for name in (
                "_tx_service",
                "_message_repo",
                "_meshcore_tx",
                "_config",
                "_name_resolver",
                "_packet_repo",
            )
        }

    def tearDown(self) -> None:
        for name, value in self._globals.items():
            setattr(messages, name, value)

    async def test_send_forwards_selected_physical_source(self):
        tx = Mock()
        tx.send_text = AsyncMock(return_value=SendResult(
            success=True,
            packet_id="01020304",
            protocol="meshtastic",
        ))
        repo = Mock()
        repo.save_sent = AsyncMock()
        messages._tx_service = tx
        messages._message_repo = repo
        messages._name_resolver = None

        result = await messages.send_message(
            messages.SendRequest(
                text="hello",
                destination="broadcast",
                protocol="meshtastic",
                channel=0,
                tx_source="serial_433",
            ),
            _claims=None,
        )

        self.assertTrue(result["success"])
        tx.send_text.assert_awaited_once_with(
            text="hello",
            destination="broadcast",
            protocol="meshtastic",
            channel=0,
            want_ack=False,
            echo_hash=None,
            tx_source="serial_433",
        )

    async def test_channels_include_compatible_transmitters(self):
        config = AppConfig()
        config.meshtastic.primary_channel_name = "Home"
        config.meshtastic.channel_keys = {"Public": "AQ=="}
        tx = Mock()
        tx.get_meshtastic_tx_sources.side_effect = [
            [
                {
                    "id": "concentrator",
                    "label": "Concentrator",
                    "kind": "concentrator",
                },
                {
                    "id": "serial_433",
                    "label": "USB 433",
                    "kind": "usb",
                    "radio_channel": 1,
                },
            ],
            [{"id": "serial_433", "label": "USB 433", "kind": "usb"}],
        ]
        messages._config = config
        messages._tx_service = tx
        messages._meshcore_tx = None

        channels = await messages.get_channels(claims=None)

        self.assertEqual(channels[0]["default_tx_source"], "concentrator")
        self.assertEqual(channels[0]["tx_sources"][1]["radio_channel"], 1)
        self.assertEqual(channels[1]["default_tx_source"], "serial_433")
        tx.get_meshtastic_tx_sources.assert_any_call(0)
        tx.get_meshtastic_tx_sources.assert_any_call(1)

    async def test_message_history_is_enriched_with_receive_interfaces(self):
        packet_repo = Mock()
        packet_repo.get_capture_sources_by_packet_ids = AsyncMock(return_value={
            ("01020304", "meshtastic"): ["concentrator", "serial_433"],
        })
        messages._name_resolver = None
        messages._packet_repo = packet_repo

        result = await messages._enrich_messages([{
            "packet_id": "01020304",
            "protocol": "meshtastic",
            "text": "hello",
        }])

        self.assertEqual(
            result[0]["rx_sources"],
            ["concentrator", "serial_433"],
        )


if __name__ == "__main__":
    unittest.main()
