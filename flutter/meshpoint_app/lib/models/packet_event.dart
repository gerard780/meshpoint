/// One live packet, pushed over `/ws` as `{"type": "packet", "data": ...}`
/// (`Packet.to_dict()` in `src/models/packet.py`).
class PacketEvent {
  final String packetId;
  final String sourceId;
  final String destinationId;
  final String protocol;
  final String packetType;
  final double? rssi;
  final double? snr;
  final DateTime timestamp;

  PacketEvent({
    required this.packetId,
    required this.sourceId,
    required this.destinationId,
    required this.protocol,
    required this.packetType,
    this.rssi,
    this.snr,
    required this.timestamp,
  });

  factory PacketEvent.fromJson(Map<String, dynamic> json) {
    final signal = json['signal'] as Map<String, dynamic>?;
    final ts = json['timestamp'] as String?;
    return PacketEvent(
      packetId: json['packet_id'] as String? ?? '',
      sourceId: json['source_id'] as String? ?? '?',
      destinationId: json['destination_id'] as String? ?? '?',
      protocol: json['protocol'] as String? ?? '?',
      packetType: json['packet_type'] as String? ?? '?',
      rssi: (signal?['rssi'] as num?)?.toDouble(),
      snr: (signal?['snr'] as num?)?.toDouble(),
      timestamp: ts != null ? (DateTime.tryParse(ts) ?? DateTime.now()) : DateTime.now(),
    );
  }
}
