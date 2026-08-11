import 'package:flutter/material.dart';

import '../theme/meshpoint_theme.dart';

/// Shown while `ServerStore.load()` (a real, if usually fast, secure-
/// storage read) is in flight. Android/iOS also get a genuine native
/// splash (see flutter_native_splash.yaml -- that one paints before the
/// Flutter engine has even started, closing the gap this widget can't
/// reach) but macOS/Windows/Linux have no OS-level splash concept at
/// all, so this is what actually shows there -- the platform the app
/// has been live-tested on so far.
///
/// Deliberately dumb: doesn't know about [ServerStore] or decide
/// anything itself -- `MeshpointApp` picks between this and
/// [StartScreen] directly, so the two are genuinely mutually exclusive
/// in the tree instead of one silently wrapping the other.
class SplashScreen extends StatelessWidget {
  const SplashScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final palette = MeshpointPalette.dark;

    return Scaffold(
      backgroundColor: palette.bgPrimary,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(24),
              child: Image.asset(
                'assets/icon/icon.png',
                width: 128,
                height: 128,
              ),
            ),
            const SizedBox(height: 20),
            Text(
              'Meshpoint Fleet Manager',
              style: TextStyle(
                color: palette.textPrimary,
                fontSize: 18,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 24),
            SizedBox(
              width: 28,
              height: 28,
              child: CircularProgressIndicator(
                strokeWidth: 2.5,
                color: palette.accentCyan,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
