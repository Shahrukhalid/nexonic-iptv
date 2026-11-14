import 'package:flutter/material.dart';

const accent = Color(0xFF22D3EE);
const accent2 = Color(0xFF3B82F6);
const background = Color(0xFF060A13);
const surface = Color(0xFF0E1524);

ThemeData buildTheme() {
  final scheme = ColorScheme.fromSeed(
    seedColor: accent2,
    brightness: Brightness.dark,
    primary: accent,
    secondary: accent2,
    surface: surface,
  );
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: background,
    canvasColor: background,
    appBarTheme: const AppBarTheme(backgroundColor: background, elevation: 0, scrolledUnderElevation: 0),
    cardTheme: CardThemeData(
      color: surface,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: surface,
      isDense: true,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
    ),
    navigationRailTheme: const NavigationRailThemeData(backgroundColor: background),
  );
}

/// The Nexonic mark: a screen with a play triangle, in the brand gradient.
class NexonicLogo extends StatelessWidget {
  const NexonicLogo({super.key, this.size = 28});
  final double size;

  @override
  Widget build(BuildContext context) {
    return ShaderMask(
      shaderCallback: (r) => const LinearGradient(colors: [accent, accent2]).createShader(r),
      child: Icon(Icons.smart_display_rounded, size: size, color: Colors.white),
    );
  }
}
