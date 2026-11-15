/// Playlists the app reads (the free Nexonic catalogue and any the user adds) and the user's settings.
library;

enum SourceType {
  nexonic('Nexonic free TV'),
  m3u('M3U link'),
  file('M3U file'),
  xtream('Xtream Codes login');

  const SourceType(this.label);
  final String label;
}

class Source {
  Source({
    required this.id,
    required this.type,
    required this.name,
    this.url = '',
    this.username = '',
    this.password = '',
    this.epgUrl = '',
    this.userAgent = '',
    this.enabled = true,
    this.lastSync,
    this.error,
    this.counts = const {},
    this.expires,
    this.account = '',
  });

  final String id;
  final SourceType type;
  String name;

  /// Playlist address (M3U link) or server address (Xtream Codes).
  String url;
  String username;
  String password;

  /// Optional XMLTV guide address.
  String epgUrl;

  /// Optional User-Agent some providers require.
  String userAgent;
  bool enabled;

  DateTime? lastSync;
  String? error;

  /// Items per kind after the last sync (live, movie, series, radio, media).
  Map<String, int> counts;

  /// Xtream account expiry and status, when the provider reports them.
  DateTime? expires;
  String account;

  bool get isBuiltIn => type == SourceType.nexonic;
  int get total => counts.values.fold(0, (a, b) => a + b);

  Map<String, String> get headers => userAgent.isEmpty ? const {} : {'User-Agent': userAgent};

  Map<String, dynamic> toJson() => {
        'id': id,
        'type': type.name,
        'name': name,
        'url': url,
        if (username.isNotEmpty) 'username': username,
        if (password.isNotEmpty) 'password': password,
        if (epgUrl.isNotEmpty) 'epgUrl': epgUrl,
        if (userAgent.isNotEmpty) 'userAgent': userAgent,
        'enabled': enabled,
        if (lastSync != null) 'lastSync': lastSync!.toIso8601String(),
        if (error != null) 'error': error,
        'counts': counts,
        if (expires != null) 'expires': expires!.toIso8601String(),
        if (account.isNotEmpty) 'account': account,
      };

  static Source fromJson(Map<String, dynamic> j) => Source(
        id: '${j['id']}',
        type: SourceType.values.firstWhere((t) => t.name == j['type'], orElse: () => SourceType.m3u),
        name: '${j['name'] ?? ''}',
        url: '${j['url'] ?? ''}',
        username: '${j['username'] ?? ''}',
        password: '${j['password'] ?? ''}',
        epgUrl: '${j['epgUrl'] ?? ''}',
        userAgent: '${j['userAgent'] ?? ''}',
        enabled: j['enabled'] != false,
        lastSync: DateTime.tryParse('${j['lastSync'] ?? ''}'),
        error: j['error'] as String?,
        counts: {for (final e in ((j['counts'] as Map?) ?? const {}).entries) '${e.key}': (e.value as num).toInt()},
        expires: DateTime.tryParse('${j['expires'] ?? ''}'),
        account: '${j['account'] ?? ''}',
      );

  static Source nexonic() => Source(id: 'nexonic', type: SourceType.nexonic, name: 'Nexonic free TV');
}

class Settings {
  Settings({
    this.startPage = 'home',
    this.hardwareDecoding = true,
    this.bufferMb = 64,
    this.refreshHours = 6,
    this.xtreamFormat = 'ts',
    this.resume = true,
    this.welcomed = false,
    this.livePreview = true,
  });

  /// home or live.
  String startPage;
  bool hardwareDecoding;
  int bufferMb;

  /// 0 turns automatic refresh off.
  int refreshHours;

  /// ts or m3u8 for Xtream live streams.
  String xtreamFormat;
  bool resume;
  bool welcomed;

  /// Plays the selected channel in the Live TV preview panel.
  bool livePreview;

  Map<String, dynamic> toJson() => {
        'startPage': startPage,
        'hardwareDecoding': hardwareDecoding,
        'bufferMb': bufferMb,
        'refreshHours': refreshHours,
        'xtreamFormat': xtreamFormat,
        'resume': resume,
        'welcomed': welcomed,
        'livePreview': livePreview,
      };

  static Settings fromJson(Map<String, dynamic> j, {required bool hardwareDefault}) => Settings(
        startPage: '${j['startPage'] ?? 'home'}',
        hardwareDecoding: (j['hardwareDecoding'] as bool?) ?? hardwareDefault,
        bufferMb: (j['bufferMb'] as num?)?.toInt() ?? 64,
        refreshHours: (j['refreshHours'] as num?)?.toInt() ?? 6,
        xtreamFormat: '${j['xtreamFormat'] ?? 'ts'}',
        resume: j['resume'] != false,
        welcomed: j['welcomed'] == true,
        livePreview: j['livePreview'] != false,
      );
}

/// Turns what people type as a server address into `scheme://host[:port]`.
String normaliseServer(String input) {
  var s = input.trim();
  if (s.isEmpty) return s;
  if (!s.startsWith('http://') && !s.startsWith('https://')) s = 'http://$s';
  final u = Uri.tryParse(s);
  if (u == null || u.host.isEmpty) return s;
  return '${u.scheme}://${u.host}${u.hasPort ? ':${u.port}' : ''}';
}
