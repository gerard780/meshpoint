// Real widget test for NodeCard + NodeDetailSheet -- constructs a
// NodeSummary directly (no server/network involved) and checks the
// card renders its chips, and that tapping it actually opens the
// detail popup with the right sections, not just that the code
// compiles.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import 'package:meshpoint_app/models/node_summary.dart';
import 'package:meshpoint_app/services/theme_store.dart';
import 'package:meshpoint_app/widgets/node_card.dart';
import 'package:meshpoint_app/widgets/node_detail_sheet.dart';

NodeSummary _sampleNode() => NodeSummary.fromJson({
      'node_id': '!deadbeef',
      'display_name': 'Ridge Repeater',
      'short_name': 'RIDG',
      'hardware_model': '9', // RAK4631
      'firmware_version': '2.5.1',
      'protocol': 'meshtastic',
      'role': '4', // REPEATER
      'first_seen': DateTime.now().toUtc().subtract(const Duration(days: 30)).toIso8601String(),
      'last_heard': DateTime.now().toUtc().subtract(const Duration(minutes: 2)).toIso8601String(),
      'packet_count': 812,
      'has_position': true,
      'latitude': 51.05,
      'longitude': 3.72,
      'altitude': 42.0,
      'latest_rssi': -72.0,
      'latest_snr': 6.5,
      'latest_hops': 1,
      'latest_capture_source': 'serial_868',
      'latest_battery': 87.0,
      'latest_voltage': 4.05,
      'latest_temperature': 68.0,
      'latest_humidity': 55.0,
      'latest_channel_util': 3.2,
      'latest_air_util': 1.1,
    });

// ThemeStore must wrap MaterialApp itself, not just its `home` content --
// matching lib/main.dart's real provider placement. showModalBottomSheet
// inserts into the Navigator's Overlay, which is a sibling of `home`'s
// subtree, not a descendant of it -- a provider placed only around
// `home` (as an earlier version of this test did) is invisible to that
// overlay and throws ProviderNotFoundException the moment the sheet
// tries to read ThemeStore, a real placement constraint this test
// deliberately exercises rather than works around.
Widget _wrap(Widget child) {
  return ChangeNotifierProvider(
    create: (_) => ThemeStore(),
    child: MaterialApp(home: Scaffold(body: child)),
  );
}

void main() {
  testWidgets('NodeCard shows identity, protocol badge, and signal/telemetry chips', (tester) async {
    final node = _sampleNode();
    await tester.pumpWidget(_wrap(NodeCard(node: node, onTap: () {})));

    expect(find.text('Ridge Repeater'), findsOneWidget);
    expect(find.text('MT'), findsOneWidget);
    expect(find.text('-72 dBm'), findsOneWidget);
    expect(find.text('EXCELLENT'), findsOneWidget);
    expect(find.text('87%'), findsOneWidget);
    expect(find.text('RAK4631'), findsOneWidget);
    expect(find.text('REPEATER'), findsOneWidget);
  });

  testWidgets('Tapping a NodeCard opens NodeDetailSheet with the right info', (tester) async {
    final node = _sampleNode();
    await tester.pumpWidget(_wrap(
      Builder(
        builder: (context) => NodeCard(node: node, onTap: () => showNodeDetailSheet(context, node)),
      ),
    ));

    expect(find.byType(NodeDetailSheet), findsNothing);

    await tester.tap(find.byType(NodeCard));
    await tester.pumpAndSettle();

    expect(find.byType(NodeDetailSheet), findsOneWidget);
    // "Ridge Repeater"/"868 MHz"/"!deadbeef" legitimately appear twice --
    // once on the NodeCard still mounted behind the sheet, once inside
    // the sheet itself -- so those are findsWidgets, not findsOneWidget.
    expect(find.text('Ridge Repeater'), findsWidgets);
    expect(find.text('RSSI'), findsOneWidget);
    expect(find.text('-72.0 dBm'), findsOneWidget);
    expect(find.text('868 MHz'), findsWidgets);
    expect(find.text('!deadbeef'), findsWidgets);
  });
}
