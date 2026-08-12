import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'screens/home_shell.dart';
import 'screens/splash_screen.dart';
import 'services/active_meshpoint_controller.dart';
import 'services/meshpoint_store.dart';
import 'services/tab_index_controller.dart';
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
        ChangeNotifierProvider(create: (_) => MeshpointStore()..load()),
        ChangeNotifierProvider(create: (_) => ThemeStore()..load()),
        ChangeNotifierProvider(create: (_) => TabIndexController()),
        // Reads MeshpointStore via context.read -- safe here since it's
        // declared earlier in this same provider list, so it already
        // exists by the time this `create` callback runs.
        ChangeNotifierProvider(create: (context) => ActiveMeshpointController(context.read<MeshpointStore>())),
      ],
      child: Consumer<ThemeStore>(
        builder: (context, themeStore, _) {
          return MaterialApp(
            title: 'Meshpoint Manager',
            theme: buildMeshpointTheme(MeshpointPalette.forTheme(themeStore.current)),
            home: Consumer<MeshpointStore>(
              builder: (context, meshpointStore, _) {
                return meshpointStore.loaded ? const HomeShell() : const SplashScreen();
              },
            ),
          );
        },
      ),
    );
  }
}
