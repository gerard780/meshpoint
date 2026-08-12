import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/tab_index_controller.dart';

/// Shown by the Nodes/Packets tabs when no meshpoint is currently
/// active -- they're shared tabs now (not per-meshpoint screens), so
/// they need somewhere to point the user before there's any data to
/// show.
class NoActiveMeshpointNotice extends StatelessWidget {
  const NoActiveMeshpointNotice({super.key});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.dns_outlined, size: 64, color: Colors.grey),
          const SizedBox(height: 16),
          const Text('No active meshpoint'),
          const SizedBox(height: 8),
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 32),
            child: Text(
              'Pick a meshpoint, then "Switch to this meshpoint" to see its data here.',
              textAlign: TextAlign.center,
            ),
          ),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: () => context.read<TabIndexController>().setIndex(0),
            icon: const Icon(Icons.dns),
            label: const Text('Go to Meshpoints'),
          ),
        ],
      ),
    );
  }
}
