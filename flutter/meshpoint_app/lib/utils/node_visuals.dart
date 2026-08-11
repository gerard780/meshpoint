import 'package:flutter/material.dart';

import '../theme/meshpoint_theme.dart';

/// Small shared helpers for rendering a [NodeSummary] consistently
/// between [NodeCard] and [NodeDetailSheet] -- ports of the same
/// tier-break logic `frontend/js/node_cards.js`/`node_drawer.js` use, so
/// an RSSI/battery value never reads a different color on the card than
/// it does in the detail sheet.
class SignalQuality {
  final String label;
  final Color color;
  const SignalQuality(this.label, this.color);
}

/// Tier breaks match `_signalQuality()` in `node_cards.js`/`node_drawer.js`.
SignalQuality signalQualityFor(double rssi, MeshpointPalette p) {
  if (rssi > -80) return SignalQuality('Excellent', p.accentGreen);
  if (rssi >= -100) return SignalQuality('Good', p.accentCyan);
  if (rssi >= -115) return SignalQuality('Fair', p.accentAmber);
  return SignalQuality('Poor', p.accentRed);
}

/// Matches `_signalBars()`'s 5-level breakpoints in `node_cards.js`.
int signalBarLevel(double rssi) {
  if (rssi > -80) return 5;
  if (rssi >= -100) return 4;
  if (rssi >= -115) return 3;
  if (rssi >= -125) return 2;
  return 1;
}

class BatteryTier {
  final IconData icon;
  final Color color;
  const BatteryTier(this.icon, this.color);
}

/// Matches `_batteryTier()` in `node_cards.js`.
BatteryTier batteryTierFor(double pct, MeshpointPalette p) {
  if (pct > 50) return BatteryTier(Icons.battery_full, p.accentGreen);
  if (pct > 25) return BatteryTier(Icons.battery_4_bar, p.accentAmber);
  return BatteryTier(Icons.battery_alert, p.accentRed);
}

/// Matches `_hashColor()` in `node_cards.js`/`node_drawer.js` -- same
/// hash so a node's avatar color is identical between the web dashboard
/// and this app when both look at the same node ID.
Color hashColorFor(String id) {
  var hash = 0;
  for (final unit in id.codeUnits) {
    hash = unit + ((hash << 5) - hash);
  }
  final hue = (hash.abs() % 360).toDouble();
  return HSLColor.fromAHSL(1.0, hue, 0.55, 0.45).toColor();
}
