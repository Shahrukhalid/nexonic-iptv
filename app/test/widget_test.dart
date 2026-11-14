import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:nexonic_iptv/catalog.dart';
import 'package:nexonic_iptv/epg.dart';
import 'package:nexonic_iptv/m3u.dart';

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
  });

  test('filters by search, country, language and category', () {
    final items = parseM3u(playlist);
    expect(filterChannels(items, query: 'dw').single.name, 'DW English');
    expect(filterChannels(items, country: 'FR').length, 1);
    expect(filterChannels(items, language: 'English').length, 2);
    expect(filterChannels(items, only: {'https://example.org/fr.m3u8'}).single.country, 'FR');
  });

  test('sync adds new channels, drops removed ones and works offline from the cache', () async {
    final dir = await Directory.systemTemp.createTemp('nexonic-test');
    var text = playlist;
    String? Function(String) serve = (p) => p == 'all.m3u' ? text : null;
    final catalog = Catalog(dir, fetcher: (p) async => serve(p));
    await catalog.refresh(sections: [Section.live]);
    expect(catalog.lists[Section.live]!.length, 2);
    catalog.toggleFavorite(catalog.lists[Section.live]!.first);
    catalog.watched(catalog.lists[Section.live]!.last);

    text = '#EXTM3U\n#EXTINF:-1,DW English\n'
        'https://dwamdstream102.akamaized.net/hls/live/2015525/dwstream102/index.m3u8\n'
        '#EXTINF:-1,New One\nhttps://example.org/new.m3u8\n'
        '#EXTINF:-1,New Two\nhttps://example.org/new2.m3u8\n';
    await catalog.refresh(sections: [Section.live]);
    expect(catalog.lists[Section.live]!.length, 3);
    expect(catalog.lastChange, contains('2 new, 1 removed'));
    expect(catalog.isRemoved(catalog.recents.first), isTrue); // the French channel left the catalogue

    serve = (_) => null; // offline
    final again = Catalog(dir, fetcher: (p) async => serve(p));
    await again.start();
    expect(again.lists[Section.live]!.length, 3);
    expect(again.favorites.length, 1);
    expect(again.recents.length, 1);
    again.dispose();
    catalog.dispose();
  });

  test('reads now and next from an XMLTV guide', () {
    final g = Guide.parseText('<tv><programme start="20261114120000 +0000" stop="20261114130000 +0000" channel="DW.de@English">'
        '<title lang="en">News &amp; Weather</title></programme>'
        '<programme start="20261114130000 +0000" stop="20261114140000 +0000" channel="DW.de@English"><title>Doc</title></programme></tv>');
    final (now, next) = g.nowNext('DW.de@English', DateTime.utc(2026, 11, 14, 12, 30));
    expect(now?.title, 'News & Weather');
    expect(next?.title, 'Doc');
  });
}
