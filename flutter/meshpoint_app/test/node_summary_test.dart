// Real unit test for NodeSummary.withLivePacket() -- the patch applied
// to a node's list entry on every live `/ws` packet
// (server_dashboard_screen.dart's _applyLivePacketToNodes) so the Nodes
// tab updates immediately instead of only on the next pull-to-refresh
// or screen re-entry (a real bug: it was doing exactly that before this
// method existed).

import 'package:flutter_test/flutter_test.dart';
import 'package:meshpoint_app/models/node_summary.dart';

NodeSummary _sampleNode() => NodeSummary.fromJson({
      'node_id': '!deadbeef',
      'display_name': 'Ridge Repeater',
      'protocol': 'meshtastic',
      'hardware_model': '9',
      'packet_count': 10,
      'has_position': false,
      'last_heard': DateTime.now().toUtc().subtract(const Duration(hours: 1)).toIso8601String(),
      'latest_rssi': -95.0,
      'latest_snr': 2.0,
    });

void main() {
  test('withLivePacket updates lastHeard/rssi/snr and bumps packetCount, keeps everything else', () {
    final original = _sampleNode();
    final heardAt = DateTime.now().toUtc();

    final updated = original.withLivePacket(heardAt: heardAt, rssi: -68.0, snr: 8.5);

    expect(updated.lastHeard, heardAt);
    expect(updated.rssi, -68.0);
    expect(updated.snr, 8.5);
    expect(updated.packetCount, original.packetCount + 1);

    // Everything a bare packet doesn't carry (hardware, name, protocol,
    // position) must survive untouched -- this only patches signal/timing.
    expect(updated.nodeId, original.nodeId);
    expect(updated.displayName, original.displayName);
    expect(updated.hardwareModel, original.hardwareModel);
    expect(updated.protocol, original.protocol);
  });

  test('withLivePacket keeps the prior rssi/snr when the packet carries none', () {
    final original = _sampleNode();
    final heardAt = DateTime.now().toUtc();

    // A packet with no signal block (e.g. relayed via MQTT) shouldn't
    // blank out a still-good last-known RSSI/SNR reading.
    final updated = original.withLivePacket(heardAt: heardAt);

    expect(updated.lastHeard, heardAt);
    expect(updated.rssi, original.rssi);
    expect(updated.snr, original.snr);
  });

  group('bandLabel', () {
    NodeSummary withCaptureSource(String? src) => NodeSummary.fromJson({
          'node_id': '!deadbeef',
          'protocol': 'meshtastic',
          'packet_count': 0,
          'has_position': false,
          'latest_capture_source': src,
        });

    test('labelled serial/meshcore_usb suffixes are trusted (deployer-set, not guessed)', () {
      expect(withCaptureSource('serial_433').bandLabel, '433 MHz');
      expect(withCaptureSource('serial_868').bandLabel, '868 MHz');
      expect(withCaptureSource('meshcore_usb_868').bandLabel, '868 MHz');
    });

    test('a bare "concentrator" source shows no band, not a guessed one', () {
      // Real bug report: a US tester (915 MHz) saw every node labelled
      // "868 MHz" because concentrator_source.py stamps the exact same
      // "concentrator" capture_source string regardless of RF region --
      // it carries no band information at all, so guessing was wrong.
      expect(withCaptureSource('concentrator').bandLabel, isNull);
    });

    test('an unrecognized or missing capture source shows no band', () {
      expect(withCaptureSource('serial').bandLabel, isNull);
      expect(withCaptureSource(null).bandLabel, isNull);
    });
  });
}
