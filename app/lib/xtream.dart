/// Xtream Codes logins: account check, live channels, films and series from a provider's `player_api.php`.
library;

import 'dart:convert';
import 'dart:isolate';

import 'm3u.dart';
import 'net.dart';
import 'sources.dart';

class XtreamAccount {
  const XtreamAccount({required this.status, this.expires, this.maxConnections = ''});
  final String status;
  final DateTime? expires;
  final String maxConnections;
}

class Episode {
  const Episode({required this.channel, required this.season, required this.number, this.plot = '', this.duration = ''});
  final Channel channel;
  final int season;
  final int number;
  final String plot;
  final String duration;
}

String _s(dynamic v) => v == null ? '' : '$v'.trim();

class XtreamClient {
  XtreamClient(this.source, {this.fetcher, this.format = 'ts'});

  final Source source;
  final Fetcher? fetcher;

  /// ts or m3u8, for live channels.
  final String format;

  String get base => normaliseServer(source.url);
  String get _u => Uri.encodeComponent(source.username);
  String get _p => Uri.encodeComponent(source.password);

  Uri api([Map<String, String> q = const {}]) => Uri.parse('$base/player_api.php')
      .replace(queryParameters: {'username': source.username, 'password': source.password, ...q});

  /// The provider's XMLTV guide for this login.
  Uri get guideUri => Uri.parse('$base/xmltv.php').replace(queryParameters: {'username': source.username, 'password': source.password});

  Future<dynamic> _json(Map<String, String> q) async {
    final text = await fetchText(api(q), fetcher: fetcher, headers: source.headers, maxMb: 300);
    if (text.trim().isEmpty) return null;
    try {
      return await decodeJsonInBackground(text);
    } on FormatException {
      throw FetchError('The server did not answer like an Xtream Codes server. Check the address.');
    }
  }

  /// Checks the login. Throws a [FetchError] with a readable reason when it is refused.
  Future<XtreamAccount> login() async {
    final j = await _json(const {});
    if (j is! Map) throw FetchError('The server did not answer like an Xtream Codes server. Check the address.');
    final info = j['user_info'];
    if (info is! Map || _s(info['auth']) == '0') throw FetchError('Wrong username or password.');
    final status = _s(info['status']);
    if (status.isNotEmpty && status.toLowerCase() != 'active') throw FetchError('This account is $status.');
    final exp = int.tryParse(_s(info['exp_date']));
    return XtreamAccount(
      status: status.isEmpty ? 'Active' : status,
      expires: exp == null || exp == 0 ? null : DateTime.fromMillisecondsSinceEpoch(exp * 1000, isUtc: true),
      maxConnections: _s(info['max_connections']),
    );
  }

  Future<Map<String, String>> _categories(String action) async {
    final j = await _json({'action': action});
    if (j is! List) return const {};
    return {
      for (final c in j)
        if (c is Map) _s(c['category_id']): _s(c['category_name'])
    };
  }

  /// Live channels, films and series of the account.
  Future<List<Channel>> load() async {
    final liveCats = await _categories('get_live_categories');
    final live = await _json({'action': 'get_live_streams'});
    final vodCats = await _categories('get_vod_categories');
    final vod = await _json({'action': 'get_vod_streams'});
    final seriesCats = await _categories('get_series_categories');
    final series = await _json({'action': 'get_series'});
    final args = (base, _u, _p, source.id, format, source.headers);
    return mapXtreamInBackground(args, live, liveCats, vod, vodCats, series, seriesCats);
  }

  /// Seasons and episodes of one series.
  Future<List<Episode>> episodes(Channel series) async {
    final j = await _json({'action': 'get_series_info', 'series_id': series.seriesId});
    if (j is! Map) return const [];
    final out = <Episode>[];
    final eps = j['episodes'];
    final groups = eps is Map ? eps.values : (eps is List ? eps : const []);
    for (final g in groups) {
      if (g is! List) continue;
      for (final e in g) {
        if (e is! Map) continue;
        final id = _s(e['id']);
        if (id.isEmpty) continue;
        final ext = _s(e['container_extension']).isEmpty ? 'mp4' : _s(e['container_extension']);
        final info = e['info'] is Map ? e['info'] as Map : const {};
        final season = int.tryParse(_s(e['season'])) ?? 1;
        final number = int.tryParse(_s(e['episode_num'])) ?? 0;
        final title = _s(e['title']).isEmpty ? 'Episode $number' : _s(e['title']);
        out.add(Episode(
          season: season,
          number: number,
          plot: _s(info['plot']),
          duration: _s(info['duration']),
          channel: Channel(
            name: title,
            url: '$base/series/$_u/$_p/$id.$ext',
            logo: _s(info['movie_image']).isNotEmpty ? _s(info['movie_image']) : series.logo,
            group: series.name,
            kind: 'episode',
            source: series.source,
            headers: series.headers,
          ),
        ));
      }
    }
    out.sort((a, b) => a.season != b.season ? a.season.compareTo(b.season) : a.number.compareTo(b.number));
    return out;
  }
}

Future<dynamic> decodeJsonInBackground(String text) => Isolate.run(() => jsonDecode(text));

Future<List<Channel>> mapXtreamInBackground(
  (String, String, String, String, String, Map<String, String>) args,
  dynamic live,
  Map<String, String> liveCats,
  dynamic vod,
  Map<String, String> vodCats,
  dynamic series,
  Map<String, String> seriesCats,
) =>
    Isolate.run(() => mapXtream(args, live, liveCats, vod, vodCats, series, seriesCats));

/// Builds channels from the decoded API answers (runs in a background isolate for large accounts).
List<Channel> mapXtream(
  (String, String, String, String, String, Map<String, String>) args,
  dynamic live,
  Map<String, String> liveCats,
  dynamic vod,
  Map<String, String> vodCats,
  dynamic series,
  Map<String, String> seriesCats,
) {
  final (base, u, p, source, format, headers) = args;
  final out = <Channel>[];
  var n = 0;
  for (final s in live is List ? live : const []) {
    if (s is! Map) continue;
    final id = _s(s['stream_id']);
    if (id.isEmpty) continue;
    n++;
    final radio = _s(s['stream_type']).contains('radio');
    out.add(Channel(
      name: _s(s['name']),
      url: '$base/live/$u/$p/$id.${radio ? 'ts' : format}',
      logo: _s(s['stream_icon']),
      group: liveCats[_s(s['category_id'])] ?? '',
      tvgId: _s(s['epg_channel_id']),
      kind: radio ? 'radio' : 'live',
      source: source,
      number: int.tryParse(_s(s['num'])) ?? n,
      headers: headers,
    ));
  }
  for (final s in vod is List ? vod : const []) {
    if (s is! Map) continue;
    final id = _s(s['stream_id']);
    if (id.isEmpty) continue;
    final ext = _s(s['container_extension']).isEmpty ? 'mp4' : _s(s['container_extension']);
    out.add(Channel(
      name: _s(s['name']),
      url: '$base/movie/$u/$p/$id.$ext',
      logo: _s(s['stream_icon']),
      group: vodCats[_s(s['category_id'])] ?? '',
      kind: 'movie',
      source: source,
      headers: headers,
      rating: _s(s['rating']),
      year: _s(s['year']),
    ));
  }
  for (final s in series is List ? series : const []) {
    if (s is! Map) continue;
    final id = _s(s['series_id']);
    if (id.isEmpty) continue;
    final released = _s(s['releaseDate']).isNotEmpty ? _s(s['releaseDate']) : _s(s['release_date']);
    out.add(Channel(
      name: _s(s['name']),
      url: '',
      logo: _s(s['cover']),
      group: seriesCats[_s(s['category_id'])] ?? '',
      kind: 'series',
      source: source,
      headers: headers,
      seriesId: id,
      rating: _s(s['rating']),
      year: released.length >= 4 ? released.substring(0, 4) : '',
      plot: _s(s['plot']),
    ));
  }
  return out;
}
