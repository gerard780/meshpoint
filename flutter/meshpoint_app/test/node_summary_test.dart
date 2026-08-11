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
}
