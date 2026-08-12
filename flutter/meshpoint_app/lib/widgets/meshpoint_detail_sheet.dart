import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/device_status.dart';
import '../models/meshpoint_server.dart';
import '../services/active_meshpoint_controller.dart';
import '../services/api_client.dart';
import '../services/meshpoint_store.dart';
import '../services/tab_index_controller.dart';
import '../services/theme_store.dart';
import '../theme/meshpoint_theme.dart';

/// Opens a meshpoint's detail popup -- device status/info, plus a
/// "Switch to this meshpoint" action. Tapping a card opens more info
/// about it, not a full navigation away, same spirit as
/// `NodeDetailSheet` -- but deliberately *not* the same
/// `DraggableScrollableSheet` mechanics that one uses. A node's info is
/// variable-length (hardware/role/signal/telemetry/position sections
/// come and go), so a draggable, scrollable sheet earns its keep there.
/// A meshpoint's info is always the same fixed ~7 rows -- a drag handle
/// and scroll affordance on content that's already fully visible just
/// reads as broken ("why can I scroll when there's nothing more to
/// see?", a real complaint). This sizes itself to its content instead.
///
/// This is also where the old per-server "Status" tab's content lives
/// now that the dashboard is a shared bottom-nav shell rather than one
/// screen per meshpoint -- don't lose it, just move it to where it's
/// actually reachable from (the meshpoint you tapped), not a persistent
/// tab that only means something once one is already active.
Future<void> showMeshpointDetailSheet(BuildContext context, MeshpointServer meshpoint) {
  return showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    builder: (_) => MeshpointDetailSheet(meshpoint: meshpoint),
  );
}

class MeshpointDetailSheet extends StatefulWidget {
  final MeshpointServer meshpoint;
  const MeshpointDetailSheet({super.key, required this.meshpoint});

  @override
  State<MeshpointDetailSheet> createState() => _MeshpointDetailSheetState();
}

class _MeshpointDetailSheetState extends State<MeshpointDetailSheet> {
  DeviceStatus? _status;
  String? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    // A fresh, one-off client -- independent of ActiveMeshpointController,
    // since you can view any logged-in meshpoint's info here, not just
    // the currently active one.
    final client = ApiClient(baseUrl: widget.meshpoint.normalizedBaseUrl, token: widget.meshpoint.token);
    try {
      final status = await client.getDeviceStatus();
      widget.meshpoint.lastKnownVersion = status.firmwareVersion;
      widget.meshpoint.lastSeenOnline = true;
      if (!mounted) return;
      setState(() {
        _status = status;
        _error = null;
        _loading = false;
      });
    } catch (e) {
      widget.meshpoint.lastSeenOnline = false;
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
    if (mounted) await context.read<MeshpointStore>().save();
  }

  @override
  Widget build(BuildContext context) {
    final palette = MeshpointPalette.forTheme(context.watch<ThemeStore>().current);
    final isActive = context.watch<ActiveMeshpointController>().active?.id == widget.meshpoint.id;

    return SafeArea(
      child: Container(
        decoration: BoxDecoration(
          color: palette.bgCard,
          borderRadius: const BorderRadius.vertical(top: Radius.circular(16)),
        ),
        // No drag handle, no DraggableScrollableSheet -- this sheet's
        // content is always the same fixed handful of rows, so it just
        // sizes to fit them. The ConstrainedBox+SingleChildScrollView is
        // a quiet safety net only (kicks in on a genuinely tiny screen
        // with a long device name), not a visible/advertised affordance.
        child: ConstrainedBox(
          constraints: BoxConstraints(maxHeight: MediaQuery.of(context).size.height * 0.85),
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 16, 8, 8),
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              widget.meshpoint.name,
                              style:
                                  TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: palette.textPrimary),
                              overflow: TextOverflow.ellipsis,
                            ),
                            Text(
                              widget.meshpoint.baseUrl,
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
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                  child: Column(
                    children: [
                      if (_loading)
                        const Padding(
                          padding: EdgeInsets.all(24),
                          child: Center(child: CircularProgressIndicator()),
                        ),
                      if (_error != null && !_loading)
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 12),
                          child: Text(_error!, style: TextStyle(color: palette.accentRed)),
                        ),
                      if (_status != null) ..._statusRows(_status!, palette),
                    ],
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
                  child: FilledButton.icon(
                    onPressed: (_status == null || isActive) ? null : () => _switchToThisMeshpoint(context),
                    icon: Icon(isActive ? Icons.check : Icons.swap_horiz),
                    label: Text(isActive ? 'Active meshpoint' : 'Switch to this meshpoint'),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  void _switchToThisMeshpoint(BuildContext context) {
    context.read<ActiveMeshpointController>().setActive(widget.meshpoint);
    context.read<TabIndexController>().setIndex(1); // Nodes tab.
    Navigator.of(context).pop();
  }

  List<Widget> _statusRows(DeviceStatus s, MeshpointPalette palette) {
    final rows = <(String, String)>[
      ('Status', s.status),
      ('Firmware', s.firmwareVersion),
      ('Uptime', s.uptimeLabel),
      ('Device name', s.deviceName ?? '--'),
      ('Long name', s.longName ?? '--'),
      ('WebSocket clients', '${s.websocketClients}'),
      ('Device ID', s.deviceId),
    ];
    return rows
        .map(
          (r) => Padding(
            padding: const EdgeInsets.symmetric(vertical: 5),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(r.$1, style: TextStyle(fontSize: 12.5, color: palette.textMuted)),
                Flexible(
                  child: Text(
                    r.$2,
                    style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600, color: palette.textPrimary),
                    textAlign: TextAlign.right,
                  ),
                ),
              ],
            ),
          ),
        )
        .toList();
  }
}
