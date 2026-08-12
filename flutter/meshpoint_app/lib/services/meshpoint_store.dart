import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../models/meshpoint_server.dart';

/// Holds the configured server list and persists it (name, URL, and the
/// session token together) via the platform keystore/keychain --
/// `flutter_secure_storage`, not `shared_preferences`, since a stored
/// entry here is effectively an admin credential for real radio
/// infrastructure, not app preferences.
///
/// Stored as one JSON blob under a single key rather than one secure-
/// storage entry per server: simplest correct thing for what's
/// realistically a handful of servers (a personal fleet, not hundreds).
class MeshpointStore extends ChangeNotifier {
  // Deliberately left as-is despite the class rename -- this is a
  // persisted on-device storage key. Changing it would silently orphan
  // every existing install's already-saved server list (a fresh read
  // under a new key finds nothing, not an empty-but-recoverable state).
  static const _storageKey = 'meshpoint_servers_v1';
  final _storage = const FlutterSecureStorage();

  List<MeshpointServer> _servers = [];
  bool _loaded = false;

  List<MeshpointServer> get servers => List.unmodifiable(_servers);
  bool get loaded => _loaded;

  Future<void> load() async {
    final raw = await _storage.read(key: _storageKey);
    if (raw != null && raw.isNotEmpty) {
      try {
        final decoded = jsonDecode(raw) as List;
        _servers = decoded
            .whereType<Map<String, dynamic>>()
            .map(MeshpointServer.fromJson)
            .toList();
      } catch (_) {
        // Corrupt/unreadable store -- start fresh rather than crash the
        // app on launch; nothing here is unrecoverable, the user just
        // re-adds servers.
        _servers = [];
      }
    }
    _loaded = true;
    notifyListeners();
  }

  Future<void> _persist() async {
    final raw = jsonEncode(_servers.map((s) => s.toJson()).toList());
    await _storage.write(key: _storageKey, value: raw);
  }

  Future<MeshpointServer> addServer({
    required String name,
    required String baseUrl,
  }) async {
    final server = MeshpointServer(
      id: _generateId(),
      name: name,
      baseUrl: baseUrl,
    );
    _servers.add(server);
    await _persist();
    notifyListeners();
    return server;
  }

  Future<void> removeServer(String id) async {
    _servers.removeWhere((s) => s.id == id);
    await _persist();
    notifyListeners();
  }

  /// Called after a successful login (or a status refresh) to persist
  /// whatever changed on an existing [MeshpointServer] instance --
  /// callers mutate the object in place (it's already the one held in
  /// [_servers]), this just writes the updated list through.
  Future<void> save() async {
    await _persist();
    notifyListeners();
  }

  String _generateId() {
    final rnd = Random.secure();
    return List.generate(16, (_) => rnd.nextInt(16).toRadixString(16)).join();
  }
}
