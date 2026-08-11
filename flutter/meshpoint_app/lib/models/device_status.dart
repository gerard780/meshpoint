/// Mirrors `GET /api/device/status`'s exact response shape
/// (`src/api/routes/device.py::device_status()`).
class DeviceStatus {
  final String status;
  final int uptimeSeconds;
  final int websocketClients;
  final String deviceId;
  final String? deviceName;
  final String? longName;
  final String firmwareVersion;

  DeviceStatus({
    required this.status,
    required this.uptimeSeconds,
    required this.websocketClients,
    required this.deviceId,
    this.deviceName,
    this.longName,
    required this.firmwareVersion,
  });

  factory DeviceStatus.fromJson(Map<String, dynamic> json) => DeviceStatus(
        status: json['status'] as String? ?? 'unknown',
        uptimeSeconds: (json['uptime_seconds'] as num?)?.toInt() ?? 0,
        websocketClients: (json['websocket_clients'] as num?)?.toInt() ?? 0,
        deviceId: json['device_id'] as String? ?? '',
        deviceName: json['device_name'] as String?,
        longName: json['long_name'] as String?,
        firmwareVersion: json['firmware_version'] as String? ?? '?',
      );

  String get uptimeLabel {
    final d = uptimeSeconds ~/ 86400;
    final h = (uptimeSeconds % 86400) ~/ 3600;
    final m = (uptimeSeconds % 3600) ~/ 60;
    if (d > 0) return '${d}d ${h}h';
    if (h > 0) return '${h}h ${m}m';
    return '${m}m';
  }
}
