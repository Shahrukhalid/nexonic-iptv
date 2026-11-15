import 'package:flutter/material.dart';

import '../catalog.dart';
import '../sources.dart';
import 'sources_page.dart';
import 'theme.dart';
import 'widgets.dart';

/// First start: free channels right away, or the user's own playlist.
class WelcomePage extends StatelessWidget {
  const WelcomePage({super.key, required this.catalog, required this.onDone});
  final Catalog catalog;
  final VoidCallback onDone;

  Future<void> _finish() async {
    catalog.settings.welcomed = true;
    await catalog.saveSettings();
    onDone();
  }

  @override
  Widget build(BuildContext context) {
    final narrow = MediaQuery.sizeOf(context).width < 720;
    final free = catalog.source('nexonic');
    final cards = [
      _Choice(
        icon: Icons.live_tv_rounded,
        gradient: true,
        title: 'Start with free TV',
        text: 'Thousands of free-to-air channels, films, radio stations and open media, checked every day.',
        button: 'Start watching',
        onTap: () async {
          if (free != null && !free.enabled) await catalog.setEnabled(free, true);
          await _finish();
        },
      ),
      _Choice(
        icon: Icons.playlist_add_rounded,
        title: 'Add my own playlist',
        text: 'Use an M3U link, an M3U file or an Xtream Codes login from your provider.',
        button: 'Add playlist',
        onTap: () async {
          await showDialog<void>(
            context: context,
            barrierDismissible: false,
            builder: (_) => SourceEditor(catalog: catalog, initialType: SourceType.xtream),
          );
          if (catalog.sources.length > 1) await _finish();
        },
      ),
    ];
    return Scaffold(
      body: Backdrop(
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 860),
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  const NexonicLogo(size: 72),
                  const SizedBox(height: 24),
                  Text('Welcome to Nexonic IPTV', textAlign: TextAlign.center,
                      style: narrow ? Theme.of(context).textTheme.headlineMedium : Theme.of(context).textTheme.displaySmall),
                  const SizedBox(height: 10),
                  Text('Live TV, films and radio in one modern player for Windows, macOS and Android.',
                      textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodyLarge?.copyWith(color: textSecondary)),
                  const SizedBox(height: 36),
                  if (narrow)
                    Column(children: [cards[0], const SizedBox(height: 14), cards[1]])
                  else
                    IntrinsicHeight(child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [Expanded(child: cards[0]), const SizedBox(width: 18), Expanded(child: cards[1])])),
                  const SizedBox(height: 22),
                  Text('You can change this any time in Playlists.', style: Theme.of(context).textTheme.bodySmall),
                ]),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _Choice extends StatelessWidget {
  const _Choice({required this.icon, required this.title, required this.text, required this.button, required this.onTap, this.gradient = false});
  final IconData icon;
  final String title;
  final String text;
  final String button;
  final VoidCallback onTap;
  final bool gradient;

  @override
  Widget build(BuildContext context) => Tappable(
        radius: radiusL,
        scale: 1.02,
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.all(26),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(radiusL),
            border: Border.all(color: gradient ? accent.withValues(alpha: 0.45) : stroke),
            gradient: gradient
                ? LinearGradient(colors: [accent.withValues(alpha: 0.16), accent2.withValues(alpha: 0.08), surface], begin: Alignment.topLeft, end: Alignment.bottomRight)
                : null,
            color: gradient ? null : surface,
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Container(
              width: 52,
              height: 52,
              decoration: BoxDecoration(gradient: gradient ? brandGradient : null, color: gradient ? null : surfaceHigh, borderRadius: BorderRadius.circular(radiusM)),
              child: Icon(icon, color: gradient ? Colors.white : accent, size: 28),
            ),
            const SizedBox(height: 18),
            Text(title, style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 8),
            Text(text, style: Theme.of(context).textTheme.bodyMedium),
            const SizedBox(height: 20),
            gradient
                ? FilledButton(onPressed: onTap, child: Text(button))
                : OutlinedButton(onPressed: onTap, child: Text(button)),
          ]),
        ),
      );
}
