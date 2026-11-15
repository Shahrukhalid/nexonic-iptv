import 'dart:io';

import 'package:flutter/material.dart';
import 'package:media_kit/media_kit.dart';
import 'package:path_provider/path_provider.dart';

import 'catalog.dart';
import 'selftest.dart';
import 'ui/shell.dart';
import 'ui/theme.dart';
import 'ui/welcome.dart';

/// Builds with `--dart-define=NEXONIC_SELF_TEST=log` (Android CI) or runs with the environment variable
/// NEXONIC_SELF_TEST=<result file> (desktop CI) start the self-test instead of the app.
const _selfTestDefine = String.fromEnvironment('NEXONIC_SELF_TEST');

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  MediaKit.ensureInitialized();
  final selfTest = _selfTestDefine.isNotEmpty ? _selfTestDefine : (Platform.environment['NEXONIC_SELF_TEST'] ?? '');
  if (selfTest.isNotEmpty) {
    runApp(SelfTestApp(output: selfTest));
    return;
  }
  final base = await getApplicationSupportDirectory();
  final catalog = Catalog(Directory('${base.path}/nexonic'));
  runApp(NexonicApp(catalog: catalog));
  await catalog.start();
}

class NexonicApp extends StatelessWidget {
  const NexonicApp({super.key, required this.catalog});
  final Catalog catalog;

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'Nexonic IPTV',
        debugShowCheckedModeBanner: false,
        theme: buildTheme(),
        darkTheme: buildTheme(),
        themeMode: ThemeMode.dark,
        home: Root(catalog: catalog),
      );
}

/// Splash while the saved catalogue loads, the welcome screen on first start, then the app.
class Root extends StatefulWidget {
  const Root({super.key, required this.catalog});
  final Catalog catalog;

  @override
  State<Root> createState() => _RootState();
}

class _RootState extends State<Root> {
  bool welcomed = false;

  @override
  void initState() {
    super.initState();
    widget.catalog.addListener(_update);
  }

  @override
  void dispose() {
    widget.catalog.removeListener(_update);
    super.dispose();
  }

  void _update() {
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.catalog;
    final Widget child;
    if (!c.loaded) {
      child = const Scaffold(key: ValueKey('splash'), body: Backdrop(child: Center(child: NexonicLogo(size: 72))));
    } else if (!c.settings.welcomed && !welcomed) {
      child = WelcomePage(key: const ValueKey('welcome'), catalog: c, onDone: () => setState(() => welcomed = true));
    } else {
      child = AppShell(key: const ValueKey('app'), catalog: c);
    }
    return AnimatedSwitcher(duration: const Duration(milliseconds: 300), child: child);
  }
}
