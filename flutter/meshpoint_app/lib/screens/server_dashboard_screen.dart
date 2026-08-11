import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/device_status.dart';
import '../models/meshpoint_server.dart';
import '../models/node_summary.dart';
import '../models/packet_event.dart';
import '../services/api_client.dart';
import '../services/server_store.dart';
import '../services/websocket_service.dart';

/// v1 scope, deliberately narrow (see memory/project_meshpoint_app.md):
/// device-status tile + a searchable node list + a live packet feed.
/// Config editing, repeater management, per-protocol pages -- real,
/// valuable, but v2+, once this core "glance at your fleet" loop is
/// actually validated.
class ServerDashboardScreen extends StatefulWidget {
  final MeshpointServer server;
  const ServerDashboardScreen({super.key, required this.server});

  @override
  State<ServerDashboardScreen> createState() => _ServerDashboardScreenState();
}

class _ServerDashboardScreenState extends State<ServerDashboardScreen>
    with SingleTickerProviderStateMixin {
  late final TabController _tabController;
  late final ApiClient _api;
  final _ws = WebSocketService();

  DeviceStatus? _status;
  String? _statusError;

  List<NodeSummary> _nodes = [];
  String? _nodesError;
  bool _loadingNodes = true;
  String _nodeSearch = '';

  final List<PacketEvent> _livePackets = [];
  static const _maxLivePackets = 100;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
    _api = ApiClient(baseUrl: widget.server.normalizedBaseUrl, token: widget.server.token);
    _loadStatus();
    _loadNodes();
    _connectLive();
  }

  @override
  void dispose() {
    _tabController.dispose();
    _ws.disconnect();
    super.dispose();
  }

  Future<void> _loadStatus() async {
    try {
      final status = await _api.getDeviceStatus();
      widget.server.lastKnownVersion = status.firmwareVersion;
      widget.server.lastSeenOnline = true;
      if (!mounted) return;
      setState(() {
        _status = status;
        _statusError = null;
      });
    } catch (e) {
      widget.server.lastSeenOnline = false;
      if (!mounted) return;
      setState(() => _statusError = e.toString());
    }
    if (mounted) context.read<ServerStore>().save();
  }

  Future<void> _loadNodes() async {
    setState(() => _loadingNodes = true);
    try {
      final nodes = await _api.getNodes();
      nodes.sort((a, b) {
        final ta = a.lastHeard?.millisecondsSinceEpoch ?? 0;
        final tb = b.lastHeard?.millisecondsSinceEpoch ?? 0;
        return tb.compareTo(ta);
      });
      widget.server.lastKnownNodeCount = nodes.length;
      if (!mounted) return;
      setState(() {
        _nodes = nodes;
        _nodesError = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _nodesError = e.toString());
    } finally {
      if (mounted) setState(() => _loadingNodes = false);
    }
  }

  void _connectLive() {
    final stream = _ws.connect(_api.websocketUri());
    stream.listen(
      (packet) {
        if (!mounted) return;
        setState(() {
          _livePackets.insert(0, packet);
          if (_livePackets.length > _maxLivePackets) {
            _livePackets.removeLast();
          }
        });
      },
      onError: (_) {},
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.server.name),
        bottom: TabBar(
          controller: _tabController,
          tabs: const [
            Tab(text: 'Status'),
            Tab(text: 'Nodes'),
            Tab(text: 'Live'),
          ],
        ),
      ),
      body: TabBarView(
        controller: _tabController,
        children: [
          _StatusTab(status: _status, error: _statusError, onRefresh: _loadStatus),
          _NodesTab(
            nodes: _nodes,
            loading: _loadingNodes,
            error: _nodesError,
            search: _nodeSearch,
            onSearchChanged: (v) => setState(() => _nodeSearch = v),
            onRefresh: _loadNodes,
          ),
          _LiveTab(packets: _livePackets),
        ],
      ),
    );
  }
}

class _StatusTab extends StatelessWidget {
  final DeviceStatus? status;
  final String? error;
  final Future<void> Function() onRefresh;

  const _StatusTab({required this.status, required this.error, required this.onRefresh});

  @override
  Widget build(BuildContext context) {
    if (error != null && status == null) {
      return _ErrorRetry(message: error!, onRetry: onRefresh);
    }
    if (status == null) {
      return const Center(child: CircularProgressIndicator());
    }
    final s = status!;
    return RefreshIndicator(
      onRefresh: onRefresh,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _StatusRow('Status', s.status),
          _StatusRow('Firmware', s.firmwareVersion),
          _StatusRow('Uptime', s.uptimeLabel),
          _StatusRow('Device name', s.deviceName ?? '--'),
          _StatusRow('Long name', s.longName ?? '--'),
          _StatusRow('WebSocket clients', '${s.websocketClients}'),
          _StatusRow('Device ID', s.deviceId),
        ],
      ),
    );
  }
}

class _StatusRow extends StatelessWidget {
  final String label;
  final String value;
  const _StatusRow(this.label, this.value);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: TextStyle(color: Theme.of(context).colorScheme.outline)),
          Text(value, style: const TextStyle(fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }
}

class _NodesTab extends StatelessWidget {
  final List<NodeSummary> nodes;
  final bool loading;
  final String? error;
  final String search;
  final ValueChanged<String> onSearchChanged;
  final Future<void> Function() onRefresh;

  const _NodesTab({
    required this.nodes,
    required this.loading,
    required this.error,
    required this.search,
    required this.onSearchChanged,
    required this.onRefresh,
  });

  @override
  Widget build(BuildContext context) {
    if (error != null && nodes.isEmpty) {
      return _ErrorRetry(message: error!, onRetry: onRefresh);
    }
    final filtered = search.isEmpty
        ? nodes
        : nodes
            .where((n) => n.displayName.toLowerCase().contains(search.toLowerCase()) ||
                n.nodeId.toLowerCase().contains(search.toLowerCase()))
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
            onChanged: onSearchChanged,
          ),
        ),
        if (loading) const LinearProgressIndicator(),
        Expanded(
          child: RefreshIndicator(
            onRefresh: onRefresh,
            child: filtered.isEmpty
                ? const Center(child: Text('No nodes'))
                : ListView.builder(
                    itemCount: filtered.length,
                    itemBuilder: (context, i) {
                      final n = filtered[i];
                      return ListTile(
                        title: Text(n.displayName),
                        subtitle: Text(
                          [
                            n.protocol,
                            if (n.role != null) n.role!,
                            if (n.hardwareModel != null) n.hardwareModel!,
                          ].join(' · '),
                        ),
                        trailing: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          crossAxisAlignment: CrossAxisAlignment.end,
                          children: [
                            Text(n.lastHeardLabel()),
                            if (n.rssi != null)
                              Text(
                                '${n.rssi!.toStringAsFixed(0)} dBm',
                                style: Theme.of(context).textTheme.bodySmall,
                              ),
                          ],
                        ),
                      );
                    },
                  ),
          ),
        ),
      ],
    );
  }
}

class _LiveTab extends StatelessWidget {
  final List<PacketEvent> packets;
  const _LiveTab({required this.packets});

  @override
  Widget build(BuildContext context) {
    if (packets.isEmpty) {
      return const Center(child: Text('Waiting for live packets...'));
    }
    return ListView.builder(
      itemCount: packets.length,
      itemBuilder: (context, i) {
        final p = packets[i];
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

class _ErrorRetry extends StatelessWidget {
  final String message;
  final Future<void> Function() onRetry;
  const _ErrorRetry({required this.message, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.error_outline, color: Theme.of(context).colorScheme.error, size: 48),
          const SizedBox(height: 12),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 24),
            child: Text(message, textAlign: TextAlign.center),
          ),
          const SizedBox(height: 12),
          FilledButton(onPressed: onRetry, child: const Text('Retry')),
        ],
      ),
    );
  }
}
