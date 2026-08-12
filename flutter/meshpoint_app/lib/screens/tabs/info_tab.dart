import 'package:flutter/material.dart';

/// App-level about screen -- version, what this app is for. Deliberately
/// static text, no `package_info_plus` dependency added just for a
/// version string (v1 scope, and this session already had enough grief
/// from native-platform-touching packages) -- keep the version below in
/// sync with `pubspec.yaml`'s `version:` by hand.
class InfoTab extends StatelessWidget {
  const InfoTab({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Info')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(16),
            child: Image.asset('assets/icon/icon.png', width: 72, height: 72),
          ),
          const SizedBox(height: 12),
          const Text('Meshpoint Manager', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600)),
          Text('Version 0.7.9', style: TextStyle(color: Theme.of(context).colorScheme.outline)),
          const SizedBox(height: 16),
          const Text(
            'Manage and view multiple meshpoint deployments from one app -- '
            'status, live node roster, and a real-time packet feed for each '
            'meshpoint in your fleet.',
          ),
        ],
      ),
    );
  }
}
