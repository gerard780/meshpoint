import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'screens/splash_screen.dart';
import 'screens/start_screen.dart';
import 'services/server_store.dart';
import 'services/theme_store.dart';
import 'theme/meshpoint_theme.dart';

void main() {
  runApp(const MeshpointApp());
}

class MeshpointApp extends StatelessWidget {
  const MeshpointApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => ServerStore()..load()),
        ChangeNotifierProvider(create: (_) => ThemeStore()..load()),
      ],
      child: Consumer<ThemeStore>(
        builder: (context, themeStore, _) {
          return MaterialApp(
            title: 'Meshpoint Manager',
            theme: buildMeshpointTheme(MeshpointPalette.forTheme(themeStore.current)),
            home: Consumer<ServerStore>(
              builder: (context, serverStore, _) {
                return serverStore.loaded ? const StartScreen() : const SplashScreen();
              },
            ),
          );
        },
      ),
    );
  }
}
