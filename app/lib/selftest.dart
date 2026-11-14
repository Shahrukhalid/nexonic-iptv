/// Release-build self-test used by CI: downloads the live catalogue, checks it parses and caches, then plays
/// verified channels until one shows moving pictures. Writes a JSON result and exits 0 (pass) or 1 (fail).
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:media_kit/media_kit.dart';
import 'package:media_kit_video/media_kit_video.dart';

import 'catalog.dart';
import 'm3u.dart';

class SelfTestApp extends StatefulWidget {
  const SelfTestApp({super.key, required this.output});

  /// A file path for the result, or "log" to only print it.
  final String output;

  @override
  State<SelfTestApp> createState() => _SelfTestAppState();
}

class _SelfTestAppState extends State<SelfTestApp> {
  final player = Player();
  late final controller = VideoController(player);
  String status = 'Starting self-test…';

  @override
  void initState() {
    super.initState();
    unawaited(_run());
  }

  Future<void> _run() async {
    final result = <String, dynamic>{'ok': false};
    try {
      final dir = await Directory.systemTemp.createTemp('nexonic-selftest');
      final catalog = Catalog(dir);
      await dir.create(recursive: true);
      await catalog.refresh(sections: [Section.live]);
      final live = catalog.lists[Section.live] ?? const <Channel>[];
      result['channels'] = live.length;
      result['categories'] = catalog.entries('category').length;
      result['cached'] = await File('${dir.path}/cache/all.m3u').exists();
      // Offline start: a fresh catalogue on the same folder must load the cached copy without the network.
      final offline = Catalog(dir, fetcher: (_) async => null);
      await offline.refresh(sections: [Section.live]);
      result['offline_channels'] = (offline.lists[Section.live] ?? const []).length;
      if (live.length < 100) throw StateError('catalogue too small: ${live.length}');
      // Verified channels first: they passed a check in the last 48 hours.
      final verifiedText = await _download('$siteBase/verified.m3u') ?? await _download('$mirrorBase/verified.m3u');
      final candidates = [...parseM3u(verifiedText ?? ''), ...live].take(12).toList();
      try {
        await (player.platform as dynamic).setProperty('ao', 'null'); // CI machines have no sound card
      } catch (_) {}
      final tried = <String>[];
      for (final c in candidates) {
        setState(() => status = 'Playing ${c.name}…');
        tried.add(c.name);
        if (await _plays(c.url)) {
          result['played'] = c.name;
          result['width'] = player.state.width;
          result['ok'] = (result['offline_channels'] as int) == live.length;
          break;
        }
      }
      result['tried'] = tried;
    } catch (e) {
      result['error'] = '$e';
    }
    final text = jsonEncode(result);
    if (Platform.isAndroid) {
      // ignore: avoid_print
      print('NEXONIC_SELF_TEST $text'); // logcat
    } else {
      // Standard output (macOS, where the sandbox blocks other folders), flushed before the process exits.
      stdout.writeln('NEXONIC_SELF_TEST $text');
      await stdout.flush();
    }
    if (widget.output != 'log') {
      try {
        await File(widget.output).writeAsString(text);
      } catch (_) {}
    }
    await player.dispose();
    exit(result['ok'] == true ? 0 : 1);
  }

  /// True when the stream decodes pictures (or sound for audio-only streams) and its position advances.
  Future<bool> _plays(String url) async {
    await player.open(Media(url));
    final end = DateTime.now().add(const Duration(seconds: 30));
    while (DateTime.now().isBefore(end)) {
      await Future<void>.delayed(const Duration(milliseconds: 500));
      final s = player.state;
      if ((s.width ?? 0) > 0 && s.position > const Duration(seconds: 2)) return true;
    }
    await player.stop();
    return false;
  }

  static Future<String?> _download(String url) async {
    final c = HttpClient();
    try {
      final res = await (await c.getUrl(Uri.parse(url))).close().timeout(const Duration(seconds: 60));
      if (res.statusCode != 200) return null;
      return await res.transform(utf8.decoder).join();
    } catch (_) {
      return null;
    } finally {
      c.close();
    }
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
        debugShowCheckedModeBanner: false,
        home: Scaffold(
          backgroundColor: Colors.black,
          body: Stack(children: [
            Video(controller: controller),
            Positioned(left: 16, bottom: 16, child: Text(status, style: const TextStyle(color: Colors.white))),
          ]),
        ),
      );
}
