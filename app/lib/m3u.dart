/// Channels and extended M3U parsing, for the Nexonic playlists and for playlists people add themselves.
library;

/// One playable item (live channel, radio station, film, episode) or a series that opens a list of episodes.
class Channel {
  const Channel({
    required this.name,
    required this.url,
    this.logo = '',
    this.group = '',
    this.country = '',
    this.language = '',
    this.tvgId = '',
    this.kind = 'live',
    this.source = '',
    this.number = 0,
    this.headers = const {},
    this.tags = const [],
    this.seriesId = '',
    this.year = '',
    this.rating = '',
    this.plot = '',
  });

  final String name;
  final String url;
  final String logo;
  final String group;
  final String country;
  final String language;
  final String tvgId;

  /// live, radio, movie, series, media or episode.
  final String kind;

  /// Id of the playlist (source) the item comes from.
  final String source;

  /// Channel number shown in lists and used for number-key zapping (0 = none).
  final int number;

  /// Request headers some streams need (User-Agent, Referer).
  final Map<String, String> headers;

  /// Extra categories (Nexonic category playlists).
  final List<String> tags;

  /// Xtream series id: the item opens a season and episode list instead of playing.
  final String seriesId;
  final String year;
  final String rating;
  final String plot;

  bool get isRadio => kind == 'radio';
  bool get isLive => kind == 'live' || kind == 'radio';
  bool get isVod => kind == 'movie' || kind == 'media' || kind == 'episode' || (kind == 'series' && seriesId.isEmpty);
  bool get opensSeries => kind == 'series' && seriesId.isNotEmpty;

  /// Stable identity for favourites, history and resume points.
  String get key => url.isNotEmpty ? url : '$source:series:$seriesId';

  /// Categories this item is listed under.
  List<String> get categories => tags.isNotEmpty ? tags : (group.isEmpty ? const ['Other'] : [group]);

  Map<String, dynamic> toJson() => {
        'name': name,
        'url': url,
        if (logo.isNotEmpty) 'logo': logo,
        if (group.isNotEmpty) 'group': group,
        if (country.isNotEmpty) 'country': country,
        if (language.isNotEmpty) 'language': language,
        if (tvgId.isNotEmpty) 'tvgId': tvgId,
        'kind': kind,
        if (source.isNotEmpty) 'source': source,
        if (number > 0) 'number': number,
        if (headers.isNotEmpty) 'headers': headers,
        if (tags.isNotEmpty) 'tags': tags,
        if (seriesId.isNotEmpty) 'seriesId': seriesId,
        if (year.isNotEmpty) 'year': year,
        if (rating.isNotEmpty) 'rating': rating,
        if (plot.isNotEmpty) 'plot': plot,
      };

  static Channel fromJson(Map<String, dynamic> j) => Channel(
        name: '${j['name'] ?? ''}',
        url: '${j['url'] ?? ''}',
        logo: '${j['logo'] ?? ''}',
        group: '${j['group'] ?? ''}',
        country: '${j['country'] ?? ''}',
        language: '${j['language'] ?? ''}',
        tvgId: '${j['tvgId'] ?? ''}',
        kind: '${j['kind'] ?? 'live'}',
        source: '${j['source'] ?? ''}',
        number: (j['number'] as num?)?.toInt() ?? 0,
        headers: {for (final e in ((j['headers'] as Map?) ?? const {}).entries) '${e.key}': '${e.value}'},
        tags: [for (final t in (j['tags'] as List?) ?? const []) '$t'],
        seriesId: '${j['seriesId'] ?? ''}',
        year: '${j['year'] ?? ''}',
        rating: '${j['rating'] ?? ''}',
        plot: '${j['plot'] ?? ''}',
      );

  Channel copyWith({String? kind, String? source, int? number, List<String>? tags}) => Channel(
        name: name,
        url: url,
        logo: logo,
        group: group,
        country: country,
        language: language,
        tvgId: tvgId,
        kind: kind ?? this.kind,
        source: source ?? this.source,
        number: number ?? this.number,
        headers: headers,
        tags: tags ?? this.tags,
        seriesId: seriesId,
        year: year,
        rating: rating,
        plot: plot,
      );
}

final _attr = RegExp(r'([A-Za-z0-9_-]+)="([^"]*)"');

/// Attributes of the `#EXTM3U` header line (for example `x-tvg-url`).
Map<String, String> headerAttrs(String text) {
  final end = text.indexOf('\n');
  final first = (end < 0 ? text : text.substring(0, end)).trim().replaceFirst('﻿', '');
  if (!first.startsWith('#EXTM3U')) return const {};
  return {for (final m in _attr.allMatches(first)) m.group(1)!.toLowerCase(): m.group(2)!};
}

/// Guide (XMLTV) addresses named in a playlist header (`x-tvg-url` or `url-tvg`, comma separated).
List<String> guideUrls(String text) {
  final h = headerAttrs(text);
  final raw = [h['x-tvg-url'], h['url-tvg'], h['tvg-url']].whereType<String>().join(',');
  return [
    for (final u in raw.split(','))
      if (u.trim().startsWith('http')) u.trim()
  ];
}

/// Splits `-1 a="x, y",Title` at the first comma outside quotes.
(String, String) _splitInfo(String rest) {
  var quoted = false;
  for (var i = 0; i < rest.length; i++) {
    final c = rest[i];
    if (c == '"') quoted = !quoted;
    if (c == ',' && !quoted) return (rest.substring(0, i), rest.substring(i + 1).trim());
  }
  return (rest, '');
}

const _vodExt = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.webm', '.ogv', '.m4v', '.mpg', '.mpeg'];

/// Guesses what an entry is when the playlist does not say: provider URL paths (`/movie/`, `/series/`), a
/// `tvg-type` attribute, a positive duration or a file extension mark films and episodes.
String classify(String url, Map<String, String> attrs, String duration, String fallback) {
  final type = (attrs['tvg-type'] ?? attrs['type'] ?? '').toLowerCase();
  if (type == 'movie' || type == 'movies' || type == 'vod') return 'movie';
  if (type == 'series' || type == 'serie') return 'series';
  if (type == 'radio' || attrs['radio'] == 'true') return 'radio';
  if (fallback != 'live') return fallback;
  final path = Uri.tryParse(url)?.path.toLowerCase() ?? url.toLowerCase();
  if (path.contains('/movie/')) return 'movie';
  if (path.contains('/series/')) return 'series';
  if (path.contains('/live/') || path.endsWith('.m3u8') || path.endsWith('.ts')) return 'live';
  final secs = int.tryParse(duration.trim()) ?? -1;
  if (secs > 0 || _vodExt.any(path.endsWith)) return 'movie';
  return 'live';
}

/// Splits Kodi-style `url|User-Agent=x&Referer=y` into the address and its headers.
(String, Map<String, String>) _pipeHeaders(String line) {
  final i = line.indexOf('|');
  if (i < 0) return (line, const {});
  final headers = <String, String>{};
  for (final part in line.substring(i + 1).split('&')) {
    final eq = part.indexOf('=');
    if (eq > 0) headers[part.substring(0, eq).trim()] = Uri.decodeComponent(part.substring(eq + 1).trim());
  }
  return (line.substring(0, i), headers);
}

String _headerName(String vlcOption) => switch (vlcOption.toLowerCase()) {
      'http-user-agent' => 'User-Agent',
      'http-referrer' || 'http-referer' => 'Referer',
      'http-origin' => 'Origin',
      _ => '',
    };

/// Channels of an extended M3U text. Entries without an http(s) address are skipped, and an address listed twice
/// is kept once. `kind` is the default type; `classify: true` lets each entry's URL and attributes decide.
List<Channel> parseM3u(String text, {String kind = 'live', String source = '', bool classify = false}) {
  final out = <Channel>[];
  final seen = <String>{};
  Map<String, String>? attrs;
  var title = '';
  var duration = '-1';
  var extra = <String, String>{};
  var group = '';
  for (final raw in text.split('\n')) {
    final line = raw.trim();
    if (line.isEmpty) continue;
    if (line.startsWith('#EXTINF:')) {
      final (info, name) = _splitInfo(line.substring(8));
      attrs = {for (final m in _attr.allMatches(info)) m.group(1)!.toLowerCase(): m.group(2)!};
      duration = info.split(' ').first;
      title = name;
      extra = {};
      group = '';
      continue;
    }
    if (line.startsWith('#EXTVLCOPT:')) {
      final opt = line.substring(11);
      final eq = opt.indexOf('=');
      if (eq > 0) {
        final name = _headerName(opt.substring(0, eq).trim());
        if (name.isNotEmpty) extra[name] = opt.substring(eq + 1).trim();
      }
      continue;
    }
    if (line.startsWith('#EXTGRP:')) {
      group = line.substring(8).trim();
      continue;
    }
    if (line.startsWith('#EXTHTTP:')) {
      final m = RegExp(r'"([^"]+)"\s*:\s*"([^"]*)"').allMatches(line.substring(9));
      for (final x in m) {
        extra[x.group(1)!] = x.group(2)!;
      }
      continue;
    }
    if (line.startsWith('#')) continue;
    final a = attrs;
    attrs = null;
    if (a == null) continue;
    final (address, pipe) = _pipeHeaders(line);
    final lower = address.toLowerCase();
    if (!(lower.startsWith('http://') || lower.startsWith('https://')) || !seen.add(address)) continue;
    final k = classify ? _classifyEntry(address, a, duration, kind) : kind;
    out.add(Channel(
      name: title.isNotEmpty ? title : (a['tvg-name'] ?? address),
      url: address,
      logo: a['tvg-logo'] ?? a['logo'] ?? '',
      group: a['group-title'] ?? group,
      country: (a['tvg-country'] ?? '').toUpperCase(),
      language: a['tvg-language'] ?? '',
      tvgId: a['tvg-id'] ?? '',
      kind: k,
      source: source,
      number: int.tryParse(a['tvg-chno'] ?? a['channel-number'] ?? '') ?? 0,
      headers: {...extra, ...pipe},
    ));
  }
  return out;
}

String _classifyEntry(String url, Map<String, String> a, String duration, String kind) =>
    classify(url, a, duration, kind);
