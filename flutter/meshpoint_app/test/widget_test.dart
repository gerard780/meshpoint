// Basic smoke test: the app boots and shows the fleet's empty state
// (no servers configured yet) without crashing. Flutter's default
// counter-app test was removed since MyApp/MyHomePage no longer exist
// -- see lib/main.dart.
//
// flutter_secure_storage has no real platform implementation in the bare
// `flutter test` VM environment, so its method channel is mocked here
// (matching the plugin's own channel name/method signatures, confirmed
// by reading flutter_secure_storage_platform_interface's source
// directly) -- this exercises ServerStore.load()'s actual code path for
// real, rather than just avoiding pumpAndSettle timing out on a channel
// call that would otherwise never return in this environment.

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:meshpoint_app/main.dart';
import 'package:meshpoint_app/screens/splash_screen.dart';
import 'package:meshpoint_app/theme/meshpoint_theme.dart';

void main() {
  const channel = MethodChannel('plugins.it_nomads.com/flutter_secure_storage');

  setUp(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      switch (call.method) {
        case 'read':
          return null; // no servers stored yet, matches a fresh install
        case 'readAll':
          return <String, String>{};
        case 'write':
        case 'delete':
        case 'deleteAll':
          return null;
        default:
          return null;
      }
    });
  });

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  testWidgets('Splash screen shows first, then the fleet screen', (WidgetTester tester) async {
    await tester.pumpWidget(const MeshpointApp());

    // Before anything has settled, the splash screen (real widget, not a
    // no-op passthrough) is what's actually on screen -- ServerStore.load()
    // hasn't resolved yet at this exact point, even against a mocked
    // channel, since it's still a real async call.
    expect(find.byType(SplashScreen), findsOneWidget);
    expect(find.byType(Image), findsOneWidget);
    expect(find.text('Meshpoint Fleet Manager'), findsOneWidget);

    await tester.pumpAndSettle();

    // And once loading finishes, it hands off to the real fleet screen.
    expect(find.byType(SplashScreen), findsNothing);
    expect(find.text('Meshpoint Fleet Manager'), findsOneWidget);
    expect(find.text('No meshpoint servers yet'), findsOneWidget);
    // Two by design: the empty-state's own "Add your first server"
    // button, plus the screen's persistent FloatingActionButton.
    expect(find.byIcon(Icons.add), findsNWidgets(2));
    expect(find.byType(FloatingActionButton), findsOneWidget);
  });

  test('Light theme actually carries Brightness.light through to ThemeData', () {
    // The other three palettes rely on MeshpointPalette's default
    // (Brightness.dark) -- this only proves anything for the one palette
    // that overrides it.
    expect(MeshpointPalette.light.brightness, Brightness.light);
    expect(MeshpointPalette.dark.brightness, Brightness.dark);

    final lightTheme = buildMeshpointTheme(MeshpointPalette.light);
    expect(lightTheme.brightness, Brightness.light);
    expect(lightTheme.scaffoldBackgroundColor, MeshpointPalette.light.bgPrimary);

    final darkTheme = buildMeshpointTheme(MeshpointPalette.dark);
    expect(darkTheme.brightness, Brightness.dark);
  });
}
