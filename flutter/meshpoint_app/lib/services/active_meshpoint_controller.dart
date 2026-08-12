import 'dart:async';

import 'package:flutter/foundation.dart';

import '../models/meshpoint_server.dart';
import '../models/node_summary.dart';
import '../models/packet_event.dart';
import 'api_client.dart';
import 'meshpoint_store.dart';
import 'websocket_service.dart';

/// Owns the connection to whichever single meshpoint is currently
/// "active" -- the one the bottom nav's Nodes/Live tabs show data for.
/// Lives above [HomeShell] (see `lib/main.dart`'s `MultiProvider`) so
/// switching bottom-nav tabs doesn't tear down and reconnect the
/// websocket or the reconciliation timer; only [setActive] with a
/// different meshpoint does that. Ported straight from what used to be
/// `ServerDashboardScreen`'s own `State` fields, before that screen
/// existed per-server rather than as shared tabs.
///
/// Deliberately doesn't own device *status* (uptime/firmware/etc.) --
/// that's fetched fresh, per-meshpoint, by `MeshpointDetailSheet`
/// whenever the user taps a meshpoint card, independent of which one
/// (if any) is currently active.
class ActiveMeshpointController extends ChangeNotifier {
  final MeshpointStore _meshpointStore;
  ActiveMeshpointController(this._meshpointStore);

  MeshpointServer? _active;
  MeshpointServer? get active => _active;

  ApiClient? _api;

  List<NodeSummary> nodes = [];
  String? nodesError;
  bool loadingNodes = false;

  final List<PacketEvent> livePackets = [];
  static const _maxLivePackets = 100;

  final _ws = WebSocketService();

  // Reconciliation fallback for everything a single live packet doesn't
  // carry (new nodes joining, battery/voltage/hardware telemetry) --
  // mirrors `frontend/js/app.js`'s own 15s `_refreshData()` interval
  // that runs alongside its per-packet `updateFromPacket()` patching,
  // not instead of it.
  Timer? _nodesRefreshTimer;

  Future<void> setActive(MeshpointServer meshpoint) async {
    if (_active?.id == meshpoint.id) return;
    _teardown();
    _active = meshpoint;
    nodes = [];
    nodesError = null;
    loadingNodes = false;
    livePackets.clear();
    notifyListeners();

    _api = ApiClient(baseUrl: meshpoint.normalizedBaseUrl, token: meshpoint.token);
    unawaited(_loadNodes());
    _connectLive();
    _nodesRefreshTimer = Timer.periodic(
      const Duration(seconds: 15),
      (_) => _loadNodes(showLoading: false),
    );
  }

  /// Called when the active meshpoint is logged out or removed from the
  /// fleet -- Nodes/Live fall back to their "no active meshpoint" empty
  /// state rather than keep showing stale data for one the app no
  /// longer has a session for.
  void clear() {
    _teardown();
    _active = null;
    nodes = [];
    nodesError = null;
    loadingNodes = false;
    livePackets.clear();
    notifyListeners();
  }

  void clearIfActive(String meshpointId) {
    if (_active?.id == meshpointId) clear();
  }

  void _teardown() {
    _nodesRefreshTimer?.cancel();
    _nodesRefreshTimer = null;
    _ws.disconnect();
  }

  /// [showLoading] is false for the background 15s reconciliation timer
  /// -- that one runs silently (no spinner flash every 15s); the
  /// initial load on [setActive] and manual pull-to-refresh still show
  /// it, and a silent background failure doesn't blow away an
  /// already-populated, still-good node list with an error state.
  Future<void> _loadNodes({bool showLoading = true}) async {
    final api = _api;
    if (api == null) return;
    if (showLoading) {
      loadingNodes = true;
      notifyListeners();
    }
    try {
      final fetched = await api.getNodes();
      fetched.sort((a, b) {
        final ta = a.lastHeard?.millisecondsSinceEpoch ?? 0;
        final tb = b.lastHeard?.millisecondsSinceEpoch ?? 0;
        return tb.compareTo(ta);
      });
      _active?.lastKnownNodeCount = fetched.length;
      nodes = fetched;
      nodesError = null;
      unawaited(_meshpointStore.save());
    } catch (e) {
      if (showLoading) nodesError = e.toString();
    } finally {
      if (showLoading) loadingNodes = false;
    }
    notifyListeners();
  }

  Future<void> refreshNodes() => _loadNodes();

  void _connectLive() {
    final api = _api;
    if (api == null) return;
    final stream = _ws.connect(api.websocketUri());
    stream.listen(
      (packet) {
        livePackets.insert(0, packet);
        if (livePackets.length > _maxLivePackets) {
          livePackets.removeLast();
        }
        _applyLivePacketToNodes(packet);
        notifyListeners();
      },
      onError: (_) {},
    );
  }

  /// Patches the matching node's signal/last-heard in place from a live
  /// packet -- mirrors `NodeCards.updateFromPacket()` in
  /// `frontend/js/node_cards.js`.
  void _applyLivePacketToNodes(PacketEvent packet) {
    final idx = nodes.indexWhere((n) => n.nodeId == packet.sourceId);
    if (idx < 0) return; // Unknown node -- the 15s reconciliation timer will pick it up.
    final updated = nodes[idx].withLivePacket(
      heardAt: packet.timestamp,
      rssi: packet.rssi,
      snr: packet.snr,
    );
    nodes
      ..removeAt(idx)
      ..insert(0, updated); // Most-recently-heard-first, matching _loadNodes()'s sort.
  }

  @override
  void dispose() {
    _teardown();
    super.dispose();
  }
}
