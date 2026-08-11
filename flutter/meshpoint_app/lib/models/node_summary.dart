/// Mirrors one entry from `GET /api/nodes` (`NodeRepository.get_all_with_signal()`
/// in `src/storage/node_repository.py`, the same enriched shape
/// `frontend/js/node_cards.js` renders) -- flat `latest_*` columns joined
/// in from the most recent packet/telemetry row per node, not nested
/// under `latest_signal`/`latest_telemetry` the way bare `Node.to_dict()`
/// is. Kept defensive/nullable throughout -- this is real field telemetry
/// from radio hardware, plenty of it is legitimately absent per node.
class NodeSummary {
  final String nodeId;
  final String displayName;
  final String? shortName;
  final String? hardwareModel;
  final String? firmwareVersion;
  final String protocol;
  final String? role;
  final DateTime? firstSeen;
  final DateTime? lastHeard;
  final int packetCount;
  final bool hasPosition;
  final double? latitude;
  final double? longitude;
  final double? altitude;
  final double? rssi;
  final double? snr;
  final int? hops;
  final String? captureSource;
  final double? battery;
  final double? voltage;
  final double? temperature;
  final double? humidity;
  final double? channelUtil;
  final double? airUtil;

  NodeSummary({
    required this.nodeId,
    required this.displayName,
    this.shortName,
    this.hardwareModel,
    this.firmwareVersion,
    required this.protocol,
    this.role,
    this.firstSeen,
    this.lastHeard,
    required this.packetCount,
    required this.hasPosition,
    this.latitude,
    this.longitude,
    this.altitude,
    this.rssi,
    this.snr,
    this.hops,
    this.captureSource,
    this.battery,
    this.voltage,
    this.temperature,
    this.humidity,
    this.channelUtil,
    this.airUtil,
  });

  factory NodeSummary.fromJson(Map<String, dynamic> json) {
    // Bare `Node.to_dict()` (enrich=false) nests these under
    // `latest_signal`/`latest_telemetry`; the default enriched `/api/nodes`
    // response this app actually calls flattens them as `latest_*` --
    // both are accepted so this model doesn't silently go blank if the
    // enrichment flag ever flips.
    final signal = json['latest_signal'] as Map<String, dynamic>?;
    final telemetry = json['latest_telemetry'] as Map<String, dynamic>?;
    final lastHeardRaw = json['last_heard'] as String?;
    final firstSeenRaw = json['first_seen'] as String?;
    return NodeSummary(
      nodeId: json['node_id'] as String? ?? '',
      displayName: json['display_name'] as String? ??
          json['long_name'] as String? ??
          json['node_id'] as String? ??
          '?',
      shortName: json['short_name'] as String?,
      hardwareModel: json['hardware_model'] as String?,
      firmwareVersion: json['firmware_version'] as String?,
      protocol: json['protocol'] as String? ?? 'meshtastic',
      role: json['role'] as String?,
      firstSeen: firstSeenRaw != null ? DateTime.tryParse(firstSeenRaw) : null,
      lastHeard: lastHeardRaw != null ? DateTime.tryParse(lastHeardRaw) : null,
      packetCount: (json['packet_count'] as num?)?.toInt() ?? 0,
      hasPosition: json['has_position'] as bool? ?? false,
      latitude: (json['latitude'] as num?)?.toDouble(),
      longitude: (json['longitude'] as num?)?.toDouble(),
      altitude: (json['altitude'] as num?)?.toDouble(),
      rssi: (json['latest_rssi'] as num?)?.toDouble() ?? (signal?['rssi'] as num?)?.toDouble(),
      snr: (json['latest_snr'] as num?)?.toDouble() ?? (signal?['snr'] as num?)?.toDouble(),
      hops: (json['latest_hops'] as num?)?.toInt(),
      captureSource: json['latest_capture_source'] as String?,
      battery:
          (json['latest_battery'] as num?)?.toDouble() ?? (telemetry?['battery_level'] as num?)?.toDouble(),
      voltage: (json['latest_voltage'] as num?)?.toDouble() ?? (telemetry?['voltage'] as num?)?.toDouble(),
      temperature:
          (json['latest_temperature'] as num?)?.toDouble() ?? (telemetry?['temperature'] as num?)?.toDouble(),
      humidity: (json['latest_humidity'] as num?)?.toDouble() ?? (telemetry?['humidity'] as num?)?.toDouble(),
      channelUtil: (json['latest_channel_util'] as num?)?.toDouble() ??
          (telemetry?['channel_utilization'] as num?)?.toDouble(),
      airUtil:
          (json['latest_air_util'] as num?)?.toDouble() ?? (telemetry?['air_util_tx'] as num?)?.toDouble(),
    );
  }

  String lastHeardLabel() => _timeAgo(lastHeard);

  String firstSeenLabel() => _timeAgo(firstSeen);

  static String _timeAgo(DateTime? ts) {
    if (ts == null) return '--';
    final diff = DateTime.now().toUtc().difference(ts.toUtc());
    if (diff.inSeconds < 0) return 'Now';
    if (diff.inSeconds < 60) return 'Now';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
    if (diff.inHours < 24) return '${diff.inHours}h ago';
    return '${diff.inDays}d ago';
  }

  /// Matches `NodeCards.ONLINE_THRESHOLD_MS` in `frontend/js/node_cards.js`
  /// -- "recently heard", not the device's own 15-minute heartbeat window.
  bool get isOnline {
    if (lastHeard == null) return false;
    return DateTime.now().toUtc().difference(lastHeard!.toUtc()) < const Duration(hours: 2);
  }

  /// `role` arrives as a stringified protobuf enum int (e.g. "4"); mirrors
  /// `_roleName()` in `frontend/js/node_cards.js`/`node_drawer.js`.
  static const Map<int, String> _roleNames = {
    0: 'CLIENT',
    1: 'CLIENT_MUTE',
    2: 'ROUTER',
    3: 'ROUTER_CLIENT',
    4: 'REPEATER',
    5: 'TRACKER',
    6: 'SENSOR',
    7: 'TAK',
    8: 'CLIENT_HIDDEN',
    9: 'LOST_AND_FOUND',
    10: 'TAK_TRACKER',
  };

  String? get roleLabel {
    if (role == null) return null;
    final n = int.tryParse(role!);
    if (n != null) return _roleNames[n] ?? 'ROLE_$n';
    return role!.toUpperCase();
  }

  /// Mirrors `_bandLabel()` in `frontend/js/node_cards.js`/`node_drawer.js`
  /// -- derived from the labelled capture source, not `frequency_mhz`
  /// (the serial USB source stamps a placeholder frequency regardless of
  /// the stick's real firmware region).
  String? get bandLabel {
    final src = captureSource;
    if (src == null) return null;
    if (src.endsWith('_433')) return '433 MHz';
    if (src.endsWith('_868')) return '868 MHz';
    if (src == 'concentrator') return '868 MHz';
    return null;
  }

  /// Applies a live `/ws` packet's signal/timing to this node without
  /// waiting for the next full `/api/nodes` reconciliation -- mirrors
  /// `NodeCards.updateFromPacket()` in `frontend/js/node_cards.js`,
  /// which patches `last_heard`/`latest_rssi`/`latest_snr` in place off
  /// every packet rather than only on its own 15s refresh timer.
  NodeSummary withLivePacket({required DateTime heardAt, double? rssi, double? snr}) {
    return NodeSummary(
      nodeId: nodeId,
      displayName: displayName,
      shortName: shortName,
      hardwareModel: hardwareModel,
      firmwareVersion: firmwareVersion,
      protocol: protocol,
      role: role,
      firstSeen: firstSeen,
      lastHeard: heardAt,
      packetCount: packetCount + 1,
      hasPosition: hasPosition,
      latitude: latitude,
      longitude: longitude,
      altitude: altitude,
      rssi: rssi ?? this.rssi,
      snr: snr ?? this.snr,
      hops: hops,
      captureSource: captureSource,
      battery: battery,
      voltage: voltage,
      temperature: temperature,
      humidity: humidity,
      channelUtil: channelUtil,
      airUtil: airUtil,
    );
  }
}
