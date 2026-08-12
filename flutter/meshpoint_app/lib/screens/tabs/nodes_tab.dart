import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../services/active_meshpoint_controller.dart';
import '../../widgets/error_retry.dart';
import '../../widgets/no_active_meshpoint_notice.dart';
import '../../widgets/node_card.dart';
import '../../widgets/node_detail_sheet.dart';

/// Node roster for whichever meshpoint is currently active
/// ([ActiveMeshpointController.active]) -- a shared tab, not a
/// per-meshpoint screen, so it needs its own "nothing active yet" state.
class NodesTab extends StatefulWidget {
  const NodesTab({super.key});

  @override
  State<NodesTab> createState() => _NodesTabState();
}

class _NodesTabState extends State<NodesTab> {
  String _search = '';

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<ActiveMeshpointController>();

    return Scaffold(
      appBar: AppBar(title: Text(controller.active?.name ?? 'Nodes')),
      body: controller.active == null ? const NoActiveMeshpointNotice() : _buildList(controller),
    );
  }

  Widget _buildList(ActiveMeshpointController controller) {
    if (controller.nodesError != null && controller.nodes.isEmpty) {
      return ErrorRetry(message: controller.nodesError!, onRetry: controller.refreshNodes);
    }
    final filtered = _search.isEmpty
        ? controller.nodes
        : controller.nodes
            .where((n) =>
                n.displayName.toLowerCase().contains(_search.toLowerCase()) ||
                n.nodeId.toLowerCase().contains(_search.toLowerCase()))
            .toList();

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.all(12),
          child: TextField(
            decoration: const InputDecoration(
              prefixIcon: Icon(Icons.search),
              hintText: 'Search nodes...',
              border: OutlineInputBorder(),
              isDense: true,
            ),
            onChanged: (v) => setState(() => _search = v),
          ),
        ),
        if (controller.loadingNodes) const LinearProgressIndicator(),
        Expanded(
          child: RefreshIndicator(
            onRefresh: controller.refreshNodes,
            child: filtered.isEmpty
                ? const Center(child: Text('No nodes'))
                : ListView.builder(
                    padding: const EdgeInsets.symmetric(vertical: 6),
                    itemCount: filtered.length,
                    itemBuilder: (context, i) {
                      final n = filtered[i];
                      return NodeCard(
                        node: n,
                        onTap: () => showNodeDetailSheet(context, n),
                      );
                    },
                  ),
          ),
        ),
      ],
    );
  }
}
