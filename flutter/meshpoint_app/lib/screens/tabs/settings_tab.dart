import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../services/active_meshpoint_controller.dart';
import '../../services/meshpoint_store.dart';
import '../../services/theme_store.dart';
import '../../theme/meshpoint_theme.dart';

/// App-wide preferences: theme (moved here from the old AppBar menu
/// button) and managing the currently active meshpoint's session.
class SettingsTab extends StatelessWidget {
  const SettingsTab({super.key});

  @override
  Widget build(BuildContext context) {
    final themeStore = context.watch<ThemeStore>();
    final activeController = context.watch<ActiveMeshpointController>();

    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(
        children: [
          const _SectionHeader('Theme'),
          ...MeshpointThemeName.values.map(
            (name) => RadioListTile<MeshpointThemeName>(
              title: Text(name.label),
              value: name,
              groupValue: themeStore.current,
              onChanged: (v) {
                if (v != null) context.read<ThemeStore>().setTheme(v);
              },
            ),
          ),
          if (activeController.active != null) ...[
            const Divider(height: 32),
            const _SectionHeader('Active meshpoint'),
            ListTile(
              leading: const Icon(Icons.dns),
              title: Text(activeController.active!.name),
              subtitle: const Text('Log out to disconnect this app from it'),
              trailing: TextButton(
                onPressed: () => _logOut(context, activeController),
                child: const Text('Log out'),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Future<void> _logOut(BuildContext context, ActiveMeshpointController controller) async {
    final meshpoint = controller.active;
    if (meshpoint == null) return;
    meshpoint.token = null;
    meshpoint.role = null;
    await context.read<MeshpointStore>().save();
    controller.clear();
  }
}

class _SectionHeader extends StatelessWidget {
  final String title;
  const _SectionHeader(this.title);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
      child: Text(
        title.toUpperCase(),
        style: TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w700,
          letterSpacing: 0.5,
          color: Theme.of(context).colorScheme.primary,
        ),
      ),
    );
  }
}
