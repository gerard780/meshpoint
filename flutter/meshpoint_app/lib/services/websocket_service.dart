import 'dart:async';
import 'dart:convert';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../models/packet_event.dart';

/// Live connection to one server's `/ws` endpoint. Decodes only the
/// `packet` event type for now (v1 scope is the live packet feed);
/// the other broadcast types this same socket carries
/// (`message_received`/`message_updated`/`noise_floor`/`reticulum_peer`/
/// `reticulum_message` -- see `memory/project_meshpoint_app.md` for the
/// full catalog, confirmed by grepping every real `.broadcast(` call
/// site) are simply ignored for now, not errors.
class WebSocketService {
  WebSocketChannel? _channel;
  StreamController<PacketEvent>? _controller;

  Stream<PacketEvent> connect(Uri wsUri) {
    disconnect();
    final controller = StreamController<PacketEvent>.broadcast();
    _controller = controller;
    final channel = WebSocketChannel.connect(wsUri);
    _channel = channel;
    channel.stream.listen(
      (raw) {
        try {
          final decoded = jsonDecode(raw as String);
          if (decoded is Map<String, dynamic> && decoded['type'] == 'packet') {
            final data = decoded['data'];
            if (data is Map<String, dynamic>) {
              controller.add(PacketEvent.fromJson(data));
            }
          }
        } catch (_) {
          // Malformed/unexpected frame -- drop it, keep the connection.
        }
      },
      onError: (_) => controller.addError('connection error'),
      onDone: () => controller.close(),
      cancelOnError: false,
    );
    return controller.stream;
  }

  void disconnect() {
    _channel?.sink.close();
    _channel = null;
    _controller?.close();
    _controller = null;
  }
}
