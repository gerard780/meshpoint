import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/tab_index_controller.dart';
import 'tabs/info_tab.dart';
import 'tabs/meshpoints_tab.dart';
import 'tabs/nodes_tab.dart';
import 'tabs/packets_tab.dart';
import 'tabs/settings_tab.dart';

/// The app's persistent shell once the meshpoint list has loaded: a
/// bottom [NavigationBar] over an [IndexedStack] of the 5 top-level
/// sections (Meshpoints, Nodes, Packets, Settings, Info).
/// `MeshpointApp` picks between this and [SplashScreen] directly, same
/// as it used to pick between [SplashScreen] and the old `StartScreen`.
///
/// [IndexedStack], not a [PageView]/route push per tab: Nodes and
/// Packets both read from [ActiveMeshpointController], which holds a
/// live websocket connection and a 15s reconciliation timer -- those
/// need to keep running when the user is looking at a different tab,
/// not get torn down and rebuilt on every switch.
class HomeShell extends StatelessWidget {
  const HomeShell({super.key});

  static const _tabs = [
    MeshpointsTab(),
    NodesTab(),
    PacketsTab(),
    SettingsTab(),
    InfoTab(),
  ];

  @override
  Widget build(BuildContext context) {
    final tabIndex = context.watch<TabIndexController>();

    return Scaffold(
      body: IndexedStack(index: tabIndex.index, children: _tabs),
      bottomNavigationBar: NavigationBar(
        selectedIndex: tabIndex.index,
        onDestinationSelected: (i) => context.read<TabIndexController>().setIndex(i),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.dns_outlined),
            selectedIcon: Icon(Icons.dns),
            label: 'Meshpoints',
          ),
          NavigationDestination(
            icon: Icon(Icons.hub_outlined),
            selectedIcon: Icon(Icons.hub),
            label: 'Nodes',
          ),
          NavigationDestination(
            icon: Icon(Icons.podcasts_outlined),
            selectedIcon: Icon(Icons.podcasts),
            label: 'Packets',
          ),
          NavigationDestination(
            icon: Icon(Icons.settings_outlined),
            selectedIcon: Icon(Icons.settings),
            label: 'Settings',
          ),
          NavigationDestination(
            icon: Icon(Icons.info_outline),
            selectedIcon: Icon(Icons.info),
            label: 'Info',
          ),
        ],
      ),
    );
  }
}
