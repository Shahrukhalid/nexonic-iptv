/// Programme guide (XMLTV): from the Nexonic playlists' header, a playlist's own guide address or an Xtream login.
library;

import 'dart:convert';
import 'dart:io';

class Programme {
  const Programme(this.start, this.stop, this.title, [this.desc = '']);
  final DateTime start;
  final DateTime stop;
  final String title;
  final String desc;

  bool isOn(DateTime t) => !t.isBefore(start) && t.isBefore(stop);

  /// 0..1 through the programme at time t.
  double progress(DateTime t) {
    final total = stop.difference(start).inSeconds;
    if (total <= 0) return 0;
    return (t.difference(start).inSeconds / total).clamp(0.0, 1.0);
  }

  List<dynamic> toJson() => [start.millisecondsSinceEpoch, stop.millisecondsSinceEpoch, title, if (desc.isNotEmpty) desc];

  static Programme fromJson(List<dynamic> j) => Programme(
        DateTime.fromMillisecondsSinceEpoch((j[0] as num).toInt(), isUtc: true),
        DateTime.fromMillisecondsSinceEpoch((j[1] as num).toInt(), isUtc: true),
        '${j[2]}',
        j.length > 3 ? '${j[3]}' : '',
      );
}

class Guide {
  Guide(this.byChannel, [this.names = const {}]);
  static final empty = Guide(const {});

  /// Programmes per channel id (lower case), sorted by start.
  final Map<String, List<Programme>> byChannel;

  /// Display name (lower case) to channel id, for playlists whose entries have no tvg-id.
  final Map<String, String> names;

  bool get isEmpty => byChannel.isEmpty;
  int get channelCount => byChannel.length;

  /// Programmes for a channel, matched by tvg-id first and then by name.
  List<Programme> programmes(String tvgId, [String name = '']) {
    final byId = tvgId.isEmpty ? null : byChannel[tvgId.toLowerCase()];
    if (byId != null) return byId;
    final id = names[name.toLowerCase()];
    return id == null ? const [] : (byChannel[id] ?? const []);
  }

  /// The programme on now and the next one.
  (Programme?, Programme?) nowNext(String tvgId, [DateTime? at, String name = '']) {
    final list = programmes(tvgId, name);
    if (list.isEmpty) return (null, null);
    final t = at ?? DateTime.now().toUtc();
    for (var i = 0; i < list.length; i++) {
      if (list[i].isOn(t)) return (list[i], i + 1 < list.length ? list[i + 1] : null);
    }
    return (null, list.where((p) => p.start.isAfter(t)).firstOrNull);
  }

  /// This guide plus another; channels already present keep their programmes.
  Guide merge(Guide other) {
    if (other.isEmpty) return this;
    if (isEmpty) return other;
    return Guide({...other.byChannel, ...byChannel}, {...other.names, ...names});
  }

  Map<String, dynamic> toJson() => {
        'names': names,
        'programmes': {for (final e in byChannel.entries) e.key: [for (final p in e.value) p.toJson()]},
      };

  static Guide fromJson(Map<String, dynamic> j) => Guide(
        {
          for (final e in ((j['programmes'] as Map?) ?? const {}).entries)
            '${e.key}': [for (final p in e.value as List) Programme.fromJson(p as List)]
        },
        {for (final e in ((j['names'] as Map?) ?? const {}).entries) '${e.key}': '${e.value}'},
      );

  static final _prog = RegExp(r'<programme([^>]*)>(.*?)</programme>', dotAll: true);
  static final _chan = RegExp(r'<channel([^>]*)>(.*?)</channel>', dotAll: true);
  static final _attr = RegExp(r'([a-z]+)="([^"]*)"');
  static final _title = RegExp(r'<title[^>]*>(.*?)</title>', dotAll: true);
  static final _desc = RegExp(r'<desc[^>]*>(.*?)</desc>', dotAll: true);
  static final _display = RegExp(r'<display-name[^>]*>(.*?)</display-name>', dotAll: true);

  static DateTime? parseTime(String v) {
    final m = RegExp(r'^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})\s*([+-]\d{4})?').firstMatch(v.trim());
    if (m == null) return null;
    var t = DateTime.utc(int.parse(m[1]!), int.parse(m[2]!), int.parse(m[3]!), int.parse(m[4]!), int.parse(m[5]!),
        int.parse(m[6]!));
    final off = m[7];
    if (off != null) {
      final d = Duration(hours: int.parse(off.substring(1, 3)), minutes: int.parse(off.substring(3, 5)));
      t = off.startsWith('+') ? t.subtract(d) : t.add(d);
    }
    return t;
  }

  static String _unescape(String s) {
    var t = s.trim();
    if (t.startsWith('<![CDATA[') && t.endsWith(']]>')) t = t.substring(9, t.length - 3);
    return t
        .replaceAll('&lt;', '<')
        .replaceAll('&gt;', '>')
        .replaceAll('&quot;', '"')
        .replaceAll('&apos;', "'")
        .replaceAll('&#39;', "'")
        .replaceAll('&amp;', '&')
        .trim();
  }

  /// Parses XMLTV bytes (gzip-compressed or plain).
  static Guide parse(List<int> bytes, {DateTime? now}) {
    final raw = bytes.length > 2 && bytes[0] == 0x1f && bytes[1] == 0x8b ? gzip.decode(bytes) : bytes;
    return parseText(utf8.decode(raw, allowMalformed: true), now: now);
  }

  /// Keeps programmes from 6 hours ago to 3 days ahead, so very large guides stay small in memory.
  static Guide parseText(String xml, {DateTime? now}) {
    final t = (now ?? DateTime.now()).toUtc();
    final from = t.subtract(const Duration(hours: 6));
    final to = t.add(const Duration(days: 3));
    final out = <String, List<Programme>>{};
    for (final m in _prog.allMatches(xml)) {
      final attrs = {for (final a in _attr.allMatches(m[1]!)) a[1]!: a[2]!};
      final start = parseTime(attrs['start'] ?? '');
      final stop = parseTime(attrs['stop'] ?? '') ?? start?.add(const Duration(hours: 1));
      final ch = attrs['channel'];
      if (start == null || stop == null || ch == null) continue;
      if (stop.isBefore(from) || start.isAfter(to)) continue;
      final title = _title.firstMatch(m[2]!)?.group(1);
      if (title == null) continue;
      var desc = _unescape(_desc.firstMatch(m[2]!)?.group(1) ?? '');
      if (desc.length > 400) desc = '${desc.substring(0, 400)}…';
      out.putIfAbsent(ch.toLowerCase(), () => []).add(Programme(start, stop, _unescape(title), desc));
    }
    for (final l in out.values) {
      l.sort((a, b) => a.start.compareTo(b.start));
    }
    final names = <String, String>{};
    for (final m in _chan.allMatches(xml)) {
      final id = RegExp(r'id="([^"]*)"').firstMatch(m[1]!)?.group(1);
      if (id == null || !out.containsKey(id.toLowerCase())) continue;
      for (final d in _display.allMatches(m[2]!)) {
        names.putIfAbsent(_unescape(d[1]!).toLowerCase(), () => id.toLowerCase());
      }
    }
    return Guide(out, names);
  }
}
