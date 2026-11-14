import 'dart:io';

import 'package:flutter/material.dart';
import 'package:media_kit/media_kit.dart';
import 'package:path_provider/path_provider.dart';

import 'catalog.dart';
import 'selftest.dart';
import 'ui/home.dart';
import 'ui/theme.dart';

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
        home: HomeScreen(catalog: catalog),
      );
}
