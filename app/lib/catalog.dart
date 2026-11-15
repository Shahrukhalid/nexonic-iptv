/// Everything the app shows: the free Nexonic catalogue and the playlists people add (M3U links, M3U files and
/// Xtream Codes logins), each cached on disk for offline use and refreshed in the background, plus favourites,
/// history, resume points and the programme guide.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:isolate';

import 'package:flutter/foundation.dart';

import 'epg.dart';
import 'm3u.dart';
import 'net.dart';
import 'sources.dart';
import 'xtream.dart';

const siteBase = 'https://shahrukhalid.github.io/nexonic-iptv/playlists';
const mirrorBase = 'https://raw.githubusercontent.com/Shahrukhalid/nexonic-iptv/main/playlists';

/// Item kinds in display order.
const kinds = ['live', 'movie', 'series', 'radio', 'media'];

/// Files of the Nexonic catalogue.
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

/// What a refresh changed.
class Diff {
  const Diff(this.added, this.removed, this.total);
  final int added;
  final int removed;
  final int total;
}

Diff diffOf(List<Channel> before, List<Channel> after) {
  final a = {for (final c in before) c.key};
  final b = {for (final c in after) c.key};
  return Diff(b.difference(a).length, a.difference(b).length, after.length);
}

/// Filters a list. Empty values mean "any".
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
          (group.isEmpty || c.categories.contains(group)) &&
          (only == null || only.contains(c.url)))
        c
  ];
}

/// Category names with item counts, largest first, then by name.
List<(String, int)> groupCounts(List<Channel> items) {
  final counts = <String, int>{};
  for (final c in items) {
    for (final g in c.categories) {
      counts[g] = (counts[g] ?? 0) + 1;
    }
  }
  final out = [for (final e in counts.entries) (e.key, e.value)];
  out.sort((a, b) => a.$1.toLowerCase().compareTo(b.$1.toLowerCase()));
  return out;
}

class ResumePoint {
  const ResumePoint(this.position, this.duration);
  final Duration position;
  final Duration duration;
  double get fraction => duration.inSeconds <= 0 ? 0 : (position.inSeconds / duration.inSeconds).clamp(0.0, 1.0);
}

class Catalog extends ChangeNotifier {
  Catalog(this.dir, {this.fetcher, Set<Section>? nexonicSections})
      : nexonicSections = nexonicSections ?? Section.values.toSet();

  final Directory dir;

  /// Replaces network access in tests (see [Fetcher]).
  final Fetcher? fetcher;

  /// The Nexonic files to read (the CI self-test only needs live TV).
  final Set<Section> nexonicSections;

  Settings settings = Settings();
  final List<Source> sources = [];
  final Map<String, List<Channel>> _items = {};
  final Map<String, Guide> _guides = {};
  final Map<String, List<String>> _guideUrls = {};
  final Map<String, Set<String>> _keys = {};
  final Set<String> busy = {};
  final Map<String, String> countryNames = {};
  final Map<String, Channel> favorites = {};
  final List<Channel> recents = [];
  final Map<String, ResumePoint> resume = {};
  final Set<String> failing = {};
  final Map<String, Future<List<Episode>>> _episodes = {};
  String? lastChange;
  bool loaded = false;

  /// Shows one playlist only (null = every enabled playlist).
  String? activeSource;

  Timer? _timer;
  Map<String, dynamic> _meta = {};
  final Map<String, List<Channel>> _view = {};
  Guide? _guide;
  bool _disposed = false;

  File get _settingsFile => File('${dir.path}/settings.json');
  File get _sourcesFile => File('${dir.path}/sources.json');
  File get _metaFile => File('${dir.path}/meta.json');
  File get _libraryFile => File('${dir.path}/library.json');
  Directory _sourceDir(String id) => Directory('${dir.path}/sources/$id');
  File _cacheFile(String path) => File('${dir.path}/cache/${path.replaceAll('/', '_')}');

  // ------------------------------------------------------------------ start, refresh, timers

  Future<void> start({bool background = true}) async {
    await dir.create(recursive: true);
    await _loadSettings();
    _meta = await _readJson(_metaFile) as Map<String, dynamic>? ?? {};
    for (final e in ((_meta['guideUrls'] as Map?) ?? const {}).entries) {
      _guideUrls['${e.key}'] = [for (final u in e.value as List) '$u'];
    }
    await _loadSources();
    await _loadLibrary();
    for (final s in sources.where((s) => s.enabled)) {
      await _loadCached(s);
    }
    loaded = true;
    _changed();
    if (background) {
      unawaited(refreshStale());
      _timer = Timer.periodic(const Duration(minutes: 30), (_) => refreshStale());
    }
  }

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

  void _changed() {
    _view.clear();
    _guide = null;
    notifyListeners();
  }

  bool get isBusy => busy.isNotEmpty;

  Source? source(String id) => sources.where((s) => s.id == id).firstOrNull;

  /// Refreshes playlists whose last update is older than the refresh interval (or that never loaded).
  Future<void> refreshStale() async {
    final hours = settings.refreshHours;
    for (final s in [...sources]) {
      if (!s.enabled || busy.contains(s.id) || s.type == SourceType.file && _items.containsKey(s.id)) continue;
      final age = s.lastSync == null ? null : DateTime.now().difference(s.lastSync!);
      if (age == null || !_items.containsKey(s.id) || (hours > 0 && age > Duration(hours: hours))) {
        await refreshSource(s.id);
      }
    }
  }

  Future<void> refreshAll() async {
    for (final s in [...sources]) {
      if (s.enabled) await refreshSource(s.id);
    }
  }

  /// Downloads one playlist again. Returns an error message, or null when it worked.
  Future<String?> refreshSource(String id) async {
    final s = source(id);
    if (s == null || busy.contains(id)) return null;
    busy.add(id);
    notifyListeners();
    String? err;
    try {
      final before = _items[id] ?? const <Channel>[];
      final items = await _download(s);
      if (items.isEmpty) throw FetchError('The playlist has no playable entries.');
      final d = diffOf(before, items);
      if (before.isNotEmpty && (d.added > 0 || d.removed > 0)) {
        lastChange = '${s.name}: ${d.added} new, ${d.removed} removed';
      }
      _setItems(s, items);
      s
        ..lastSync = DateTime.now()
        ..error = null;
      await _saveItems(id, items);
    } catch (e) {
      err = e is FetchError ? e.message : 'Could not read the playlist ($e).';
      s.error = err;
    } finally {
      busy.remove(id);
      await _saveSources();
      _changed();
    }
    if (err == null) await _refreshGuide(s);
    return err;
  }

  void _setItems(Source s, List<Channel> items) {
    _items[s.id] = items;
    _keys.remove(s.id);
    final counts = <String, int>{};
    for (final c in items) {
      counts[c.kind] = (counts[c.kind] ?? 0) + 1;
    }
    s.counts = counts;
  }

  // ------------------------------------------------------------------ downloading each kind of playlist

  Future<List<Channel>> _download(Source s) async {
    switch (s.type) {
      case SourceType.nexonic:
        return _downloadNexonic();
      case SourceType.m3u:
        final text = await fetchText(Uri.parse(s.url.trim()), fetcher: fetcher, headers: s.headers, maxMb: 300);
        return _parsePlaylist(s, text);
      case SourceType.file:
        final f = File('${_sourceDir(s.id).path}/playlist.m3u');
        if (!await f.exists()) throw FetchError('The playlist file is missing. Add it again.');
        return _parsePlaylist(s, await f.readAsString());
      case SourceType.xtream:
        final client = XtreamClient(s, fetcher: fetcher, format: settings.xtreamFormat);
        final account = await client.login();
        s
          ..expires = account.expires
          ..account = account.status;
        _guideUrls[s.id] = [client.guideUri.toString()];
        return client.load();
    }
  }

  Future<List<Channel>> _parsePlaylist(Source s, String text) async {
    if (!text.trimLeft().replaceFirst('﻿', '').startsWith('#EXTM3U') && !text.contains('#EXTINF')) {
      throw FetchError('This is not an M3U playlist.');
    }
    final id = s.id;
    _guideUrls[id] = guideUrls(text);
    final items = await parseInBackground(text, source: id, classify: true);
    return _number(items);
  }

  static List<Channel> _number(List<Channel> items) {
    var n = 0;
    return [
      for (final c in items)
        if (c.isLive && c.number == 0) c.copyWith(number: ++n) else c
    ];
  }

  Future<List<Channel>> _downloadNexonic() async {
    final out = <Channel>[];
    var any = false;
    for (final sec in Section.values.where(nexonicSections.contains)) {
      final text = await _nexonicFile(sec.path);
      if (text == null) continue;
      any = true;
      if (sec == Section.live) _guideUrls['nexonic'] = guideUrls(text);
      final kind = sec.kind;
      out.addAll(await parseInBackground(text, kind: kind, source: 'nexonic'));
    }
    if (!any) throw FetchError('Could not download the Nexonic catalogue. Check the internet connection.');
    // Categories (news, kids, …) come from the category playlists listed in index.json.
    final tags = <String, List<String>>{};
    final index = await _nexonicFile('index.json');
    if (index != null) {
      try {
        final rows = (jsonDecode(index) as Map<String, dynamic>)['playlists'] as List<dynamic>;
        for (final r in rows.cast<Map<String, dynamic>>()) {
          if (r['kind'] == 'country') countryNames['${r['key']}'.toUpperCase()] = '${r['name']}';
        }
        if (nexonicSections.contains(Section.live)) {
          for (final r in rows.cast<Map<String, dynamic>>().where((r) => r['kind'] == 'category')) {
            final path = '${r['path']}'.replaceFirst('playlists/', '');
            final text = await _nexonicFile(path);
            if (text == null) continue;
            final name = _titleCase('${r['key']}');
            for (final c in parseM3u(text)) {
              tags.putIfAbsent(c.url, () => []).add(name);
            }
          }
        }
        _meta['countryNames'] = countryNames;
      } catch (_) {
        // Categories are optional.
      }
    }
    var n = 0;
    return [
      for (final c in out)
        c.kind == 'live' ? c.copyWith(number: ++n, tags: tags[c.url] ?? const ['Other']) : c
    ];
  }

  static String _titleCase(String s) =>
      s.split(RegExp(r'[-_ ]')).where((w) => w.isNotEmpty).map((w) => w[0].toUpperCase() + w.substring(1)).join(' ');

  /// A Nexonic file: the website first, then the raw mirror, then the cached copy (so the app works offline).
  Future<String?> _nexonicFile(String path) async {
    final cache = _cacheFile(path);
    if (fetcher != null) {
      final t = await fetcher!(Uri.parse('$siteBase/$path'));
      if (t != null) {
        await cache.parent.create(recursive: true);
        await cache.writeAsString(t);
        return t;
      }
      return await cache.exists() ? cache.readAsString() : null;
    }
    final etags = Map<String, dynamic>.from((_meta['etags'] as Map?) ?? const {});
    for (final base in [siteBase, mirrorBase]) {
      try {
        final url = '$base/$path';
        final has = await cache.exists();
        final r = await download(Uri.parse(url), etag: has ? etags[url] as String? : null, maxMb: 100);
        if (r.status == 304) return await cache.readAsString();
        final text = r.text;
        await cache.parent.create(recursive: true);
        await cache.writeAsString(text);
        if (r.etag != null) {
          etags[url] = r.etag;
          _meta['etags'] = etags;
        }
        return text;
      } catch (_) {
        continue;
      }
    }
    return await cache.exists() ? cache.readAsString() : null;
  }

  // ------------------------------------------------------------------ programme guide

  Future<void> _refreshGuide(Source s) async {
    final urls = [if (s.epgUrl.trim().isNotEmpty) s.epgUrl.trim(), ...?_guideUrls[s.id]];
    _meta['guideUrls'] = _guideUrls;
    await _saveMeta();
    for (final u in urls.toSet()) {
      try {
        final bytes = await fetchBytes(Uri.parse(u), fetcher: fetcher, headers: s.headers, maxMb: 250);
        final g = await guideFromBytes(bytes);
        if (g.isEmpty) continue;
        _guides[s.id] = g;
        final text = await guideToText(g);
        final f = File('${_sourceDir(s.id).path}/guide.json');
        await f.parent.create(recursive: true);
        await f.writeAsString(text);
        _changed();
        return;
      } catch (_) {
        continue; // A missing guide only hides programme titles.
      }
    }
  }

  /// The merged guide of every enabled playlist.
  Guide get guide {
    final g = _guide;
    if (g != null) return g;
    var out = Guide.empty;
    for (final s in sources.where((s) => s.enabled)) {
      final x = _guides[s.id];
      if (x != null) out = out.merge(x);
    }
    return _guide = out;
  }

  (Programme?, Programme?) nowNext(Channel c, [DateTime? at]) => guide.nowNext(c.tvgId, at, c.name);

  // ------------------------------------------------------------------ what the pages show

  Iterable<Source> get _visible =>
      sources.where((s) => s.enabled && (activeSource == null || s.id == activeSource));

  /// Every item of one kind from the visible playlists.
  List<Channel> items(String kind) => _view.putIfAbsent(kind, () {
        return [
          for (final s in _visible)
            for (final c in _items[s.id] ?? const <Channel>[])
              if (c.kind == kind) c
        ];
      });

  int count(String kind) => items(kind).length;

  bool get hasNexonic => sources.any((s) => s.isBuiltIn && s.enabled);

  bool get isEmpty => kinds.every((k) => count(k) == 0);

  /// Kinds that have at least one item (live TV is always shown).
  List<String> get presentKinds => [for (final k in kinds) if (k == 'live' || count(k) > 0) k];

  /// True when the item is gone from the latest copy of its playlist (removed upstream).
  bool isRemoved(Channel c) {
    final list = _items[c.source];
    if (list == null) return false;
    final keys = _keys.putIfAbsent(c.source, () => {for (final x in list) x.key});
    return !keys.contains(c.key);
  }

  /// Puts items in place without downloading (tests and screenshots).
  @visibleForTesting
  void debugSetItems(String sourceId, List<Channel> items, {Guide? guide}) {
    final s = source(sourceId) ?? (Source(id: sourceId, type: SourceType.m3u, name: sourceId)..lastSync = DateTime.now());
    if (!sources.contains(s)) sources.add(s);
    _setItems(s, items);
    if (guide != null) _guides[sourceId] = guide;
    loaded = true;
    _changed();
  }

  // ------------------------------------------------------------------ adding, editing and removing playlists

  /// Adds a playlist and downloads it. Returns an error message (and does not keep it) or null.
  Future<String?> addSource(Source s, {String? fileText}) async {
    if (fileText != null) {
      final f = File('${_sourceDir(s.id).path}/playlist.m3u');
      await f.parent.create(recursive: true);
      await f.writeAsString(fileText);
    }
    sources.add(s);
    final err = await refreshSource(s.id);
    if (err != null) {
      sources.remove(s);
      _items.remove(s.id);
      try {
        await _sourceDir(s.id).delete(recursive: true);
      } catch (_) {}
      await _saveSources();
      _changed();
    }
    return err;
  }

  Future<String?> updateSource(Source s, {String? fileText}) async {
    if (fileText != null) {
      final f = File('${_sourceDir(s.id).path}/playlist.m3u');
      await f.parent.create(recursive: true);
      await f.writeAsString(fileText);
    }
    _guides.remove(s.id);
    _episodes.clear();
    await _saveSources();
    return refreshSource(s.id);
  }

  Future<void> removeSource(String id) async {
    sources.removeWhere((s) => s.id == id && !s.isBuiltIn);
    _items.remove(id);
    _guides.remove(id);
    _guideUrls.remove(id);
    if (activeSource == id) activeSource = null;
    try {
      await _sourceDir(id).delete(recursive: true);
    } catch (_) {}
    await _saveSources();
    _changed();
  }

  Future<void> setEnabled(Source s, bool on) async {
    s.enabled = on;
    if (!on && activeSource == s.id) activeSource = null;
    await _saveSources();
    if (on && !_items.containsKey(s.id)) {
      await _loadCached(s);
      if (!_items.containsKey(s.id)) unawaited(refreshSource(s.id));
    }
    _changed();
  }

  void showSource(String? id) {
    activeSource = id;
    _changed();
  }

  /// Seasons and episodes of an Xtream series (cached for the session).
  Future<List<Episode>> episodes(Channel series) {
    final s = source(series.source);
    if (s == null || s.type != SourceType.xtream) return Future.value(const []);
    return _episodes.putIfAbsent(series.key, () {
      final f = XtreamClient(s, fetcher: fetcher, format: settings.xtreamFormat).episodes(series);
      f.catchError((Object _) {
        _episodes.remove(series.key);
        return const <Episode>[];
      });
      return f;
    });
  }

  // ------------------------------------------------------------------ settings

  Future<void> saveSettings() async {
    await _writeJson(_settingsFile, settings.toJson());
    _changed();
  }

  Future<void> _loadSettings() async {
    final j = await _readJson(_settingsFile);
    final hw = !Platform.isMacOS;
    settings = j is Map<String, dynamic> ? Settings.fromJson(j, hardwareDefault: hw) : Settings(hardwareDecoding: hw);
  }

  // ------------------------------------------------------------------ favourites, history and resume points

  bool isFavorite(Channel c) => favorites.containsKey(c.key);

  void toggleFavorite(Channel c) {
    if (favorites.remove(c.key) == null) favorites[c.key] = c;
    _saveLibrary();
    notifyListeners();
  }

  List<Channel> get favoriteList => favorites.values.toList().reversed.toList();

  void watched(Channel c) {
    recents.removeWhere((r) => r.key == c.key);
    recents.insert(0, c);
    if (recents.length > 60) recents.removeRange(60, recents.length);
    failing.remove(c.key);
    _saveLibrary();
    notifyListeners();
  }

  void markFailing(Channel c) {
    failing.add(c.key);
    notifyListeners();
  }

  /// Saves where a film or episode was stopped. Near the start or the end, the point is cleared.
  void setProgress(Channel c, Duration position, Duration duration) {
    if (c.isLive || duration.inSeconds <= 0) return;
    if (position.inSeconds < 30 || duration - position < const Duration(minutes: 2)) {
      if (resume.remove(c.key) != null) _saveLibrary();
      return;
    }
    resume[c.key] = ResumePoint(position, duration);
    _saveLibrary();
  }

  Future<void> clearHistory() async {
    recents.clear();
    resume.clear();
    await _saveLibrary();
    notifyListeners();
  }

  Future<void> clearFavorites() async {
    favorites.clear();
    await _saveLibrary();
    notifyListeners();
  }

  // ------------------------------------------------------------------ files

  Future<void> _loadSources() async {
    final j = await _readJson(_sourcesFile);
    sources
      ..clear()
      ..addAll([
        if (j is List)
          for (final s in j)
            if (s is Map<String, dynamic>) Source.fromJson(s)
      ]);
    if (!sources.any((s) => s.isBuiltIn)) sources.insert(0, Source.nexonic());
    for (final e in ((_meta['countryNames'] as Map?) ?? const {}).entries) {
      countryNames['${e.key}'] = '${e.value}';
    }
  }

  Future<void> _saveSources() => _writeJson(_sourcesFile, [for (final s in sources) s.toJson()]);

  Future<void> _saveMeta() => _writeJson(_metaFile, _meta);

  Future<void> _saveItems(String id, List<Channel> items) async {
    final f = File('${_sourceDir(id).path}/channels.json');
    await f.parent.create(recursive: true);
    final text = await encodeChannels(items);
    await f.writeAsString(text);
    await _saveMeta();
  }

  Future<void> _loadCached(Source s) async {
    final f = File('${_sourceDir(s.id).path}/channels.json');
    if (await f.exists()) {
      try {
        final text = await f.readAsString();
        final items = await decodeChannels(text);
        _setItems(s, items);
      } catch (_) {
        // A damaged cache is replaced by the next refresh.
      }
    }
    final g = File('${_sourceDir(s.id).path}/guide.json');
    if (await g.exists()) {
      try {
        final text = await g.readAsString();
        _guides[s.id] = await guideFromText(text);
      } catch (_) {}
    }
  }

  Future<void> _loadLibrary() async {
    final j = await _readJson(_libraryFile);
    if (j is! Map<String, dynamic>) return;
    try {
      for (final f in (j['favorites'] as List<dynamic>? ?? const [])) {
        final c = Channel.fromJson(f as Map<String, dynamic>);
        favorites[c.key] = c;
      }
      recents
        ..clear()
        ..addAll([for (final r in (j['recents'] as List<dynamic>? ?? const [])) Channel.fromJson(r as Map<String, dynamic>)]);
      for (final e in ((j['resume'] as Map?) ?? const {}).entries) {
        final v = e.value as List;
        resume['${e.key}'] = ResumePoint(Duration(seconds: (v[0] as num).toInt()), Duration(seconds: (v[1] as num).toInt()));
      }
    } catch (_) {
      // An unreadable file: keep what was read.
    }
  }

  Future<void> _saveLibrary() => _writeJson(_libraryFile, {
        'favorites': [for (final c in favorites.values) c.toJson()],
        'recents': [for (final c in recents) c.toJson()],
        'resume': {for (final e in resume.entries) e.key: [e.value.position.inSeconds, e.value.duration.inSeconds]},
      });

  static Future<dynamic> _readJson(File f) async {
    try {
      if (!await f.exists()) return null;
      return jsonDecode(await f.readAsString());
    } catch (_) {
      return null;
    }
  }

  Future<void> _writeJson(File f, Object value) async {
    try {
      await f.parent.create(recursive: true);
      await f.writeAsString(jsonEncode(value));
    } catch (_) {}
  }
}

// Heavy parsing runs in background isolates. These top-level helpers keep the closures free of `this`.

Future<List<Channel>> parseInBackground(String text, {String kind = 'live', String source = '', bool classify = false}) =>
    Isolate.run(() => parseM3u(text, kind: kind, source: source, classify: classify));

Future<String> encodeChannels(List<Channel> items) => Isolate.run(() => jsonEncode([for (final c in items) c.toJson()]));

Future<List<Channel>> decodeChannels(String text) =>
    Isolate.run(() => [for (final m in jsonDecode(text) as List) Channel.fromJson(m as Map<String, dynamic>)]);

Future<Guide> guideFromBytes(List<int> bytes) => Isolate.run(() => Guide.parse(bytes));

Future<String> guideToText(Guide g) => Isolate.run(() => jsonEncode(g.toJson()));

Future<Guide> guideFromText(String text) => Isolate.run(() => Guide.fromJson(jsonDecode(text) as Map<String, dynamic>));

/// A new playlist id.
String newSourceId() => 's${DateTime.now().microsecondsSinceEpoch.toRadixString(36)}';
