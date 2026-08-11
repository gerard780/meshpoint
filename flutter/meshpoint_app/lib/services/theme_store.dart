import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../theme/meshpoint_theme.dart';

/// Persists the chosen theme -- reuses the same secure-storage instance
/// the server list already depends on rather than pulling in
/// shared_preferences for one extra non-sensitive value.
class ThemeStore extends ChangeNotifier {
  static const _storageKey = 'meshpoint_theme_v1';
  final _storage = const FlutterSecureStorage();

  MeshpointThemeName _current = MeshpointThemeName.dark;
  MeshpointThemeName get current => _current;

  Future<void> load() async {
    final raw = await _storage.read(key: _storageKey);
    _current = MeshpointThemeNameLabel.fromStorageKey(raw);
    notifyListeners();
  }

  Future<void> setTheme(MeshpointThemeName name) async {
    _current = name;
    await _storage.write(key: _storageKey, value: name.storageKey);
    notifyListeners();
  }

  /// Same order the web app's own `ThemeController.cycle()` uses.
  Future<void> cycle() async {
    const order = [
      MeshpointThemeName.dark,
      MeshpointThemeName.highContrast,
      MeshpointThemeName.sunlight,
    ];
    final next = order[(order.indexOf(_current) + 1) % order.length];
    await setTheme(next);
  }
}
