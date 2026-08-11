import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/node_summary.dart';
import '../services/theme_store.dart';
import '../theme/meshpoint_theme.dart';
import '../utils/hardware_names.dart';
import '../utils/node_visuals.dart';

/// A rich per-node summary card, styled after the web dashboard's own
/// node cards (`frontend/js/node_cards.js` + `frontend/css/node_cards.css`,
/// and `extra/local_meshradar/dashboard.html`'s `.node-card`): a
/// hash-colored avatar, online dot, protocol badge, and rows of small
/// signal/telemetry/meta chips. Tapping calls [onTap] -- the caller
/// opens [NodeDetailSheet].
class NodeCard extends StatelessWidget {
  final NodeSummary node;
  final VoidCallback onTap;

  const NodeCard({super.key, required this.node, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final palette = MeshpointPalette.forTheme(context.watch<ThemeStore>().current);

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
      color: palette.bgCard,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(10),
        side: BorderSide(color: palette.border),
      ),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(10),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _CardHeader(node: node, palette: palette),
              if (node.rssi != null || (node.hops ?? 0) > 0) ...[
                const SizedBox(height: 6),
                _SignalRow(node: node, palette: palette),
              ],
              if (_hasTelemetry(node)) ...[
                const SizedBox(height: 6),
                _TelemetryRow(node: node, palette: palette),
              ],
              const SizedBox(height: 6),
              _MetaRow(node: node, palette: palette),
            ],
          ),
        ),
      ),
    );
  }

  static bool _hasTelemetry(NodeSummary n) =>
      n.voltage != null ||
      n.battery != null ||
      n.temperature != null ||
      n.humidity != null ||
      n.channelUtil != null ||
      n.airUtil != null;
}

class _CardHeader extends StatelessWidget {
  final NodeSummary node;
  final MeshpointPalette palette;
  const _CardHeader({required this.node, required this.palette});

  @override
  Widget build(BuildContext context) {
    final initials =
        (node.shortName?.isNotEmpty == true ? node.shortName! : node.nodeId.replaceAll('!', ''))
            .toUpperCase();
    final shortLabel = initials.length > 4 ? initials.substring(initials.length - 4) : initials;
    final avatarColor = hashColorFor(node.nodeId);
    final isMeshcore = node.protocol == 'meshcore';

    return Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Container(
          width: 32,
          height: 32,
          alignment: Alignment.center,
          decoration: BoxDecoration(color: avatarColor, borderRadius: BorderRadius.circular(6)),
          child: Text(
            shortLabel,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 10,
              fontWeight: FontWeight.w700,
              letterSpacing: -0.2,
            ),
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    width: 7,
                    height: 7,
                    decoration: BoxDecoration(
                      color: node.isOnline ? palette.accentGreen : palette.textMuted,
                      shape: BoxShape.circle,
                    ),
                  ),
                  const SizedBox(width: 5),
                  Expanded(
                    child: Text(
                      node.displayName,
                      style: TextStyle(
                        fontWeight: FontWeight.w600,
                        fontSize: 13.5,
                        color: palette.textPrimary,
                      ),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ],
              ),
              Text(
                node.lastHeardLabel(),
                style: TextStyle(fontSize: 11, color: palette.textMuted, fontFamily: 'monospace'),
              ),
            ],
          ),
        ),
        const SizedBox(width: 6),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
          decoration: BoxDecoration(
            color: (isMeshcore ? palette.accentPurple : palette.accentBlue).withValues(alpha: 0.15),
            borderRadius: BorderRadius.circular(3),
          ),
          child: Text(
            isMeshcore ? 'MC' : 'MT',
            style: TextStyle(
              fontSize: 9.5,
              fontWeight: FontWeight.w700,
              color: isMeshcore ? palette.accentPurple : palette.accentBlue,
            ),
          ),
        ),
      ],
    );
  }
}

class _SignalRow extends StatelessWidget {
  final NodeSummary node;
  final MeshpointPalette palette;
  const _SignalRow({required this.node, required this.palette});

  @override
  Widget build(BuildContext context) {
    final chips = <Widget>[];
    final rssi = node.rssi;
    if (rssi != null) {
      final quality = signalQualityFor(rssi, palette);
      chips.add(_Chip(
        color: quality.color,
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            _SignalBars(level: signalBarLevel(rssi), color: quality.color),
            const SizedBox(width: 3),
            Text('${rssi.toStringAsFixed(0)} dBm'),
          ],
        ),
      ));
      if (node.snr != null) {
        chips.add(_Chip(color: palette.textSecondary, text: 'SNR ${node.snr!.toStringAsFixed(1)} dB'));
      }
      chips.add(_Chip(color: quality.color, text: quality.label.toUpperCase(), bold: true));
    }
    if ((node.hops ?? 0) > 0) {
      chips.add(_Chip(color: palette.textSecondary, text: '${node.hops} hop${node.hops! > 1 ? 's' : ''}'));
    }
    return Wrap(spacing: 4, runSpacing: 4, children: chips);
  }
}

class _TelemetryRow extends StatelessWidget {
  final NodeSummary node;
  final MeshpointPalette palette;
  const _TelemetryRow({required this.node, required this.palette});

  @override
  Widget build(BuildContext context) {
    final chips = <Widget>[];
    if (node.voltage != null) {
      chips.add(_Chip(color: palette.accentCyan, text: '⚡ ${node.voltage!.toStringAsFixed(2)}V'));
    }
    if (node.battery == 101) {
      // Meshtastic firmware convention: 101 = externally powered, no
      // battery attached (not a real percentage) -- matches node_cards.js.
      chips.add(_Chip(color: palette.accentCyan, text: '\u{1F50C} Powered'));
    } else if ((node.battery ?? 0) > 0) {
      final tier = batteryTierFor(node.battery!, palette);
      chips.add(_Chip(
        color: tier.color,
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(tier.icon, size: 11, color: tier.color),
            const SizedBox(width: 2),
            Text('${node.battery!.toStringAsFixed(0)}%'),
          ],
        ),
      ));
    }
    if (node.temperature != null) {
      chips.add(_Chip(color: palette.accentCyan, text: '\u{1F321} ${node.temperature!.toStringAsFixed(1)}°F'));
    }
    if (node.humidity != null) {
      chips.add(_Chip(color: palette.accentCyan, text: '\u{1F4A7} ${node.humidity!.toStringAsFixed(0)}%'));
    }
    if (node.channelUtil != null) {
      chips.add(_Chip(color: palette.accentCyan, text: 'ChUtil ${node.channelUtil!.toStringAsFixed(1)}%'));
    }
    if (node.airUtil != null) {
      chips.add(_Chip(color: palette.accentCyan, text: 'AirUtil ${node.airUtil!.toStringAsFixed(1)}%'));
    }
    return Wrap(spacing: 4, runSpacing: 4, children: chips);
  }
}

class _MetaRow extends StatelessWidget {
  final NodeSummary node;
  final MeshpointPalette palette;
  const _MetaRow({required this.node, required this.palette});

  @override
  Widget build(BuildContext context) {
    final chips = <Widget>[];
    if (node.hardwareModel != null) {
      chips.add(_Chip(color: palette.textMuted, text: hardwareNameFor(node.hardwareModel!)));
    }
    if (node.roleLabel != null) {
      chips.add(_Chip(color: palette.textMuted, text: node.roleLabel!));
    }
    if (node.bandLabel != null) {
      chips.add(_Chip(color: palette.accentPurple, text: node.bandLabel!, bold: true));
    }
    chips.add(_Chip(color: palette.textMuted, text: '!${node.nodeId.replaceAll('!', '')}'));

    return Container(
      padding: const EdgeInsets.only(top: 6),
      decoration: BoxDecoration(border: Border(top: BorderSide(color: palette.border.withValues(alpha: 0.6)))),
      child: Wrap(spacing: 4, runSpacing: 4, children: chips),
    );
  }
}

class _Chip extends StatelessWidget {
  final Color color;
  final String? text;
  final Widget? child;
  final bool bold;
  const _Chip({required this.color, this.text, this.child, this.bold = false})
      : assert(text != null || child != null);

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1.5),
      decoration: BoxDecoration(color: color.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(3)),
      child: DefaultTextStyle(
        style: TextStyle(
          fontSize: 10,
          fontFamily: 'monospace',
          color: color,
          fontWeight: bold ? FontWeight.w700 : FontWeight.w500,
          letterSpacing: bold ? 0.3 : 0,
        ),
        child: child ?? Text(text!),
      ),
    );
  }
}

class _SignalBars extends StatelessWidget {
  final int level;
  final Color color;
  const _SignalBars({required this.level, required this.color});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.end,
      children: List.generate(5, (i) {
        final active = i < level;
        return Container(
          width: 2.5,
          height: 4.0 + i * 2,
          margin: const EdgeInsets.only(right: 1),
          color: active ? color : color.withValues(alpha: 0.2),
        );
      }),
    );
  }
}
