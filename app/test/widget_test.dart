import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:nexonic_iptv/catalog.dart';
import 'package:nexonic_iptv/epg.dart';
import 'package:nexonic_iptv/m3u.dart';
import 'package:nexonic_iptv/sources.dart';
import 'package:nexonic_iptv/xtream.dart';

const playlist = '#EXTM3U x-nexonic-playlist="All channels" x-tvg-url="https://example.org/guide.xml.gz"\n'
    '#EXTINF:-1 tvg-id="DW.de@English" tvg-country="DE" tvg-language="English" tvg-logo="https://l/dw.png" '
    'group-title="Germany",DW English\n'
    'https://dwamdstream102.akamaized.net/hls/live/2015525/dwstream102/index.m3u8\n'
    '#EXTINF:-1 tvg-id="" tvg-country="FR" tvg-language="French;English" group-title="News, France",FR "Info", Direct\n'
    'https://example.org/fr.m3u8\n'
    '#EXTINF:-1 group-title="X",Duplicate\n'
    'https://example.org/fr.m3u8\n'
    '#EXTINF:-1 group-title="X",Not http\n'
    'rtmp://example.org/live\n';

String _xmltvTime(DateTime t) {
  String two(int n) => n.toString().padLeft(2, '0');
  final u = t.toUtc();
  return '${u.year}${two(u.month)}${two(u.day)}${two(u.hour)}${two(u.minute)}00 +0000';
}

/// A guide around the real current time (guides keep only programmes near now).
String guideXml(String channel, {String name = ''}) {
  final now = DateTime.now().toUtc();
  final a = now.subtract(const Duration(minutes: 30));
  final b = now.add(const Duration(minutes: 30));
  final c = now.add(const Duration(minutes: 90));
  return '<tv><channel id="$channel"><display-name>$name</display-name></channel>'
      '<programme start="${_xmltvTime(a)}" stop="${_xmltvTime(b)}" channel="$channel"><title>News &amp; Weather</title><desc>Today.</desc></programme>'
      '<programme start="${_xmltvTime(b)}" stop="${_xmltvTime(c)}" channel="$channel"><title>Documentary</title></programme></tv>';
}

Fetcher serve(Map<String, String? Function()> routes) => (Uri u) async {
      for (final e in routes.entries) {
        if (u.toString().contains(e.key)) return e.value();
      }
      return null;
    };

void main() {
  test('parses attributes, quoted commas and the header', () {
    final items = parseM3u(playlist);
    expect(items.length, 2);
    expect(items[0].name, 'DW English');
    expect(items[0].country, 'DE');
    expect(items[0].logo, 'https://l/dw.png');
    expect(items[1].name, 'FR "Info", Direct');
    expect(items[1].group, 'News, France');
    expect(headerAttrs(playlist)['x-tvg-url'], 'https://example.org/guide.xml.gz');
    expect(guideUrls(playlist), ['https://example.org/guide.xml.gz']);
  });

  test('reads provider playlists: types, headers and channel numbers', () {
    const text = '#EXTM3U url-tvg="https://g.example/a.xml,https://g.example/b.xml.gz"\n'
        '#EXTINF:-1 tvg-chno="7" group-title="News",Seven\n'
        '#EXTVLCOPT:http-user-agent=MyBox/1.0\n'
        '#EXTVLCOPT:http-referrer=https://ref.example/\n'
        'http://p.example:8080/live/u/p/1.ts\n'
        '#EXTINF:-1 group-title="Films",A Film\n'
        'http://p.example:8080/movie/u/p/2.mkv\n'
        '#EXTINF:-1 group-title="Shows",Show S01E01\n'
        'http://p.example:8080/series/u/p/3.mp4\n'
        '#EXTINF:5400,Long video\n'
        'https://cdn.example/v.mp4|User-Agent=Agent%202&Referer=https://r.example/\n'
        '#EXTINF:-1 tvg-type="movie",Typed\n'
        'https://cdn.example/typed\n';
    final items = parseM3u(text, source: 's1', classify: true);
    expect([for (final c in items) c.kind], ['live', 'movie', 'series', 'movie', 'movie']);
    expect(items[0].number, 7);
    expect(items[0].headers, {'User-Agent': 'MyBox/1.0', 'Referer': 'https://ref.example/'});
    expect(items[3].url, 'https://cdn.example/v.mp4');
    expect(items[3].headers['User-Agent'], 'Agent 2');
    expect(items.every((c) => c.source == 's1'), isTrue);
    expect(guideUrls(text), ['https://g.example/a.xml', 'https://g.example/b.xml.gz']);
  });

  test('filters by search, country, language and category', () {
    final items = parseM3u(playlist);
    expect(filterChannels(items, query: 'dw').single.name, 'DW English');
    expect(filterChannels(items, country: 'FR').length, 1);
    expect(filterChannels(items, language: 'English').length, 2);
    expect(filterChannels(items, group: 'Germany').single.name, 'DW English');
    expect(filterChannels(items, only: {'https://example.org/fr.m3u8'}).single.country, 'FR');
    expect(groupCounts(items).map((g) => g.$1), ['Germany', 'News, France']);
  });

  test('Nexonic sync adds new channels, drops removed ones and works offline', () async {
    final dir = await Directory.systemTemp.createTemp('nexonic-test');
    var text = playlist;
    final catalog = Catalog(dir, fetcher: serve({'playlists/all.m3u': () => text}));
    await catalog.start(background: false);
    expect(catalog.sources.single.isBuiltIn, isTrue);
    expect(await catalog.refreshSource('nexonic'), isNull);
    expect(catalog.items('live').length, 2);
    expect(catalog.items('live').first.number, 1);
    catalog.toggleFavorite(catalog.items('live').first);
    catalog.watched(catalog.items('live').last);

    text = '#EXTM3U\n#EXTINF:-1,DW English\n'
        'https://dwamdstream102.akamaized.net/hls/live/2015525/dwstream102/index.m3u8\n'
        '#EXTINF:-1,New One\nhttps://example.org/new.m3u8\n'
        '#EXTINF:-1,New Two\nhttps://example.org/new2.m3u8\n';
    await catalog.refreshSource('nexonic');
    expect(catalog.items('live').length, 3);
    expect(catalog.lastChange, contains('2 new, 1 removed'));
    expect(catalog.isRemoved(catalog.recents.first), isTrue); // the French channel left the catalogue

    final again = Catalog(dir, fetcher: serve({}));
    await again.start(background: false);
    expect(again.items('live').length, 3);
    expect(again.favorites.length, 1);
    expect(again.recents.length, 1);
    again.dispose();
    catalog.dispose();
  });

  test('adds an M3U link with its guide, and refuses a page that is not a playlist', () async {
    final dir = await Directory.systemTemp.createTemp('nexonic-test');
    final catalog = Catalog(dir, fetcher: serve({
      'my.example/list.m3u': () => playlist.replaceFirst('https://example.org/guide.xml.gz', 'https://g.example/guide.xml'),
      'g.example/guide.xml': () => guideXml('DW.de@English'),
      'my.example/page': () => '<html>not a playlist</html>',
    }));
    await catalog.start(background: false);
    final s = Source(id: newSourceId(), type: SourceType.m3u, name: 'Mine', url: 'https://my.example/list.m3u');
    expect(await catalog.addSource(s), isNull);
    expect(catalog.items('live').where((c) => c.source == s.id).length, 2);
    expect(s.counts['live'], 2);
    final dw = catalog.items('live').firstWhere((c) => c.name == 'DW English');
    expect(catalog.nowNext(dw).$1?.title, 'News & Weather');
    expect(catalog.nowNext(dw).$2?.title, 'Documentary');

    final bad = Source(id: newSourceId(), type: SourceType.m3u, name: 'Bad', url: 'https://my.example/page');
    expect(await catalog.addSource(bad), 'This is not an M3U playlist.');
    expect(catalog.source(bad.id), isNull);

    catalog.showSource(s.id);
    expect(catalog.items('live').length, 2);
    await catalog.removeSource(s.id);
    expect(catalog.source(s.id), isNull);
    expect(catalog.activeSource, isNull);
    catalog.dispose();
  });

  test('signs in to an Xtream Codes server and lists channels, films, series and episodes', () async {
    final dir = await Directory.systemTemp.createTemp('nexonic-test');
    String? api(Uri u) {
      if (!u.path.endsWith('player_api.php')) return u.path.endsWith('xmltv.php') ? guideXml('one.tv') : null;
      if (u.queryParameters['password'] != 'secret') return '{"user_info":{"auth":0}}';
      return switch (u.queryParameters['action']) {
        null => '{"user_info":{"auth":1,"status":"Active","exp_date":"4102444800","max_connections":"1"},"server_info":{}}',
        'get_live_categories' => '[{"category_id":"1","category_name":"News"}]',
        'get_live_streams' => '[{"num":1,"name":"One TV","stream_id":11,"stream_icon":"","epg_channel_id":"one.tv","category_id":"1"},'
            '{"num":2,"name":"Jazz FM","stream_id":12,"stream_type":"radio_streams","category_id":"1"}]',
        'get_vod_categories' => '[{"category_id":"5","category_name":"Drama"}]',
        'get_vod_streams' => '[{"name":"A Film","stream_id":21,"container_extension":"mkv","rating":"7.5","category_id":"5"}]',
        'get_series_categories' => '[]',
        'get_series' => '[{"name":"A Show","series_id":31,"cover":"","plot":"Plot.","releaseDate":"2020-01-01"}]',
        'get_series_info' => '{"episodes":{"1":[{"id":"41","episode_num":1,"title":"Pilot","container_extension":"mp4","season":1,"info":{}}],'
            '"2":[{"id":"42","episode_num":1,"title":"Return","container_extension":"mp4","season":2}]}}',
        _ => null,
      };
    }

    final catalog = Catalog(dir, fetcher: (u) async => api(u));
    await catalog.start(background: false);
    final wrong = Source(id: newSourceId(), type: SourceType.xtream, name: 'P', url: 'p.example:8080/', username: 'me', password: 'nope');
    expect(await catalog.addSource(wrong), 'Wrong username or password.');

    final s = Source(id: newSourceId(), type: SourceType.xtream, name: 'P', url: 'p.example:8080/', username: 'me', password: 'secret');
    expect(await catalog.addSource(s), isNull);
    expect(s.expires?.year, 2100);
    final live = catalog.items('live').where((c) => c.source == s.id).toList();
    expect(live.single.url, 'http://p.example:8080/live/me/secret/11.ts');
    expect(live.single.group, 'News');
    expect(catalog.items('radio').single.name, 'Jazz FM');
    expect(catalog.items('movie').single.url, 'http://p.example:8080/movie/me/secret/21.mkv');
    final show = catalog.items('series').single;
    expect(show.opensSeries, isTrue);
    expect(show.year, '2020');
    final eps = await catalog.episodes(show);
    expect([for (final e in eps) '${e.season}:${e.channel.name}'], ['1:Pilot', '2:Return']);
    expect(eps.first.channel.url, 'http://p.example:8080/series/me/secret/41.mp4');
    expect(catalog.nowNext(live.single).$1?.title, 'News & Weather');
    catalog.dispose();
  });

  test('reads now and next from an XMLTV guide, by id or by name', () {
    final g = Guide.parseText(
        '<tv><channel id="DW.de@English"><display-name>DW English</display-name></channel>'
        '<programme start="20261114120000 +0000" stop="20261114130000 +0000" channel="DW.de@English">'
        '<title lang="en">News &amp; Weather</title></programme>'
        '<programme start="20261114130000 +0000" stop="20261114140000 +0000" channel="DW.de@English"><title>Doc</title></programme></tv>',
        now: DateTime.utc(2026, 11, 14, 12, 30));
    final (now, next) = g.nowNext('DW.de@English', DateTime.utc(2026, 11, 14, 12, 30));
    expect(now?.title, 'News & Weather');
    expect(next?.title, 'Doc');
    expect(g.nowNext('', DateTime.utc(2026, 11, 14, 12, 30), 'DW English').$1?.title, 'News & Weather');
    final round = Guide.fromJson(g.toJson());
    expect(round.programmes('dw.de@english').length, 2);
  });

  test('server addresses are normalised', () {
    expect(normaliseServer('p.example:8080/'), 'http://p.example:8080');
    expect(normaliseServer('https://p.example/player_api.php?x=1'), 'https://p.example');
    final x = XtreamClient(Source(id: 'a', type: SourceType.xtream, name: 'a', url: 'p.example', username: 'u s', password: 'p&w'));
    expect(x.api().queryParameters, {'username': 'u s', 'password': 'p&w'});
  });

  test('resume points are kept only in the middle of a film', () async {
    final dir = await Directory.systemTemp.createTemp('nexonic-test');
    final catalog = Catalog(dir);
    const film = Channel(name: 'F', url: 'https://x/f.mp4', kind: 'movie');
    catalog.setProgress(film, const Duration(minutes: 30), const Duration(minutes: 90));
    expect(catalog.resume[film.key]?.fraction, closeTo(0.33, 0.01));
    catalog.setProgress(film, const Duration(minutes: 89), const Duration(minutes: 90));
    expect(catalog.resume.containsKey(film.key), isFalse);
    catalog.dispose();
  });
}
