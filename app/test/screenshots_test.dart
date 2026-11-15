// Renders the main screens with sample data to PNG files for design review (not part of the normal test run):
//
//   flutter test --update-goldens --dart-define=SCREENSHOTS=true test/screenshots_test.dart
//
// The images are written to test/screenshots/. Channel names in the sample data are invented.
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nexonic_iptv/catalog.dart';
import 'package:nexonic_iptv/epg.dart';
import 'package:nexonic_iptv/m3u.dart';
import 'package:nexonic_iptv/sources.dart';
import 'package:nexonic_iptv/ui/guide_page.dart';
import 'package:nexonic_iptv/ui/live_page.dart';
import 'package:nexonic_iptv/ui/shell.dart';
import 'package:nexonic_iptv/ui/theme.dart';
import 'package:nexonic_iptv/ui/welcome.dart';
import 'package:nexonic_iptv/ui/widgets.dart';

const enabled = bool.fromEnvironment('SCREENSHOTS');

Future<void> _loadFonts() async {
  final roots = <String>[
    if (Platform.environment['FLUTTER_ROOT'] case final r?) r,
    // flutter_tester lives in <flutter>/bin/cache/artifacts/engine/<platform>/.
    File(Platform.resolvedExecutable).parent.parent.parent.parent.parent.parent.path,
  ];
  for (final root in roots) {
    final dir = Directory('$root/bin/cache/artifacts/material_fonts');
    if (!dir.existsSync()) continue;
    final roboto = FontLoader('Roboto');
    for (final f in dir.listSync().whereType<File>().where((f) => f.path.contains('Roboto') && f.path.endsWith('.ttf'))) {
      roboto.addFont(Future.value(ByteData.sublistView(f.readAsBytesSync())));
    }
    await roboto.load();
    final icons = File('${dir.path}/MaterialIcons-Regular.otf');
    if (icons.existsSync()) {
      await (FontLoader('MaterialIcons')..addFont(Future.value(ByteData.sublistView(icons.readAsBytesSync())))).load();
    }
    return;
  }
}

const _live = [
  ('Atlas News 24', 'News'), ('Meridian World', 'News'), ('Capital Business', 'News'), ('Daybreak News', 'News'),
  ('Northwind Sports', 'Sports'), ('Arena One', 'Sports'), ('Goal Line TV', 'Sports'), ('Racing Weekly', 'Sports'),
  ('Kids Planet', 'Kids'), ('Little Explorers', 'Kids'), ('Cartoon Harbor', 'Kids'), ('Story Time TV', 'Kids'),
  ('Orbit Documentary', 'Documentary'), ('Wild Earth', 'Documentary'), ('History Lane', 'Documentary'), ('Science Now', 'Documentary'),
  ('Harbor Music', 'Music'), ('Retro Hits', 'Music'), ('Jazz Avenue', 'Music'), ('Coastline TV', 'Entertainment'),
  ('Metro One', 'Entertainment'), ('Cinema Classics', 'Entertainment'), ('Laugh Factory TV', 'Entertainment'), ('Food & Travel', 'Lifestyle'),
  ('Home Studio', 'Lifestyle'), ('Parliament Live', 'News'), ('Global Weather', 'News'), ('Summit Outdoors', 'Lifestyle'),
];
const _shows = [
  'Morning Briefing', 'World Report', 'Market Watch', 'Live Match: Semi-final', 'Highlights', 'The Big Quiz', 'Planet Oceans',
  'Inside the Workshop', 'Evening News', 'Top 40 Countdown', 'Cooking at Home', 'Weather Update', 'Cartoon Club', 'Night Talk',
  'Classic Film: The Harbour', 'Science Hour', 'Travel Diaries', 'Late Edition',
];
const _films = [
  ('The Silent Coast', '1954', '7.8'), ('Midnight Harbor', '1947', '7.2'), ('Paper Moonlight', '1961', '6.9'), ('The Long Valley', '1939', '7.4'),
  ('City of Lanterns', '1958', '8.1'), ('Northbound', '1950', '6.7'), ('Glass Garden', '1966', '7.0'), ('The Clockmaker', '1931', '7.6'),
  ('Saltwater Road', '1949', '6.8'), ('Winter Station', '1956', '7.3'), ('A Quiet Signal', '1962', '7.1'), ('Desert Lights', '1953', '6.5'),
];

(List<Channel>, Guide) sample() {
  final now = DateTime.now().toUtc();
  final base = DateTime.utc(now.year, now.month, now.day, now.hour).subtract(const Duration(hours: 2));
  final items = <Channel>[];
  final programmes = <String, List<Programme>>{};
  for (var i = 0; i < _live.length; i++) {
    final (name, group) = _live[i];
    final id = 'ch$i';
    items.add(Channel(name: name, url: 'https://example.invalid/$id.m3u8', group: group, tvgId: id, number: i + 1, source: 'nexonic', country: i.isEven ? 'GB' : 'US', tags: [group]));
    var t = base.add(Duration(minutes: (i * 17) % 45));
    final list = <Programme>[];
    for (var k = 0; k < 16; k++) {
      final len = Duration(minutes: [30, 45, 60, 90, 60, 30][(i + k) % 6]);
      list.add(Programme(t, t.add(len), _shows[(i * 3 + k) % _shows.length], 'An invented programme description for the screenshot.'));
      t = t.add(len);
    }
    programmes[id] = list;
  }
  for (var i = 0; i < _films.length; i++) {
    final (name, year, rating) = _films[i];
    items.add(Channel(name: name, url: 'https://example.invalid/f$i.mp4', kind: 'movie', group: i.isEven ? 'Drama' : 'Mystery', year: year, rating: rating, source: 'nexonic'));
  }
  for (final s in ['Harbour Patrol', 'The Workshop', 'Night Shift', 'Hilltop Farm', 'Space Cadets', 'Courtroom Nine']) {
    items.add(Channel(name: s, url: '', kind: 'series', seriesId: s, group: 'Classic TV', year: '1960', source: 'nexonic'));
  }
  for (final r in ['Jazz FM Cafe', 'Classic Radio', 'Talk 101', 'Indie Wave', 'Chill Lounge', 'Retro Radio', 'News Radio', 'Country Roads']) {
    items.add(Channel(name: r, url: 'https://example.invalid/$r.mp3', kind: 'radio', group: 'Music', country: 'GB', source: 'nexonic'));
  }
  return (items, Guide(programmes));
}

Future<Catalog> _catalog() async {
  final dir = await Directory.systemTemp.createTemp('nexonic-shots');
  final c = Catalog(dir);
  c.sources.add(Source.nexonic()..lastSync = DateTime.now());
  c.sources.add(Source(id: 'mine', type: SourceType.xtream, name: 'My provider', url: 'http://tv.example.com:8080', username: 'me', password: 'x')
    ..lastSync = DateTime.now().subtract(const Duration(hours: 2))
    ..counts = {'live': 12840, 'movie': 30412, 'series': 4120}
    ..expires = DateTime.now().add(const Duration(days: 212)));
  c.sources.add(Source(id: 'list', type: SourceType.m3u, name: 'Family playlist', url: 'https://lists.example.org/family.m3u', enabled: false));
  final (items, guide) = sample();
  c.debugSetItems('nexonic', items, guide: guide);
  c.settings.welcomed = true;
  final live = c.items('live');
  c.watched(live[4]);
  c.watched(live[12]);
  c.watched(live[0]);
  c.toggleFavorite(live[0]);
  c.toggleFavorite(live[8]);
  c.toggleFavorite(live[16]);
  return c;
}

Future<void> _shot(WidgetTester tester, String name, Size size, Widget child, {Future<void> Function()? then}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  // A fresh app for every picture, so a page never keeps the state of the previous one.
  await tester.pumpWidget(const SizedBox());
  await tester.pumpWidget(MaterialApp(key: ValueKey(name), debugShowCheckedModeBanner: false, theme: buildTheme(), home: child));
  for (var i = 0; i < 6; i++) {
    await tester.pump(const Duration(milliseconds: 200));
  }
  if (then != null) {
    await then();
    for (var i = 0; i < 6; i++) {
      await tester.pump(const Duration(milliseconds: 200));
    }
  }
  await expectLater(find.byType(MaterialApp), matchesGoldenFile('screenshots/$name.png'));
}

void main() {
  setUpAll(() async {
    loadImages = false;
    previewPlayback = false;
    if (enabled) await _loadFonts();
  });

  const desktop = Size(1440, 900);
  const phone = Size(412, 900);

  testWidgets('screenshots', (tester) async {
    final c = await tester.runAsync(_catalog);
    final catalog = c!;
    await _shot(tester, '01-home', desktop, AppShell(catalog: catalog, initialPage: Nav.home));
    await _shot(tester, '02-live', desktop, AppShell(catalog: catalog, initialPage: Nav.live));
    await _shot(tester, '03-guide', desktop, Scaffold(body: Backdrop(child: GuidePage(catalog: catalog, nav: (_, {group}) {}))));
    await _shot(tester, '04-films', desktop, AppShell(catalog: catalog, initialPage: Nav.movies));
    await _shot(tester, '05-playlists', desktop, AppShell(catalog: catalog, initialPage: Nav.sources));
    await _shot(tester, '06-add-playlist', desktop, AppShell(catalog: catalog, initialPage: Nav.sources), then: () async {
      await tester.tap(find.text('Add playlist').first);
    });
    await _shot(tester, '07-settings', desktop, AppShell(catalog: catalog, initialPage: Nav.settings));
    await _shot(tester, '08-welcome', desktop, WelcomePage(catalog: catalog, onDone: () {}));
    await _shot(tester, '09-phone-home', phone, AppShell(catalog: catalog, initialPage: Nav.home));
    await _shot(tester, '10-phone-live', phone, AppShell(catalog: catalog, initialPage: Nav.live));
    addTearDown(tester.view.reset);
  }, skip: !enabled);
}
