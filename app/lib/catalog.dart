/// The Nexonic catalogue: published playlists, cached on disk, refreshed at startup and every few hours.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

import 'epg.dart';
import 'm3u.dart';

const siteBase = 'https://shahrukhalid.github.io/nexonic-iptv/playlists';
const mirrorBase = 'https://raw.githubusercontent.com/Shahrukhalid/nexonic-iptv/main/playlists';
const refreshEvery = Duration(hours: 3);

enum Section {
  live('Live TV', 'all.m3u', 'live'),
  movies('Movies', 'vod/movies.m3u', 'movie'),
  series('Series', 'vod/series.m3u', 'series'),
  radio('Radio', 'radio/all.m3u', 'radio'),
  media('Open media', 'media/all.m3u', 'media');

  const Section(this.label, this.path, this.kind);
  final String label;
  final String path;
  final String kind;
}

/// What a refresh changed in one section.
class Diff {
  const Diff(this.added, this.removed, this.total);
  final int added;
  final int removed;
  final int total;
}

/// A playlist listed in `playlists/index.json` (country, language or category file).
class IndexEntry {
  const IndexEntry(this.kind, this.key, this.name, this.path, this.count);
  final String kind;
  final String key;
  final String name;
  final String path;
  final int count;
}

/// Filters a channel list. Empty values mean "any".
List<Channel> filterChannels(
  List<Channel> items, {
  String query = '',
  String country = '',
  String language = '',
  String group = '',
  Set<String>? only,
}) {
  final q = query.trim().toLowerCase();
  return [
    for (final c in items)
      if ((q.isEmpty || c.name.toLowerCase().contains(q) || c.group.toLowerCase().contains(q)) &&
          (country.isEmpty || c.country == country) &&
          (language.isEmpty || c.language.split(';').contains(language)) &&
          (group.isEmpty || c.group == group) &&
          (only == null || only.contains(c.url)))
        c
  ];
}

Diff diffOf(List<Channel> before, List<Channel> after) {
  final a = {for (final c in before) c.url};
  final b = {for (final c in after) c.url};
  return Diff(b.difference(a).length, a.difference(b).length, after.length);
}

class Catalog extends ChangeNotifier {
  Catalog(this.dir, {this.fetcher});

  final Directory dir;

  /// Replaces network access in tests: path -> text (null = not available).
  final Future<String?> Function(String path)? fetcher;

  final Map<Section, List<Channel>> lists = {};
  final Map<Section, DateTime> updated = {};
  final Map<String, Set<String>> _filterSets = {};
  List<IndexEntry> index = const [];
  final Map<String, Channel> favorites = {};
  final List<Channel> recents = [];
  final Set<String> failing = {};
  Guide guide = Guide.empty;
  final Set<Section> busy = {};
  String? error;
  String? lastChange;
  Timer? _timer;
  Map<String, dynamic> _meta = {};

  File get _metaFile => File('${dir.path}/meta.json');
  File get _libraryFile => File('${dir.path}/library.json');
  File _cacheFile(String path) => File('${dir.path}/cache/${path.replaceAll('/', '_')}');

  Future<void> start() async {
    await dir.create(recursive: true);
    await _loadLibrary();
    try {
      _meta = jsonDecode(await _metaFile.readAsString()) as Map<String, dynamic>;
    } catch (_) {
      _meta = {};
    }
    // Offline first: whatever was cached shows at once, then the network copy replaces it.
    final cached = await _cacheFile(Section.live.path).exists();
    if (cached) {
      await _loadSection(Section.live, network: false);
      await _loadIndex(network: false);
    }
    unawaited(refresh(sections: [Section.live]));
    _timer = Timer.periodic(refreshEvery, (_) => refresh());
  }

  bool _disposed = false;

  @override
  void notifyListeners() {
    if (!_disposed) super.notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _timer?.cancel();
    super.dispose();
  }

  /// Loads a section the first time it is opened.
  Future<void> ensure(Section s) async {
    if (lists.containsKey(s) || busy.contains(s)) return;
    if (await _cacheFile(s.path).exists()) await _loadSection(s, network: false);
    await refresh(sections: [s]);
  }

  /// Fetches the given sections (default: every section opened so far) and reports what changed.
  Future<void> refresh({List<Section>? sections}) async {
    final todo = sections ?? lists.keys.toList();
    if (todo.isEmpty) todo.add(Section.live);
    final notes = <String>[];
    error = null;
    for (final s in todo) {
      final before = lists[s] ?? const <Channel>[];
      final ok = await _loadSection(s, network: true);
      if (!ok) continue;
      final d = diffOf(before, lists[s]!);
      if (before.isNotEmpty && (d.added > 0 || d.removed > 0)) {
        notes.add('${s.label}: ${d.added} new, ${d.removed} removed');
      }
    }
    if (todo.contains(Section.live)) {
      await _loadIndex(network: true);
      _filterSets.clear();
    }
    if (notes.isNotEmpty) lastChange = notes.join(' · ');
    notifyListeners();
  }

  Future<bool> _loadSection(Section s, {required bool network}) async {
    busy.add(s);
    notifyListeners();
    try {
      final text = network ? await _fetch(s.path) : await _readCache(s.path);
      if (text == null) return false;
      final items = parseM3u(text, kind: s.kind);
      if (items.isEmpty) return false;
      lists[s] = items;
      updated[s] = network ? DateTime.now() : (await _cacheFile(s.path).lastModified());
      if (s == Section.live) unawaited(_loadGuide(headerAttrs(text)['x-tvg-url']));
      return true;
    } catch (e) {
      error = 'Could not update ${s.label}: $e';
      return false;
    } finally {
      busy.remove(s);
      notifyListeners();
    }
  }

  Future<void> _loadIndex({required bool network}) async {
    try {
      final text = network ? await _fetch('index.json') : await _readCache('index.json');
      if (text == null) return;
      final rows = (jsonDecode(text) as Map<String, dynamic>)['playlists'] as List<dynamic>;
      index = [
        for (final r in rows.cast<Map<String, dynamic>>())
          IndexEntry('${r['kind']}', '${r['key']}', '${r['name']}', '${r['path']}', (r['count'] as num?)?.toInt() ?? 0)
      ];
    } catch (_) {
      // The index only adds the category filter; the app works without it.
    }
  }

  List<IndexEntry> entries(String kind) => [
        for (final e in index)
          if (e.kind == kind) e
      ]..sort((a, b) => a.name.compareTo(b.name));

  /// Addresses in one category (or any other index) playlist, fetched on demand.
  Future<Set<String>> playlistUrls(IndexEntry e) async {
    final hit = _filterSets[e.path];
    if (hit != null) return hit;
    final rel = e.path.startsWith('playlists/') ? e.path.substring(10) : e.path;
    final text = await _fetch(rel) ?? await _readCache(rel) ?? '';
    final set = {for (final c in parseM3u(text)) c.url};
    _filterSets[e.path] = set;
    return set;
  }

  Future<void> _loadGuide(String? url) async {
    if (url == null || url.isEmpty) return;
    try {
      final c = HttpClient()..connectionTimeout = const Duration(seconds: 15);
      try {
        final res = await (await c.getUrl(Uri.parse(url))).close().timeout(const Duration(seconds: 60));
        if (res.statusCode != 200) return;
        final bytes = await res.fold<List<int>>(<int>[], (a, b) => a..addAll(b));
        guide = Guide.parse(bytes);
        notifyListeners();
      } finally {
        c.close();
      }
    } catch (_) {
      // No guide is fine.
    }
  }

  Future<String?> _readCache(String path) async {
    final f = _cacheFile(path);
    return await f.exists() ? f.readAsString() : null;
  }

  /// Network copy of a published file (site first, then the raw mirror), written to the cache. Falls back to the
  /// cached copy when both fail, so the app keeps working offline.
  Future<String?> _fetch(String path) async {
    if (fetcher != null) {
      final t = await fetcher!(path);
      if (t != null) await _write(path, t, null);
      return t ?? await _readCache(path);
    }
    final etags = (_meta['etags'] as Map<String, dynamic>?) ?? <String, dynamic>{};
    for (final base in [siteBase, mirrorBase]) {
      try {
        final cached = await _cacheFile(path).exists();
        final (status, body, etag) = await _get('$base/$path', cached ? etags['$base/$path'] as String? : null);
        if (status == 304) return _readCache(path);
        await _write(path, body!, etag == null ? null : MapEntry('$base/$path', etag));
        return body;
      } catch (_) {
        continue;
      }
    }
    return _readCache(path);
  }

  Future<void> _write(String path, String body, MapEntry<String, String>? etag) async {
    final f = _cacheFile(path);
    await f.parent.create(recursive: true);
    await f.writeAsString(body);
    if (etag != null) {
      final etags = Map<String, dynamic>.from((_meta['etags'] as Map<String, dynamic>?) ?? {});
      etags[etag.key] = etag.value;
      _meta['etags'] = etags;
      await _metaFile.writeAsString(jsonEncode(_meta));
    }
  }

  static Future<(int, String?, String?)> _get(String url, String? etag) async {
    final c = HttpClient()
      ..connectionTimeout = const Duration(seconds: 15)
      ..userAgent = 'NexonicIPTV/1.3';
    try {
      final req = await c.getUrl(Uri.parse(url));
      if (etag != null) req.headers.set(HttpHeaders.ifNoneMatchHeader, etag);
      final res = await req.close().timeout(const Duration(seconds: 60));
      if (res.statusCode == 304) {
        await res.drain<void>();
        return (304, null, etag);
      }
      if (res.statusCode != 200) {
        await res.drain<void>();
        throw HttpException('HTTP ${res.statusCode}');
      }
      final body = await res.transform(const Utf8Decoder(allowMalformed: true)).join().timeout(const Duration(minutes: 3));
      return (200, body, res.headers.value(HttpHeaders.etagHeader));
    } finally {
      c.close();
    }
  }

  // ------------------------------------------------------------------ favourites and recently watched

  bool isFavorite(Channel c) => favorites.containsKey(c.url);

  void toggleFavorite(Channel c) {
    if (favorites.remove(c.url) == null) favorites[c.url] = c;
    _saveLibrary();
    notifyListeners();
  }

  void watched(Channel c) {
    recents.removeWhere((r) => r.url == c.url);
    recents.insert(0, c);
    if (recents.length > 50) recents.removeRange(50, recents.length);
    failing.remove(c.url);
    _saveLibrary();
    notifyListeners();
  }

  void markFailing(Channel c) {
    failing.add(c.url);
    notifyListeners();
  }

  /// True when the channel is gone from the latest catalogue of its section (removed upstream).
  bool isRemoved(Channel c) {
    final s = Section.values.where((s) => s.kind == c.kind).firstOrNull;
    final list = s == null ? null : lists[s];
    if (list == null) return false;
    return !list.any((x) => x.url == c.url);
  }

  Future<void> _loadLibrary() async {
    try {
      final j = jsonDecode(await _libraryFile.readAsString()) as Map<String, dynamic>;
      for (final f in (j['favorites'] as List<dynamic>? ?? const [])) {
        final c = Channel.fromJson(f as Map<String, dynamic>);
        favorites[c.url] = c;
      }
      recents
        ..clear()
        ..addAll([for (final r in (j['recents'] as List<dynamic>? ?? const [])) Channel.fromJson(r as Map<String, dynamic>)]);
    } catch (_) {
      // First start or an unreadable file: start empty.
    }
  }

  Future<void> _saveLibrary() async {
    try {
      await _libraryFile.writeAsString(jsonEncode({
        'favorites': [for (final c in favorites.values) c.toJson()],
        'recents': [for (final c in recents) c.toJson()],
      }));
    } catch (_) {}
  }
}
