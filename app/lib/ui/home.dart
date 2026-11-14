import 'package:flutter/material.dart';

import '../catalog.dart';
import '../m3u.dart';
import 'player.dart';
import 'theme.dart';
import 'widgets.dart';

/// Pages of the app: the five catalogue sections plus favourites and recently watched.
enum AppPage { live, movies, series, radio, media, favorites, recent }

extension on AppPage {
  Section? get section => switch (this) {
        AppPage.live => Section.live,
        AppPage.movies => Section.movies,
        AppPage.series => Section.series,
        AppPage.radio => Section.radio,
        AppPage.media => Section.media,
        _ => null,
      };

  String get label => section?.label ?? (this == AppPage.favorites ? 'Favourites' : 'Recent');

  IconData get icon => switch (this) {
        AppPage.live => Icons.live_tv_rounded,
        AppPage.movies => Icons.movie_rounded,
        AppPage.series => Icons.video_library_rounded,
        AppPage.radio => Icons.radio_rounded,
        AppPage.media => Icons.public_rounded,
        AppPage.favorites => Icons.star_rounded,
        AppPage.recent => Icons.history_rounded,
      };
}

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, required this.catalog});
  final Catalog catalog;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  AppPage page = AppPage.live;
  String query = '';
  String country = '';
  String language = '';
  String group = '';
  IndexEntry? category;
  Set<String>? categoryUrls;
  String? _shownChange;

  Catalog get catalog => widget.catalog;

  @override
  void initState() {
    super.initState();
    catalog.addListener(_onCatalog);
  }

  @override
  void dispose() {
    catalog.removeListener(_onCatalog);
    super.dispose();
  }

  void _onCatalog() {
    final change = catalog.lastChange;
    if (change != null && change != _shownChange && mounted) {
      _shownChange = change;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Updated · $change')));
    }
    if (mounted) setState(() {});
  }

  void _select(AppPage p) {
    setState(() {
      page = p;
      country = language = group = '';
      category = null;
      categoryUrls = null;
    });
    final s = p.section;
    if (s != null) catalog.ensure(s);
  }

  Future<void> _pickCategory(String path) async {
    if (path.isEmpty) {
      setState(() {
        category = null;
        categoryUrls = null;
      });
      return;
    }
    final e = catalog.entries('category').firstWhere((e) => e.path == path);
    final urls = await catalog.playlistUrls(e);
    if (mounted) {
      setState(() {
        category = e;
        categoryUrls = urls;
      });
    }
  }

  List<Channel> get _source => switch (page) {
        AppPage.favorites => catalog.favorites.values.toList(),
        AppPage.recent => catalog.recents,
        _ => catalog.lists[page.section] ?? const [],
      };

  void _open(List<Channel> list, int i) {
    Navigator.of(context).push(MaterialPageRoute(builder: (_) => PlayerScreen(catalog: catalog, list: list, index: i)));
  }

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= 840;
    final items = filterChannels(_source, query: query, country: country, language: language, group: group, only: categoryUrls);
    final body = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _header(wide),
        if (!wide) _sectionChips(),
        _filters(),
        Expanded(child: _grid(items, wide)),
      ],
    );
    if (!wide) return Scaffold(body: SafeArea(child: body));
    return Scaffold(
      body: SafeArea(
        child: Row(
          children: [
            NavigationRail(
              selectedIndex: page.index,
              onDestinationSelected: (i) => _select(AppPage.values[i]),
              labelType: NavigationRailLabelType.all,
              leading: const Padding(padding: EdgeInsets.symmetric(vertical: 16), child: NexonicLogo(size: 36)),
              destinations: [
                for (final p in AppPage.values) NavigationRailDestination(icon: Icon(p.icon), label: Text(p.label)),
              ],
            ),
            const VerticalDivider(width: 1, color: Colors.white10),
            Expanded(child: body),
          ],
        ),
      ),
    );
  }

  Widget _header(bool wide) {
    final s = page.section;
    final when = s == null ? null : catalog.updated[s];
    final busy = s != null && catalog.busy.contains(s);
    final count = _source.length;
    return Padding(
      padding: EdgeInsets.fromLTRB(16, wide ? 16 : 8, 16, 8),
      child: Row(
        children: [
          if (!wide) ...[const NexonicLogo(), const SizedBox(width: 8)],
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(wide ? page.label : 'Nexonic IPTV', style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700)),
              Text(
                [
                  '$count ${page == AppPage.radio ? 'stations' : 'items'}',
                  if (when != null) 'updated ${_ago(when)}',
                  if (catalog.error != null) 'offline copy',
                ].join(' · '),
                style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.white54),
              ),
            ],
          ),
          const SizedBox(width: 16),
          Expanded(
            child: TextField(
              decoration: const InputDecoration(prefixIcon: Icon(Icons.search_rounded), hintText: 'Search channels'),
              onChanged: (v) => setState(() => query = v),
            ),
          ),
          const SizedBox(width: 8),
          busy
              ? const Padding(padding: EdgeInsets.all(12), child: SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)))
              : IconButton(
                  tooltip: 'Refresh the channel list',
                  icon: const Icon(Icons.refresh_rounded),
                  onPressed: () => catalog.refresh(sections: s == null ? null : [s]),
                ),
        ],
      ),
    );
  }

  Widget _sectionChips() => SizedBox(
        height: 44,
        child: ListView(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.symmetric(horizontal: 12),
          children: [
            for (final p in AppPage.values)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4),
                child: ChoiceChip(
                  avatar: Icon(p.icon, size: 16),
                  label: Text(p.label),
                  selected: p == page,
                  onSelected: (_) => _select(p),
                ),
              ),
          ],
        ),
      );

  Widget _filters() {
    final src = _source;
    final chips = <Widget>[];
    if (page == AppPage.live || page == AppPage.radio) {
      final names = {for (final e in catalog.entries('country')) e.key.toUpperCase(): e.name};
      final codes = {for (final c in src) if (c.country.isNotEmpty) c.country}.toList()
        ..sort((a, b) => (names[a] ?? a).compareTo(names[b] ?? b));
      chips.add(FilterMenu(
        label: 'Country',
        value: country,
        options: [for (final c in codes) (c, names[c] ?? c)],
        onChanged: (v) => setState(() => country = v),
      ));
    }
    if (page == AppPage.live) {
      final langs = {for (final c in src) ...c.language.split(';').where((l) => l.isNotEmpty)}.toList()..sort();
      chips.add(FilterMenu(
        label: 'Language',
        value: language,
        options: [for (final l in langs) (l, l)],
        onChanged: (v) => setState(() => language = v),
      ));
      final cats = catalog.entries('category');
      if (cats.isNotEmpty) {
        chips.add(FilterMenu(
          label: 'Category',
          value: category?.path ?? '',
          options: [for (final e in cats) (e.path, e.name)],
          onChanged: _pickCategory,
        ));
      }
    } else if (page.section != null && page != AppPage.radio) {
      final groups = {for (final c in src) if (c.group.isNotEmpty) c.group}.toList()..sort();
      if (groups.length > 1 && groups.length < 400) {
        chips.add(FilterMenu(
          label: 'Genre',
          value: group,
          options: [for (final g in groups) (g, g)],
          onChanged: (v) => setState(() => group = v),
        ));
      }
    }
    if (chips.isEmpty) return const SizedBox(height: 4);
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
      child: Wrap(spacing: 8, runSpacing: 8, children: chips),
    );
  }

  Widget _grid(List<Channel> items, bool wide) {
    final s = page.section;
    if (items.isEmpty) {
      final loading = s != null && catalog.busy.contains(s);
      return Center(
        child: loading
            ? const CircularProgressIndicator()
            : Text(
                page == AppPage.favorites
                    ? 'Tap the star on a channel to keep it here.'
                    : page == AppPage.recent
                        ? 'Channels you watch appear here.'
                        : catalog.error ?? 'Nothing matches.',
                style: const TextStyle(color: Colors.white54),
              ),
      );
    }
    return GridView.builder(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
      gridDelegate: SliverGridDelegateWithMaxCrossAxisExtent(
        maxCrossAxisExtent: wide ? 220 : 180,
        mainAxisExtent: 150,
        crossAxisSpacing: 12,
        mainAxisSpacing: 12,
      ),
      itemCount: items.length,
      itemBuilder: (_, i) {
        final c = items[i];
        final removed = s == null && catalog.isRemoved(c);
        return ChannelCard(
          channel: c,
          favorite: catalog.isFavorite(c),
          warning: removed || catalog.failing.contains(c.url),
          subtitle: removed ? 'No longer in the catalogue' : null,
          onTap: () => _open(items, i),
          onFavorite: () => catalog.toggleFavorite(c),
        );
      },
    );
  }

  static String _ago(DateTime t) {
    final d = DateTime.now().difference(t);
    if (d.inMinutes < 1) return 'just now';
    if (d.inHours < 1) return '${d.inMinutes} min ago';
    if (d.inDays < 1) return '${d.inHours} h ago';
    return '${d.inDays} d ago';
  }
}
