"""REGION_PRESETS MeshCore community radio presets.

Credit: javastraat/meshpoint f912d6c
"""

from __future__ import annotations

import unittest

from src.cli.meshcore_radio_command import PRESET_CHOICES, _resolve_region
from src.cli.meshcore_radio_config import REGION_PRESETS


class RegionPresetsTest(unittest.TestCase):
    def test_has_all_twenty_community_presets(self):
        self.assertEqual(len(REGION_PRESETS), 20)

    def test_eu_433_pair_present(self):
        long_range = REGION_PRESETS["EU_433_LONG_RANGE"]
        narrow = REGION_PRESETS["EU_433_NARROW"]
        self.assertEqual(
            (
                long_range.frequency_mhz,
                long_range.bandwidth_khz,
                long_range.spreading_factor,
                long_range.coding_rate,
            ),
            (433.650, 250.0, 11, 5),
        )
        self.assertEqual(
            (
                narrow.frequency_mhz,
                narrow.bandwidth_khz,
                narrow.spreading_factor,
                narrow.coding_rate,
            ),
            (433.650, 62.5, 8, 8),
        )

    def test_every_preset_has_plausible_lora_params(self):
        for key, preset in REGION_PRESETS.items():
            with self.subTest(key=key):
                self.assertTrue(100.0 <= preset.frequency_mhz <= 1000.0)
                self.assertIn(preset.bandwidth_khz, (62.5, 125.0, 250.0))
                self.assertTrue(5 <= preset.spreading_factor <= 12)
                self.assertTrue(5 <= preset.coding_rate <= 8)


class ResolveRegionTest(unittest.TestCase):
    def test_legacy_short_aliases(self):
        self.assertEqual(_resolve_region("US"), "USA_CANADA")
        self.assertEqual(_resolve_region("EU"), "EU_UK_NARROW")
        self.assertEqual(_resolve_region("ANZ"), "AUSTRALIA_NARROW")
        self.assertEqual(REGION_PRESETS["USA_CANADA"].frequency_mhz, 910.525)
        self.assertEqual(REGION_PRESETS["EU_UK_NARROW"].frequency_mhz, 869.618)
        self.assertEqual(REGION_PRESETS["AUSTRALIA_NARROW"].frequency_mhz, 916.575)

    def test_eu_868_alias(self):
        self.assertEqual(_resolve_region("EU_868"), "EU_UK_NARROW")

    def test_full_preset_key_case_insensitive(self):
        self.assertEqual(_resolve_region("eu_433_narrow"), "EU_433_NARROW")

    def test_custom_resolves(self):
        self.assertEqual(_resolve_region("CUSTOM"), "custom")
        self.assertEqual(_resolve_region("custom"), "custom")

    def test_unknown_region_exits(self):
        with self.assertRaises(SystemExit):
            _resolve_region("NOT_A_REAL_REGION")

    def test_preset_choices_includes_every_key_plus_custom(self):
        self.assertEqual(
            set(PRESET_CHOICES), set(REGION_PRESETS.keys()) | {"custom"}
        )


if __name__ == "__main__":
    unittest.main()
