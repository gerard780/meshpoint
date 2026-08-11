/// Mirrors one entry from `GET /api/nodes` (`Node.to_dict()` in
/// `src/models/node.py`, optionally enriched with `latest_signal`).
/// Kept defensive/nullable throughout -- this is real field telemetry
/// from radio hardware, plenty of it is legitimately absent per node.
class NodeSummary {
  final String nodeId;
  final String displayName;
  final String? hardwareModel;
  final String protocol;
  final String? role;
  final DateTime? lastHeard;
  final int packetCount;
  final bool hasPosition;
  final double? latitude;
  final double? longitude;
  final double? rssi;
  final double? snr;

  NodeSummary({
    required this.nodeId,
    required this.displayName,
    this.hardwareModel,
    required this.protocol,
    this.role,
    this.lastHeard,
    required this.packetCount,
    required this.hasPosition,
    this.latitude,
    this.longitude,
    this.rssi,
    this.snr,
  });

  factory NodeSummary.fromJson(Map<String, dynamic> json) {
    final signal = json['latest_signal'] as Map<String, dynamic>?;
    final lastHeardRaw = json['last_heard'] as String?;
    return NodeSummary(
      nodeId: json['node_id'] as String? ?? '',
      displayName: json['display_name'] as String? ??
          json['long_name'] as String? ??
          json['node_id'] as String? ??
          '?',
      hardwareModel: json['hardware_model'] as String?,
      protocol: json['protocol'] as String? ?? 'meshtastic',
      role: json['role'] as String?,
      lastHeard: lastHeardRaw != null ? DateTime.tryParse(lastHeardRaw) : null,
      packetCount: (json['packet_count'] as num?)?.toInt() ?? 0,
      hasPosition: json['has_position'] as bool? ?? false,
      latitude: (json['latitude'] as num?)?.toDouble(),
      longitude: (json['longitude'] as num?)?.toDouble(),
      rssi: (signal?['rssi'] as num?)?.toDouble(),
      snr: (signal?['snr'] as num?)?.toDouble(),
    );
  }

  String lastHeardLabel() {
    if (lastHeard == null) return '--';
    final diff = DateTime.now().toUtc().difference(lastHeard!.toUtc());
    if (diff.inSeconds < 60) return 'Now';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
    if (diff.inHours < 24) return '${diff.inHours}h ago';
    return '${diff.inDays}d ago';
  }
}
