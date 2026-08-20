"""Tests for lorawan_payload_formats.py's declarative field decode."""

from __future__ import annotations

import unittest

from src.decode.lorawan_payload_formats import decode_payload


class TestDecodePayload(unittest.TestCase):

    def test_single_scaled_int16_field(self):
        """0E56 -> 3670 -> 36.7 C, scale=0.01. Real value from a live
        device capture on 2026-08-20, cross-checked against this
        project's own TTN payload formatter script -- see project memory."""
        fields = [{"name": "temperature_c", "type": "int16_be", "scale": 0.01}]

        result = decode_payload(fields, bytes.fromhex("0E56"))

        self.assertEqual(result, {"temperature_c": 36.7})

    def test_negative_value(self):
        fields = [{"name": "temperature_c", "type": "int16_be", "scale": 0.01}]
        # -1.00 C -> raw = -100 = 0xFF9C two's complement
        result = decode_payload(fields, bytes.fromhex("FF9C"))

        self.assertEqual(result["temperature_c"], -1.0)

    def test_unscaled_field_defaults_to_raw_integer(self):
        fields = [{"name": "count", "type": "uint8"}]
        result = decode_payload(fields, bytes([42]))

        self.assertEqual(result, {"count": 42})

    def test_multiple_fields_sequential_offsets(self):
        """No offset given -- each field defaults to right after the
        previous one (byte-size-aware), not always byte 0."""
        fields = [
            {"name": "battery_v", "type": "uint8", "scale": 0.1},
            {"name": "temperature_c", "type": "int16_be", "scale": 0.01},
        ]
        payload = bytes([33]) + bytes.fromhex("0E56")  # battery=3.3V, temp=36.7C

        result = decode_payload(fields, payload)

        self.assertEqual(result, {"battery_v": 3.3, "temperature_c": 36.7})

    def test_explicit_offset_overrides_sequential(self):
        fields = [{"name": "temperature_c", "type": "int16_be", "offset": 2, "scale": 0.01}]
        payload = bytes([0xFF, 0xFF]) + bytes.fromhex("0E56")

        result = decode_payload(fields, payload)

        self.assertEqual(result, {"temperature_c": 36.7})

    def test_field_past_end_of_payload_is_skipped_not_fatal(self):
        fields = [
            {"name": "a", "type": "uint8"},
            {"name": "b", "type": "int16_be"},  # payload too short for this one
        ]
        result = decode_payload(fields, bytes([1]))

        self.assertEqual(result, {"a": 1})

    def test_unknown_type_is_skipped(self):
        fields = [{"name": "x", "type": "not_a_real_type"}]
        result = decode_payload(fields, bytes([1, 2, 3, 4]))

        self.assertEqual(result, {})

    def test_missing_name_is_skipped(self):
        fields = [{"type": "uint8"}]
        result = decode_payload(fields, bytes([42]))

        self.assertEqual(result, {})

    def test_empty_field_list(self):
        self.assertEqual(decode_payload([], bytes([1, 2, 3])), {})


if __name__ == "__main__":
    unittest.main()
