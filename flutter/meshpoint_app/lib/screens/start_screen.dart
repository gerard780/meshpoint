import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/meshpoint_server.dart';
import '../services/api_client.dart';
import '../services/server_store.dart';
import 'add_edit_server_screen.dart';
import 'server_dashboard_screen.dart';

/// The app's home screen: the fleet -- every configured meshpoint server,
/// add/remove from here. Tapping a server that's already logged in goes
/// straight to its dashboard; one that isn't (freshly added, or a token
/// that's since expired) goes to the login screen first.
class StartScreen extends StatefulWidget {
  const StartScreen({super.key});

  @override
  State<StartScreen> createState() => _StartScreenState();
}

class _StartScreenState extends State<StartScreen> {
  final Map<String, bool?> _onlineById = {}; // null = checking

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _refreshAll());
  }

  Future<void> _refreshAll() async {
    final store = context.read<ServerStore>();
    for (final server in store.servers) {
      _checkOne(server);
    }
  }

  Future<void> _checkOne(MeshpointServer server) async {
    setState(() => _onlineById[server.id] = null);
    final client = ApiClient(baseUrl: server.normalizedBaseUrl, token: server.token);
    try {
      await client.getIdentity();
      if (!mounted) return;
      setState(() => _onlineById[server.id] = true);
    } catch (_) {
      if (!mounted) return;
      setState(() => _onlineById[server.id] = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final store = context.watch<ServerStore>();

    return Scaffold(
      appBar: AppBar(title: const Text('Meshpoint Fleet')),
      body: !store.loaded
          ? const Center(child: CircularProgressIndicator())
          : store.servers.isEmpty
              ? _EmptyState(onAdd: () => _openAddServer(context))
              : RefreshIndicator(
                  onRefresh: _refreshAll,
                  child: ListView.builder(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    itemCount: store.servers.length,
                    itemBuilder: (context, i) {
                      final server = store.servers[i];
                      return _ServerTile(
                        server: server,
                        online: _onlineById[server.id],
                        onTap: () => _openServer(context, server),
                        onRemove: () => _confirmRemove(context, server),
                      );
                    },
                  ),
                ),
      floatingActionButton: FloatingActionButton(
        onPressed: () => _openAddServer(context),
        tooltip: 'Add server',
        child: const Icon(Icons.add),
      ),
    );
  }

  Future<void> _openAddServer(BuildContext context) async {
    await Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => const AddEditServerScreen()),
    );
    if (mounted) _refreshAll();
  }

  void _openServer(BuildContext context, MeshpointServer server) {
    if (!server.isLoggedIn) {
      Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => AddEditServerScreen(existing: server),
        ),
      );
      return;
    }
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => ServerDashboardScreen(server: server)),
    );
  }

  Future<void> _confirmRemove(BuildContext context, MeshpointServer server) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Remove server'),
        content: Text('Remove "${server.name}" from this app? '
            'This only forgets it here -- nothing changes on the server itself.'),
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
      await context.read<ServerStore>().removeServer(server.id);
    }
  }
}

class _ServerTile extends StatelessWidget {
  final MeshpointServer server;
  final bool? online; // null = checking, true/false = known
  final VoidCallback onTap;
  final VoidCallback onRemove;

  const _ServerTile({
    required this.server,
    required this.online,
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
        child: Text(server.name.isNotEmpty ? server.name[0].toUpperCase() : '?'),
      ),
      title: Text(server.name),
      subtitle: Text(
        [
          server.baseUrl,
          if (server.lastKnownVersion != null) 'v${server.lastKnownVersion}',
          if (!server.isLoggedIn) 'not logged in',
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
          const Text('No meshpoint servers yet'),
          const SizedBox(height: 8),
          FilledButton.icon(
            onPressed: onAdd,
            icon: const Icon(Icons.add),
            label: const Text('Add your first server'),
          ),
        ],
      ),
    );
  }
}
