import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'screens/start_screen.dart';
import 'services/server_store.dart';

void main() {
  runApp(const MeshpointApp());
}

class MeshpointApp extends StatelessWidget {
  const MeshpointApp({super.key});

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider(
      create: (_) => ServerStore()..load(),
      child: MaterialApp(
        title: 'Meshpoint',
        theme: ThemeData(
          colorScheme: ColorScheme.fromSeed(seedColor: Colors.cyan, brightness: Brightness.light),
          useMaterial3: true,
        ),
        darkTheme: ThemeData(
          colorScheme: ColorScheme.fromSeed(seedColor: Colors.cyan, brightness: Brightness.dark),
          useMaterial3: true,
        ),
        home: const StartScreen(),
      ),
    );
  }
}
