/// Programme guide from the XMLTV file named in the playlist header (`x-tvg-url`), when one is published.
library;

import 'dart:convert';
import 'dart:io';

class Programme {
  const Programme(this.start, this.stop, this.title);
  final DateTime start;
  final DateTime stop;
  final String title;
}

class Guide {
  Guide(this.byChannel);
  static final empty = Guide(const {});

  final Map<String, List<Programme>> byChannel;

  bool get isEmpty => byChannel.isEmpty;

  /// The programme on now and the next one for a tvg-id.
  (Programme?, Programme?) nowNext(String tvgId, [DateTime? at]) {
    final list = byChannel[tvgId.toLowerCase()];
    if (list == null) return (null, null);
    final t = at ?? DateTime.now().toUtc();
    for (var i = 0; i < list.length; i++) {
      if (!t.isBefore(list[i].start) && t.isBefore(list[i].stop)) {
        return (list[i], i + 1 < list.length ? list[i + 1] : null);
      }
    }
    return (null, list.where((p) => p.start.isAfter(t)).firstOrNull);
  }

  static final _prog = RegExp(r'<programme([^>]*)>(.*?)</programme>', dotAll: true);
  static final _attr = RegExp(r'([a-z]+)="([^"]*)"');
  static final _title = RegExp(r'<title[^>]*>(.*?)</title>', dotAll: true);

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

  static String _unescape(String s) => s
      .replaceAll('&lt;', '<')
      .replaceAll('&gt;', '>')
      .replaceAll('&quot;', '"')
      .replaceAll('&apos;', "'")
      .replaceAll('&amp;', '&')
      .trim();

  /// Parses XMLTV bytes (gzip-compressed or plain).
  static Guide parse(List<int> bytes) {
    final raw = bytes.length > 2 && bytes[0] == 0x1f && bytes[1] == 0x8b ? gzip.decode(bytes) : bytes;
    return parseText(utf8.decode(raw, allowMalformed: true));
  }

  static Guide parseText(String xml) {
    final out = <String, List<Programme>>{};
    for (final m in _prog.allMatches(xml)) {
      final attrs = {for (final a in _attr.allMatches(m[1]!)) a[1]!: a[2]!};
      final start = parseTime(attrs['start'] ?? '');
      final stop = parseTime(attrs['stop'] ?? '');
      final ch = attrs['channel'];
      final title = _title.firstMatch(m[2]!)?.group(1);
      if (start == null || ch == null || title == null) continue;
      out.putIfAbsent(ch.toLowerCase(), () => []).add(Programme(start, stop ?? start.add(const Duration(hours: 1)), _unescape(title)));
    }
    for (final l in out.values) {
      l.sort((a, b) => a.start.compareTo(b.start));
    }
    return Guide(out);
  }
}
