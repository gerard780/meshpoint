import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../models/meshpoint_server.dart';
import '../../services/active_meshpoint_controller.dart';
import '../../services/api_client.dart';
import '../../services/meshpoint_store.dart';
import '../../widgets/meshpoint_detail_sheet.dart';
import '../add_edit_meshpoint_screen.dart';

/// First bottom-nav tab, and where the boot screen lands: every
/// configured meshpoint, add/remove from here. Tapping one that's
/// already logged in opens its info popup (see
/// [showMeshpointDetailSheet]) with a "Switch to this meshpoint"
/// action; one that isn't (freshly added, or a token that's since
/// expired) goes to the login screen first.
class MeshpointsTab extends StatefulWidget {
  const MeshpointsTab({super.key});

  @override
  State<MeshpointsTab> createState() => _MeshpointsTabState();
}

class _MeshpointsTabState extends State<MeshpointsTab> {
  final Map<String, bool?> _onlineById = {}; // null = checking

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _refreshAll());
  }

  Future<void> _refreshAll() async {
    final store = context.read<MeshpointStore>();
    for (final meshpoint in store.servers) {
      _checkOne(meshpoint);
    }
  }

  Future<void> _checkOne(MeshpointServer meshpoint) async {
    setState(() => _onlineById[meshpoint.id] = null);
    final client = ApiClient(baseUrl: meshpoint.normalizedBaseUrl, token: meshpoint.token);
    try {
      await client.getIdentity();
      if (!mounted) return;
      setState(() => _onlineById[meshpoint.id] = true);
    } catch (_) {
      if (!mounted) return;
      setState(() => _onlineById[meshpoint.id] = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final store = context.watch<MeshpointStore>();
    final activeId = context.watch<ActiveMeshpointController>().active?.id;

    return Scaffold(
      appBar: AppBar(title: const Text('Meshpoints')),
      body: !store.loaded
          ? const Center(child: CircularProgressIndicator())
          : store.servers.isEmpty
              ? _EmptyState(onAdd: () => _openAddMeshpoint(context))
              : RefreshIndicator(
                  onRefresh: _refreshAll,
                  child: ListView.builder(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    itemCount: store.servers.length,
                    itemBuilder: (context, i) {
                      final meshpoint = store.servers[i];
                      return _MeshpointTile(
                        meshpoint: meshpoint,
                        online: _onlineById[meshpoint.id],
                        isActive: meshpoint.id == activeId,
                        onTap: () => _openMeshpoint(context, meshpoint),
                        onRemove: () => _confirmRemove(context, meshpoint),
                      );
                    },
                  ),
                ),
      floatingActionButton: FloatingActionButton(
        onPressed: () => _openAddMeshpoint(context),
        tooltip: 'Add meshpoint',
        child: const Icon(Icons.add),
      ),
    );
  }

  Future<void> _openAddMeshpoint(BuildContext context) async {
    await Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => const AddEditMeshpointScreen()),
    );
    if (mounted) _refreshAll();
  }

  void _openMeshpoint(BuildContext context, MeshpointServer meshpoint) {
    if (!meshpoint.isLoggedIn) {
      Navigator.of(context).push(
        MaterialPageRoute(builder: (_) => AddEditMeshpointScreen(existing: meshpoint)),
      );
      return;
    }
    showMeshpointDetailSheet(context, meshpoint);
  }

  Future<void> _confirmRemove(BuildContext context, MeshpointServer meshpoint) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Remove meshpoint'),
        content: Text('Remove "${meshpoint.name}" from this app? '
            'This only forgets it here -- nothing changes on the meshpoint itself.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('Remove'),
          ),
        ],
      ),
    );
    if (confirmed == true && context.mounted) {
      context.read<ActiveMeshpointController>().clearIfActive(meshpoint.id);
      await context.read<MeshpointStore>().removeServer(meshpoint.id);
    }
  }
}

class _MeshpointTile extends StatelessWidget {
  final MeshpointServer meshpoint;
  final bool? online; // null = checking, true/false = known
  final bool isActive;
  final VoidCallback onTap;
  final VoidCallback onRemove;

  const _MeshpointTile({
    required this.meshpoint,
    required this.online,
    required this.isActive,
    required this.onTap,
    required this.onRemove,
  });

  @override
  Widget build(BuildContext context) {
    final dotColor = online == null
        ? Colors.grey
        : online!
            ? Colors.green
            : Colors.red;
    return ListTile(
      leading: CircleAvatar(
        child: Text(meshpoint.name.isNotEmpty ? meshpoint.name[0].toUpperCase() : '?'),
      ),
      title: Row(
        children: [
          Flexible(child: Text(meshpoint.name, overflow: TextOverflow.ellipsis)),
          if (isActive) ...[
            const SizedBox(width: 6),
            Icon(Icons.check_circle, size: 16, color: Theme.of(context).colorScheme.primary),
          ],
        ],
      ),
      subtitle: Text(
        [
          meshpoint.baseUrl,
          if (meshpoint.lastKnownVersion != null) 'v${meshpoint.lastKnownVersion}',
          if (!meshpoint.isLoggedIn) 'not logged in',
        ].join(' · '),
      ),
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 10,
            height: 10,
            decoration: BoxDecoration(color: dotColor, shape: BoxShape.circle),
          ),
          IconButton(
            icon: const Icon(Icons.delete_outline),
            onPressed: onRemove,
            tooltip: 'Remove',
          ),
        ],
      ),
      onTap: onTap,
    );
  }
}

class _EmptyState extends StatelessWidget {
  final VoidCallback onAdd;
  const _EmptyState({required this.onAdd});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.router_outlined, size: 64, color: Colors.grey),
          const SizedBox(height: 16),
          const Text('No meshpoints yet'),
          const SizedBox(height: 8),
          FilledButton.icon(
            onPressed: onAdd,
            icon: const Icon(Icons.add),
            label: const Text('Add your first meshpoint'),
          ),
        ],
      ),
    );
  }
}
