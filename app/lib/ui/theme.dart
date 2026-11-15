import 'package:flutter/material.dart';

// Nexonic design tokens: deep navy surfaces, one cyan-to-blue brand gradient, a red live accent.
const background = Color(0xFF070B14);
const background2 = Color(0xFF0A101D);
const surface = Color(0xFF101828);
const surfaceHigh = Color(0xFF172238);
const surfaceTop = Color(0xFF1E2B45);
const stroke = Color(0x1AFFFFFF);
const textPrimary = Color(0xFFEAF0FF);
const textSecondary = Color(0xFF93A0BA);
const textMuted = Color(0xFF64708A);
const accent = Color(0xFF22D3EE);
const accent2 = Color(0xFF3B82F6);
const accent3 = Color(0xFF8B5CF6);
const live = Color(0xFFF43F5E);
const gold = Color(0xFFFBBF24);
const success = Color(0xFF34D399);
const warning = Color(0xFFF59E0B);

const brandGradient = LinearGradient(colors: [accent, accent2], begin: Alignment.topLeft, end: Alignment.bottomRight);

const radiusS = 10.0;
const radiusM = 14.0;
const radiusL = 20.0;

/// A fallback colour pair for an item without artwork, derived from its name so it stays the same everywhere.
(Color, Color) tintFor(String name) {
  const pairs = [
    (Color(0xFF0EA5E9), Color(0xFF6366F1)),
    (Color(0xFF14B8A6), Color(0xFF0EA5E9)),
    (Color(0xFF8B5CF6), Color(0xFFEC4899)),
    (Color(0xFFF59E0B), Color(0xFFEF4444)),
    (Color(0xFF22C55E), Color(0xFF14B8A6)),
    (Color(0xFF3B82F6), Color(0xFF8B5CF6)),
    (Color(0xFFEC4899), Color(0xFFF97316)),
    (Color(0xFF06B6D4), Color(0xFF22C55E)),
  ];
  var h = 0;
  for (final c in name.codeUnits) {
    h = (h * 31 + c) & 0x7fffffff;
  }
  return pairs[h % pairs.length];
}

ThemeData buildTheme() {
  final scheme = ColorScheme.fromSeed(
    seedColor: accent2,
    brightness: Brightness.dark,
    primary: accent,
    onPrimary: const Color(0xFF00141A),
    secondary: accent2,
    surface: surface,
    onSurface: textPrimary,
    surfaceContainerHighest: surfaceHigh,
    outline: stroke,
    error: live,
  );
  const text = TextTheme(
    displaySmall: TextStyle(fontSize: 34, fontWeight: FontWeight.w800, letterSpacing: -0.8, color: textPrimary),
    headlineMedium: TextStyle(fontSize: 26, fontWeight: FontWeight.w800, letterSpacing: -0.5, color: textPrimary),
    headlineSmall: TextStyle(fontSize: 21, fontWeight: FontWeight.w700, letterSpacing: -0.3, color: textPrimary),
    titleLarge: TextStyle(fontSize: 18, fontWeight: FontWeight.w700, letterSpacing: -0.2, color: textPrimary),
    titleMedium: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: textPrimary),
    titleSmall: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: textPrimary),
    bodyLarge: TextStyle(fontSize: 15, color: textPrimary, height: 1.45),
    bodyMedium: TextStyle(fontSize: 13.5, color: textSecondary, height: 1.4),
    bodySmall: TextStyle(fontSize: 12, color: textSecondary),
    labelLarge: TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
    labelMedium: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: textSecondary),
    labelSmall: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w700, letterSpacing: 0.6, color: textSecondary),
  );
  final rounded = RoundedRectangleBorder(borderRadius: BorderRadius.circular(radiusS));
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    textTheme: text,
    scaffoldBackgroundColor: background,
    canvasColor: background,
    splashFactory: InkSparkle.splashFactory,
    visualDensity: VisualDensity.standard,
    dividerTheme: const DividerThemeData(color: stroke, thickness: 1, space: 1),
    appBarTheme: const AppBarTheme(
      backgroundColor: Colors.transparent,
      elevation: 0,
      scrolledUnderElevation: 0,
      titleTextStyle: TextStyle(fontSize: 18, fontWeight: FontWeight.w700, color: textPrimary),
    ),
    cardTheme: CardThemeData(
      color: surface,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(radiusM), side: const BorderSide(color: stroke)),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: background2,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(radiusL), side: const BorderSide(color: stroke)),
    ),
    bottomSheetTheme: const BottomSheetThemeData(
      backgroundColor: background2,
      surfaceTintColor: Colors.transparent,
      showDragHandle: true,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(radiusL))),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: surfaceHigh,
      isDense: true,
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      hintStyle: const TextStyle(color: textMuted),
      labelStyle: const TextStyle(color: textSecondary),
      prefixIconColor: textSecondary,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(radiusS), borderSide: BorderSide.none),
      enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(radiusS), borderSide: const BorderSide(color: stroke)),
      focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(radiusS), borderSide: const BorderSide(color: accent, width: 1.4)),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: accent,
        foregroundColor: const Color(0xFF00141A),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
        shape: rounded,
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: textPrimary,
        side: const BorderSide(color: stroke),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        shape: rounded,
      ),
    ),
    textButtonTheme: TextButtonThemeData(style: TextButton.styleFrom(foregroundColor: accent, shape: rounded)),
    iconButtonTheme: IconButtonThemeData(style: IconButton.styleFrom(foregroundColor: textPrimary)),
    chipTheme: ChipThemeData(
      backgroundColor: surfaceHigh,
      selectedColor: accent.withValues(alpha: 0.18),
      side: const BorderSide(color: stroke),
      labelStyle: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: textPrimary),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
      showCheckmark: false,
      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
    ),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: SegmentedButton.styleFrom(
        backgroundColor: surfaceHigh,
        selectedBackgroundColor: accent.withValues(alpha: 0.18),
        selectedForegroundColor: accent,
        side: const BorderSide(color: stroke),
      ),
    ),
    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? const Color(0xFF00141A) : textSecondary),
      trackColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? accent : surfaceTop),
      trackOutlineColor: const WidgetStatePropertyAll(Colors.transparent),
    ),
    sliderTheme: const SliderThemeData(
      activeTrackColor: accent,
      inactiveTrackColor: Color(0x33FFFFFF),
      thumbColor: Colors.white,
      overlayColor: Color(0x2222D3EE),
      trackHeight: 3,
    ),
    progressIndicatorTheme: const ProgressIndicatorThemeData(color: accent, linearTrackColor: Color(0x22FFFFFF)),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: surfaceTop,
      contentTextStyle: const TextStyle(color: textPrimary),
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(radiusS)),
    ),
    tooltipTheme: TooltipThemeData(
      decoration: BoxDecoration(color: surfaceTop, borderRadius: BorderRadius.circular(8), border: Border.all(color: stroke)),
      textStyle: const TextStyle(color: textPrimary, fontSize: 12),
      waitDuration: const Duration(milliseconds: 500),
    ),
    popupMenuTheme: PopupMenuThemeData(
      color: surfaceHigh,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(radiusM), side: const BorderSide(color: stroke)),
    ),
    menuTheme: MenuThemeData(
      style: MenuStyle(
        backgroundColor: const WidgetStatePropertyAll(surfaceHigh),
        surfaceTintColor: const WidgetStatePropertyAll(Colors.transparent),
        shape: WidgetStatePropertyAll(
            RoundedRectangleBorder(borderRadius: BorderRadius.circular(radiusM), side: const BorderSide(color: stroke))),
      ),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: background2,
      surfaceTintColor: Colors.transparent,
      indicatorColor: accent.withValues(alpha: 0.16),
      height: 68,
      labelTextStyle: WidgetStateProperty.resolveWith((s) => TextStyle(
            fontSize: 11.5,
            fontWeight: FontWeight.w600,
            color: s.contains(WidgetState.selected) ? textPrimary : textSecondary,
          )),
      iconTheme: WidgetStateProperty.resolveWith(
          (s) => IconThemeData(color: s.contains(WidgetState.selected) ? accent : textSecondary, size: 24)),
    ),
    listTileTheme: const ListTileThemeData(iconColor: textSecondary, textColor: textPrimary),
    scrollbarTheme: ScrollbarThemeData(
      thumbColor: WidgetStatePropertyAll(Colors.white.withValues(alpha: 0.16)),
      radius: const Radius.circular(8),
      thickness: const WidgetStatePropertyAll(6),
    ),
  );
}

/// The Nexonic mark: a rounded screen with a play triangle on the brand gradient.
class NexonicLogo extends StatelessWidget {
  const NexonicLogo({super.key, this.size = 32});
  final double size;

  @override
  Widget build(BuildContext context) => Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          gradient: brandGradient,
          borderRadius: BorderRadius.circular(size * 0.28),
          boxShadow: [BoxShadow(color: accent.withValues(alpha: 0.35), blurRadius: size * 0.5, offset: Offset(0, size * 0.1))],
        ),
        child: Icon(Icons.play_arrow_rounded, color: Colors.white, size: size * 0.7),
      );
}

/// Logo plus the product name.
class NexonicWordmark extends StatelessWidget {
  const NexonicWordmark({super.key, this.size = 30});
  final double size;

  @override
  Widget build(BuildContext context) => Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          NexonicLogo(size: size),
          SizedBox(width: size * 0.35),
          Text.rich(
            TextSpan(children: [
              const TextSpan(text: 'Nexonic', style: TextStyle(fontWeight: FontWeight.w800)),
              TextSpan(text: ' IPTV', style: TextStyle(fontWeight: FontWeight.w500, color: textSecondary.withValues(alpha: 0.9))),
            ]),
            style: TextStyle(fontSize: size * 0.56, letterSpacing: -0.3, color: textPrimary),
          ),
        ],
      );
}

/// The app background: deep navy with a soft brand glow in the top corner.
class Backdrop extends StatelessWidget {
  const Backdrop({super.key, required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) => DecoratedBox(
        decoration: const BoxDecoration(
          color: background,
          gradient: RadialGradient(
            center: Alignment(-0.9, -1.1),
            radius: 1.4,
            colors: [Color(0xFF0D2236), background],
            stops: [0, 0.6],
          ),
        ),
        child: child,
      );
}
