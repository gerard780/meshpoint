import 'package:flutter/material.dart';

/// The web dashboard's own three named themes -- not invented here,
/// read directly from `frontend/js/theme_controller.js` (`dark` /
/// `high-contrast` / `sunlight`) and their real color values from
/// `frontend/css/dashboard.css` (`:root`, the base "dark" palette) and
/// `frontend/css/theme_high_contrast.css` (the other two, which only
/// override a subset of variables -- anything not overridden there
/// falls back to the dark palette's own value, same as the CSS itself
/// does via custom-property cascade).
enum MeshpointThemeName { dark, highContrast, sunlight }

extension MeshpointThemeNameLabel on MeshpointThemeName {
  String get label => switch (this) {
        MeshpointThemeName.dark => 'Dark',
        MeshpointThemeName.highContrast => 'High contrast',
        MeshpointThemeName.sunlight => 'Sunlight',
      };

  static MeshpointThemeName fromStorageKey(String? key) => switch (key) {
        'high-contrast' => MeshpointThemeName.highContrast,
        'sunlight' => MeshpointThemeName.sunlight,
        _ => MeshpointThemeName.dark,
      };

  /// Matches `ThemeController`'s own `localStorage` value spelling, in
  /// case the two apps ever need to compare notes on a shared device.
  String get storageKey => switch (this) {
        MeshpointThemeName.dark => 'dark',
        MeshpointThemeName.highContrast => 'high-contrast',
        MeshpointThemeName.sunlight => 'sunlight',
      };
}

class MeshpointPalette {
  final Color bgPrimary;
  final Color bgSecondary;
  final Color bgCard;
  final Color border;
  final Color textPrimary;
  final Color textSecondary;
  final Color textMuted;
  final Color accentCyan;
  final Color accentGreen;
  final Color accentAmber;
  final Color accentRed;
  final Color accentPurple;
  final Color accentBlue;

  const MeshpointPalette({
    required this.bgPrimary,
    required this.bgSecondary,
    required this.bgCard,
    required this.border,
    required this.textPrimary,
    required this.textSecondary,
    required this.textMuted,
    required this.accentCyan,
    required this.accentGreen,
    required this.accentAmber,
    required this.accentRed,
    required this.accentPurple,
    required this.accentBlue,
  });

  // dashboard.css's `:root` -- the base palette every other theme
  // partially overrides.
  static const dark = MeshpointPalette(
    bgPrimary: Color(0xFF0A0E17),
    bgSecondary: Color(0xFF111827),
    bgCard: Color(0xFF162033),
    border: Color(0xFF233049),
    textPrimary: Color(0xFFE2E8F0),
    textSecondary: Color(0xFF94A3B8),
    textMuted: Color(0xFF64748B),
    accentCyan: Color(0xFF06B6D4),
    accentGreen: Color(0xFF00E5A0),
    accentAmber: Color(0xFFF59E0B),
    accentRed: Color(0xFFEF4444),
    accentPurple: Color(0xFFA855F7),
    accentBlue: Color(0xFF3B82F6),
  );

  // theme_high_contrast.css's `[data-theme="high-contrast"]` block.
  // bgCard/border/accentPurple/accentBlue aren't overridden there, so
  // they carry over from `dark`, matching the real CSS cascade.
  static const highContrast = MeshpointPalette(
    bgPrimary: Color(0xFF04060C),
    bgSecondary: Color(0xFF0B1424),
    bgCard: Color(0xFF162033),
    border: Color(0xFF233049),
    textPrimary: Color(0xFFFFFFFF),
    textSecondary: Color(0xFFE6F1FF),
    textMuted: Color(0xFFC0D0E8),
    accentCyan: Color(0xFF5FEAFF),
    accentGreen: Color(0xFF5DFFC1),
    accentAmber: Color(0xFFFFC857),
    accentRed: Color(0xFFFF7A7A),
    accentPurple: Color(0xFFA855F7),
    accentBlue: Color(0xFF3B82F6),
  );

  // theme_high_contrast.css's `[data-theme="sunlight"]` block -- same
  // "only the listed variables change" cascade behavior as above.
  static const sunlight = MeshpointPalette(
    bgPrimary: Color(0xFF0A1224),
    bgSecondary: Color(0xFF14213B),
    bgCard: Color(0xFF162033),
    border: Color(0xFF233049),
    textPrimary: Color(0xFFF7FBFF),
    textSecondary: Color(0xFFD6E5FF),
    textMuted: Color(0xFF93A4C1),
    accentCyan: Color(0xFF00F5FF),
    accentGreen: Color(0xFF00FFA8),
    accentAmber: Color(0xFFFFD166),
    accentRed: Color(0xFFFF6B6B),
    accentPurple: Color(0xFFA855F7),
    accentBlue: Color(0xFF3B82F6),
  );

  static MeshpointPalette forTheme(MeshpointThemeName name) => switch (name) {
        MeshpointThemeName.dark => dark,
        MeshpointThemeName.highContrast => highContrast,
        MeshpointThemeName.sunlight => sunlight,
      };
}

/// Builds a real Flutter [ThemeData] from a [MeshpointPalette]. All
/// three are dark-mode-ish variants (the web app's own "sunlight" theme
/// is still a dark background, just brighter/higher-contrast for
/// outdoor readability -- see theme_high_contrast.css's own comment),
/// so every one of these uses `Brightness.dark` as its base.
ThemeData buildMeshpointTheme(MeshpointPalette p) {
  final colorScheme = ColorScheme.fromSeed(
    seedColor: p.accentCyan,
    brightness: Brightness.dark,
    primary: p.accentCyan,
    secondary: p.accentPurple,
    error: p.accentRed,
    surface: p.bgCard,
  );

  return ThemeData(
    useMaterial3: true,
    brightness: Brightness.dark,
    colorScheme: colorScheme,
    scaffoldBackgroundColor: p.bgPrimary,
    canvasColor: p.bgPrimary,
    cardColor: p.bgCard,
    dividerColor: p.border,
    appBarTheme: AppBarTheme(
      backgroundColor: p.bgSecondary,
      foregroundColor: p.textPrimary,
      elevation: 0,
    ),
    textTheme: ThemeData.dark().textTheme.apply(
          bodyColor: p.textPrimary,
          displayColor: p.textPrimary,
        ),
    listTileTheme: ListTileThemeData(
      textColor: p.textPrimary,
      iconColor: p.textSecondary,
    ),
    cardTheme: CardThemeData(
      color: p.bgCard,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(8),
        side: BorderSide(color: p.border),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: p.bgSecondary,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(6),
        borderSide: BorderSide(color: p.border),
      ),
    ),
    floatingActionButtonTheme: FloatingActionButtonThemeData(
      backgroundColor: p.accentCyan,
      foregroundColor: p.bgPrimary,
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: p.accentCyan,
        foregroundColor: p.bgPrimary,
      ),
    ),
  );
}
