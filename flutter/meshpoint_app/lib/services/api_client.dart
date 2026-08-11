import 'dart:convert';
import 'package:http/http.dart' as http;

import '../models/device_status.dart';
import '../models/node_summary.dart';

/// Thrown for any non-2xx response; carries the server's own `detail`
/// string when present (e.g. "invalid_credentials", "locked_out") so
/// screens can show a real message instead of a bare status code.
class ApiException implements Exception {
  final int statusCode;
  final String detail;
  ApiException(this.statusCode, this.detail);

  @override
  String toString() => detail;
}

class LoginResult {
  final String role;
  final String token;
  LoginResult({required this.role, required this.token});
}

/// One instance per configured server. Pure bearer-token auth -- no
/// cookie jar -- matching `src/api/auth/dependencies.py`'s documented
/// `Authorization: Bearer <jwt>` path for non-browser clients, and
/// `POST /api/auth/login`'s `X-Meshpoint-Client` gated token-in-body
/// response (see `src/api/routes/auth_routes.py`).
class ApiClient {
  final String baseUrl;
  String? token;

  ApiClient({required this.baseUrl, this.token});

  Uri _uri(String path, [Map<String, String>? query]) =>
      Uri.parse('$baseUrl$path').replace(queryParameters: query);

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        'X-Meshpoint-Client': 'app',
        if (token != null && token!.isNotEmpty) 'Authorization': 'Bearer $token',
      };

  Map<String, dynamic> _decodeOrThrow(http.Response res) {
    Map<String, dynamic> body = {};
    if (res.body.isNotEmpty) {
      try {
        final decoded = jsonDecode(res.body);
        if (decoded is Map<String, dynamic>) body = decoded;
      } catch (_) {
        // Non-JSON body (e.g. a proxy error page) -- fall through to the
        // generic status-code message below.
      }
    }
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw ApiException(
        res.statusCode,
        (body['detail'] as String?) ?? 'HTTP ${res.statusCode}',
      );
    }
    return body;
  }

  /// `GET /api/identity` is intentionally unauthenticated -- good first
  /// call when adding a server, to confirm the URL is really a
  /// meshpoint box before ever asking for credentials.
  Future<Map<String, dynamic>> getIdentity() async {
    final res = await http.get(_uri('/api/identity'), headers: _headers);
    return _decodeOrThrow(res);
  }

  Future<LoginResult> login(String username, String password) async {
    final res = await http.post(
      _uri('/api/auth/login'),
      headers: _headers,
      body: jsonEncode({'username': username, 'password': password}),
    );
    final body = _decodeOrThrow(res);
    final tok = body['token'] as String?;
    if (tok == null || tok.isEmpty) {
      // Shouldn't happen given X-Meshpoint-Client is always sent above,
      // but fail loudly rather than silently caching an empty token.
      throw ApiException(500, 'server did not return a session token');
    }
    token = tok;
    return LoginResult(role: body['role'] as String? ?? 'viewer', token: tok);
  }

  Future<DeviceStatus> getDeviceStatus() async {
    final res = await http.get(_uri('/api/device/status'), headers: _headers);
    return DeviceStatus.fromJson(_decodeOrThrow(res));
  }

  Future<List<NodeSummary>> getNodes({int limit = 200}) async {
    final res = await http.get(
      _uri('/api/nodes', {'limit': '$limit'}),
      headers: _headers,
    );
    if (res.statusCode < 200 || res.statusCode >= 300) {
      _decodeOrThrow(res); // throws with the right detail
    }
    final decoded = jsonDecode(res.body);
    if (decoded is! List) return [];
    return decoded
        .whereType<Map<String, dynamic>>()
        .map(NodeSummary.fromJson)
        .toList();
  }

  /// `ws://`/`wss://` form of [baseUrl], with the bearer token as a
  /// `?token=` query param -- the query-param fallback
  /// `src/api/auth/ws_guard.py` already supports for exactly this case
  /// (a plain WebSocket handshake can't carry a custom Authorization
  /// header the way a REST call can).
  Uri websocketUri() {
    final httpUri = Uri.parse(baseUrl);
    final scheme = httpUri.scheme == 'https' ? 'wss' : 'ws';
    return httpUri.replace(
      scheme: scheme,
      path: '/ws',
      queryParameters: token != null ? {'token': token!} : null,
    );
  }
}
