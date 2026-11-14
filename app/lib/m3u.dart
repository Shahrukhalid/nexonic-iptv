/// Extended M3U parsing for the Nexonic playlists.
library;

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
  });

  final String name;
  final String url;
  final String logo;
  final String group;
  final String country;
  final String language;
  final String tvgId;
  final String kind;

  bool get isRadio => kind == 'radio';

  Map<String, String> toJson() => {
        'name': name,
        'url': url,
        'logo': logo,
        'group': group,
        'country': country,
        'language': language,
        'tvgId': tvgId,
        'kind': kind,
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
      );
}

final _attr = RegExp(r'([A-Za-z0-9_-]+)="([^"]*)"');

/// Attributes of the `#EXTM3U` header line (for example `x-tvg-url`).
Map<String, String> headerAttrs(String text) {
  final end = text.indexOf('\n');
  final first = (end < 0 ? text : text.substring(0, end)).trim();
  if (!first.startsWith('#EXTM3U')) return const {};
  return {for (final m in _attr.allMatches(first)) m.group(1)!.toLowerCase(): m.group(2)!};
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

/// Channels of an extended M3U text. Entries without an http(s) address are skipped, and an address listed twice
/// is kept once.
List<Channel> parseM3u(String text, {String kind = 'live'}) {
  final out = <Channel>[];
  final seen = <String>{};
  Map<String, String>? attrs;
  String title = '';
  for (final raw in text.split('\n')) {
    final line = raw.trim();
    if (line.isEmpty) continue;
    if (line.startsWith('#EXTINF:')) {
      final (info, name) = _splitInfo(line.substring(8));
      attrs = {for (final m in _attr.allMatches(info)) m.group(1)!.toLowerCase(): m.group(2)!};
      title = name;
      continue;
    }
    if (line.startsWith('#')) continue;
    final a = attrs;
    attrs = null;
    if (a == null) continue;
    final lower = line.toLowerCase();
    if (!(lower.startsWith('http://') || lower.startsWith('https://')) || !seen.add(line)) continue;
    out.add(Channel(
      name: title.isNotEmpty ? title : (a['tvg-name'] ?? line),
      url: line,
      logo: a['tvg-logo'] ?? '',
      group: a['group-title'] ?? '',
      country: (a['tvg-country'] ?? '').toUpperCase(),
      language: a['tvg-language'] ?? '',
      tvgId: a['tvg-id'] ?? '',
      kind: kind,
    ));
  }
  return out;
}
