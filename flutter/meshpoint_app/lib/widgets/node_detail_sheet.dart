import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/node_summary.dart';
import '../services/theme_store.dart';
import '../theme/meshpoint_theme.dart';
import '../utils/hardware_names.dart';
import '../utils/node_visuals.dart';

/// Opens the node detail popup -- a draggable sheet (not a full route
/// push) so it reads as "more info about the card you just tapped"
/// rather than a full navigation away from the node list, matching how
/// `frontend/js/node_drawer.js`'s slide-out panel behaves relative to
/// the node list beside it. v1 scope: read-only info sections mirroring
/// `_buildInfoSection`/`_buildSignalSection`/`_buildDeviceMetrics`/
/// `_buildEnvironmentMetrics`/`_buildPositionSection` in node_drawer.js
/// -- the metrics-over-time chart and recent-packets list need their own
/// API calls this app doesn't make yet, left for a later pass.
Future<void> showNodeDetailSheet(BuildContext context, NodeSummary node) {
  return showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    builder: (_) => NodeDetailSheet(node: node),
  );
}

class NodeDetailSheet extends StatelessWidget {
  final NodeSummary node;
  const NodeDetailSheet({super.key, required this.node});

  @override
  Widget build(BuildContext context) {
    final palette = MeshpointPalette.forTheme(context.watch<ThemeStore>().current);

    return DraggableScrollableSheet(
      initialChildSize: 0.62,
      minChildSize: 0.4,
      maxChildSize: 0.94,
      expand: false,
      builder: (context, scrollController) {
        return Container(
          decoration: BoxDecoration(
            color: palette.bgCard,
            borderRadius: const BorderRadius.vertical(top: Radius.circular(16)),
          ),
          child: Column(
            children: [
              const SizedBox(height: 8),
              Container(
                width: 36,
                height: 4,
                decoration: BoxDecoration(
                  color: palette.border,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
              _Header(node: node, palette: palette),
              Divider(height: 1, color: palette.border),
              Expanded(
                child: ListView(
                  controller: scrollController,
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
                  children: [
                    _Section(title: 'Node info', palette: palette, rows: _infoRows(node)),
                    _Section(title: 'Signal', palette: palette, rows: _signalRows(node)),
                    _Section(title: 'Device metrics', palette: palette, rows: _deviceRows(node)),
                    _Section(title: 'Environment', palette: palette, rows: _envRows(node)),
                    _Section(title: 'Position', palette: palette, rows: _positionRows(node)),
                  ],
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  static List<(String, String)> _infoRows(NodeSummary n) {
    final rows = <(String, String)>[];
    if (n.hardwareModel != null) rows.add(('Hardware', hardwareNameFor(n.hardwareModel!)));
    if (n.roleLabel != null) rows.add(('Role', n.roleLabel!));
    rows.add(('Protocol', n.protocol.toUpperCase()));
    if (n.bandLabel != null) rows.add(('Band', n.bandLabel!));
    if (n.firmwareVersion != null) rows.add(('Firmware', n.firmwareVersion!));
    rows.add(('Node ID', '!${n.nodeId.replaceAll('!', '')}'));
    rows.add(('First seen', n.firstSeenLabel()));
    rows.add(('Last heard', n.lastHeardLabel()));
    if (n.packetCount > 0) rows.add(('Packets', '${n.packetCount}'));
    return rows;
  }

  static List<(String, String)> _signalRows(NodeSummary n) {
    final rows = <(String, String)>[];
    final rssi = n.rssi;
    if (rssi != null) {
      rows.add(('RSSI', '${rssi.toStringAsFixed(1)} dBm'));
      // Palette-dependent label/color pairing is card-only chrome; here
      // just the quality word, computed with a placeholder cyan palette
      // slot since the label text itself doesn't depend on the theme.
      rows.add(('Quality', _qualityLabel(rssi)));
    }
    if (n.snr != null) rows.add(('SNR', '${n.snr!.toStringAsFixed(1)} dB'));
    if (n.hops != null) rows.add(('Hops', '${n.hops}'));
    return rows;
  }

  static String _qualityLabel(double rssi) {
    if (rssi > -80) return 'Excellent';
    if (rssi >= -100) return 'Good';
    if (rssi >= -115) return 'Fair';
    return 'Poor';
  }

  static List<(String, String)> _deviceRows(NodeSummary n) {
    final rows = <(String, String)>[];
    if (n.voltage != null) rows.add(('Voltage', '${n.voltage!.toStringAsFixed(2)} V'));
    if (n.battery == 101) {
      rows.add(('Battery', 'Powered (no battery)'));
    } else if ((n.battery ?? 0) > 0) {
      rows.add(('Battery', '${n.battery!.toStringAsFixed(0)}%'));
    }
    if (n.channelUtil != null) rows.add(('Channel util', '${n.channelUtil!.toStringAsFixed(1)}%'));
    if (n.airUtil != null) rows.add(('Air util TX', '${n.airUtil!.toStringAsFixed(1)}%'));
    return rows;
  }

  static List<(String, String)> _envRows(NodeSummary n) {
    final rows = <(String, String)>[];
    if (n.temperature != null) rows.add(('Temperature', '${n.temperature!.toStringAsFixed(1)}°F'));
    if (n.humidity != null) rows.add(('Humidity', '${n.humidity!.toStringAsFixed(0)}%'));
    return rows;
  }

  static List<(String, String)> _positionRows(NodeSummary n) {
    final rows = <(String, String)>[];
    if (n.latitude != null) rows.add(('Latitude', n.latitude!.toStringAsFixed(6)));
    if (n.longitude != null) rows.add(('Longitude', n.longitude!.toStringAsFixed(6)));
    if (n.altitude != null) rows.add(('Altitude', '${n.altitude!.round()} ft'));
    return rows;
  }
}

class _Header extends StatelessWidget {
  final NodeSummary node;
  final MeshpointPalette palette;
  const _Header({required this.node, required this.palette});

  @override
  Widget build(BuildContext context) {
    final initials =
        (node.shortName?.isNotEmpty == true ? node.shortName! : node.nodeId.replaceAll('!', ''))
            .toUpperCase();
    final shortLabel = initials.length > 4 ? initials.substring(initials.length - 4) : initials;

    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 8, 12),
      child: Row(
        children: [
          Container(
            width: 40,
            height: 40,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: hashColorFor(node.nodeId),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Text(
              shortLabel,
              style: const TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w700),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  node.displayName,
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: palette.textPrimary),
                  overflow: TextOverflow.ellipsis,
                ),
                Text(
                  '!${node.nodeId.replaceAll('!', '')}',
                  style: TextStyle(fontSize: 11.5, color: palette.textMuted, fontFamily: 'monospace'),
                ),
              ],
            ),
          ),
          IconButton(
            icon: const Icon(Icons.close),
            color: palette.textMuted,
            onPressed: () => Navigator.of(context).pop(),
          ),
        ],
      ),
    );
  }
}

class _Section extends StatelessWidget {
  final String title;
  final MeshpointPalette palette;
  final List<(String, String)> rows;
  const _Section({required this.title, required this.palette, required this.rows});

  @override
  Widget build(BuildContext context) {
    if (rows.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title.toUpperCase(),
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.5,
              color: palette.accentCyan,
            ),
          ),
          const SizedBox(height: 6),
          ...rows.map((row) => Padding(
                padding: const EdgeInsets.symmetric(vertical: 3),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(row.$1, style: TextStyle(fontSize: 12.5, color: palette.textMuted)),
                    Flexible(
                      child: Text(
                        row.$2,
                        style: TextStyle(fontSize: 12.5, color: palette.textPrimary, fontWeight: FontWeight.w600),
                        textAlign: TextAlign.right,
                      ),
                    ),
                  ],
                ),
              )),
        ],
      ),
    );
  }
}
