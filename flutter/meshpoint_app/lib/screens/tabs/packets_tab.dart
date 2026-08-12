import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../services/active_meshpoint_controller.dart';
import '../../widgets/no_active_meshpoint_notice.dart';

/// Live packet feed for whichever meshpoint is currently active -- same
/// "shared tab, needs its own empty state" shape as [NodesTab].
///
/// v1 scope, deliberately plain (`ListTile` rows, no cards/filters yet)
/// -- richer packet-card UI is a real follow-up, not done here.
class PacketsTab extends StatelessWidget {
  const PacketsTab({super.key});

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<ActiveMeshpointController>();

    return Scaffold(
      appBar: AppBar(
        title: Text(controller.active != null ? '${controller.active!.name} · Packets' : 'Packets'),
      ),
      body: controller.active == null ? const NoActiveMeshpointNotice() : _buildFeed(context, controller),
    );
  }

  Widget _buildFeed(BuildContext context, ActiveMeshpointController controller) {
    if (controller.livePackets.isEmpty) {
      return const Center(child: Text('Waiting for live packets...'));
    }
    return ListView.builder(
      itemCount: controller.livePackets.length,
      itemBuilder: (context, i) {
        final p = controller.livePackets[i];
        return ListTile(
          dense: true,
          title: Text('${p.sourceId} → ${p.destinationId}'),
          subtitle: Text('${p.protocol} · ${p.packetType}'),
          trailing: Text(
            p.rssi != null ? '${p.rssi!.toStringAsFixed(0)} dBm' : '',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        );
      },
    );
  }
}
