/// A configured meshpoint deployment the app knows about.
///
/// `token` is the bearer JWT returned by `POST /api/auth/login` when the
/// request identifies itself as a non-browser client (see
/// `src/api/routes/auth_routes.py`'s `X-Meshpoint-Client` handling) --
/// null until the user logs in, matching every other field that's only
/// known once a login has actually succeeded.
class MeshpointServer {
  final String id;
  String name;
  String baseUrl;
  String? token;
  String? role;

  // Cached from the last successful status/identity fetch, purely for
  // the server-list screen's summary tile -- never trusted as the
  // source of truth, just "what we last saw."
  String? lastKnownVersion;
  int? lastKnownNodeCount;
  bool lastSeenOnline;

  MeshpointServer({
    required this.id,
    required this.name,
    required this.baseUrl,
    this.token,
    this.role,
    this.lastKnownVersion,
    this.lastKnownNodeCount,
    this.lastSeenOnline = false,
  });

  bool get isLoggedIn => token != null && token!.isNotEmpty;

  /// Normalized, no trailing slash -- every ApiClient call appends its
  /// own leading `/api/...` path.
  String get normalizedBaseUrl =>
      baseUrl.endsWith('/') ? baseUrl.substring(0, baseUrl.length - 1) : baseUrl;

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'baseUrl': baseUrl,
        'token': token,
        'role': role,
        'lastKnownVersion': lastKnownVersion,
        'lastKnownNodeCount': lastKnownNodeCount,
        'lastSeenOnline': lastSeenOnline,
      };

  factory MeshpointServer.fromJson(Map<String, dynamic> json) => MeshpointServer(
        id: json['id'] as String,
        name: json['name'] as String,
        baseUrl: json['baseUrl'] as String,
        token: json['token'] as String?,
        role: json['role'] as String?,
        lastKnownVersion: json['lastKnownVersion'] as String?,
        lastKnownNodeCount: json['lastKnownNodeCount'] as int?,
        lastSeenOnline: json['lastSeenOnline'] as bool? ?? false,
      );
}
