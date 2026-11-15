import 'package:flutter/material.dart';

import '../catalog.dart';
import 'browse_page.dart';
import 'guide_page.dart';
import 'home_page.dart';
import 'live_page.dart';
import 'search_page.dart';
import 'settings_page.dart';
import 'sources_page.dart';
import 'theme.dart';
import 'widgets.dart';

enum Nav {
  home('Home', Icons.home_rounded, Icons.home_outlined),
  live('Live TV', Icons.live_tv_rounded, Icons.live_tv_outlined),
  guide('TV guide', Icons.calendar_view_week_rounded, Icons.calendar_view_week_outlined),
  movies('Films', Icons.movie_rounded, Icons.movie_outlined),
  series('Series', Icons.video_library_rounded, Icons.video_library_outlined),
  radio('Radio', Icons.radio_rounded, Icons.radio_outlined),
  media('Open media', Icons.public_rounded, Icons.public_outlined),
  favorites('My list', Icons.star_rounded, Icons.star_outline_rounded),
  search('Search', Icons.search_rounded, Icons.search_rounded),
  sources('Playlists', Icons.playlist_play_rounded, Icons.playlist_play_outlined),
  settings('Settings', Icons.settings_rounded, Icons.settings_outlined),
  more('More', Icons.menu_rounded, Icons.menu_rounded);

  const Nav(this.label, this.icon, this.outline);
  final String label;
  final IconData icon;
  final IconData outline;

  String? get kind => switch (this) {
        Nav.live => 'live',
        Nav.movies => 'movie',
        Nav.series => 'series',
        Nav.radio => 'radio',
        Nav.media => 'media',
        _ => null,
      };
}

typedef Navigate = void Function(Nav page, {String? group});

class AppShell extends StatefulWidget {
  const AppShell({super.key, required this.catalog, this.initialPage});
  final Catalog catalog;

  /// Opens on this page instead of the start page from the settings (tests and screenshots).
  final Nav? initialPage;

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  late Nav page = widget.initialPage ?? (widget.catalog.settings.startPage == 'live' ? Nav.live : Nav.home);
  String? group;
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
    if (!mounted) return;
    final change = catalog.lastChange;
    if (change != null && change != _shownChange) {
      _shownChange = change;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Updated · $change')));
    }
    setState(() {});
  }

  void go(Nav p, {String? group}) => setState(() {
        page = p;
        this.group = group;
      });

  /// Sections shown in navigation: empty film, series, radio and open media sections are hidden.
  List<Nav> get _sections => [
        Nav.home,
        Nav.live,
        Nav.guide,
        for (final n in [Nav.movies, Nav.series, Nav.radio, Nav.media])
          if (catalog.count(n.kind!) > 0) n,
      ];

  Widget _page() => switch (page) {
        Nav.home => HomePage(catalog: catalog, nav: go),
        Nav.live => LivePage(key: ValueKey('live-$group-${catalog.activeSource}'), catalog: catalog, nav: go, initialGroup: group),
        Nav.guide => GuidePage(catalog: catalog, nav: go),
        Nav.movies || Nav.series || Nav.radio || Nav.media =>
          BrowsePage(key: ValueKey('${page.name}-${catalog.activeSource}'), catalog: catalog, kind: page.kind!, title: page.label, initialGroup: group),
        Nav.favorites => FavoritesPage(catalog: catalog),
        Nav.search => SearchPage(catalog: catalog),
        Nav.sources => SourcesPage(catalog: catalog),
        Nav.settings => SettingsPage(catalog: catalog),
        Nav.more => _MorePage(items: [for (final n in Nav.values) if (!_bottom.contains(n) && n != Nav.more && (_sections.contains(n) || n.index >= Nav.favorites.index)) n], nav: go),
      };

  List<Nav> get _bottom {
    final s = _sections.where((n) => n != Nav.guide).toList();
    return [...s.take(4), Nav.more];
  }

  @override
  Widget build(BuildContext context) {
    final w = MediaQuery.sizeOf(context).width;
    final body = AnimatedSwitcher(
      duration: const Duration(milliseconds: 180),
      child: KeyedSubtree(key: ValueKey('${page.name}-$group'), child: _page()),
    );
    if (w < 900) {
      final bottom = _bottom;
      final selected = bottom.contains(page) ? bottom.indexOf(page) : bottom.length - 1;
      return Scaffold(
        body: Backdrop(child: SafeArea(bottom: false, child: body)),
        bottomNavigationBar: NavigationBar(
          selectedIndex: selected,
          onDestinationSelected: (i) => go(bottom[i]),
          destinations: [
            for (final n in bottom) NavigationDestination(icon: Icon(n.outline), selectedIcon: Icon(n.icon), label: n == Nav.movies ? 'Films' : n.label),
          ],
        ),
      );
    }
    return Scaffold(
      body: Backdrop(
        child: Row(children: [
          _Sidebar(catalog: catalog, page: page, sections: _sections, compact: w < 1200, onSelect: go),
          const VerticalDivider(width: 1),
          Expanded(child: SafeArea(left: false, child: body)),
        ]),
      ),
    );
  }
}

class _Sidebar extends StatelessWidget {
  const _Sidebar({required this.catalog, required this.page, required this.sections, required this.compact, required this.onSelect});
  final Catalog catalog;
  final Nav page;
  final List<Nav> sections;
  final bool compact;
  final Navigate onSelect;

  @override
  Widget build(BuildContext context) {
    Widget item(Nav n, {int? count, Widget? trailing}) => _NavItem(
          nav: n,
          selected: page == n,
          compact: compact,
          count: count,
          trailing: trailing,
          onTap: () => onSelect(n),
        );
    final enabled = catalog.sources.where((s) => s.enabled).toList();
    return Container(
      width: compact ? 84 : 248,
      color: background2.withValues(alpha: 0.7),
      child: SafeArea(
        right: false,
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Padding(
            padding: EdgeInsets.fromLTRB(compact ? 0 : 20, 22, compact ? 0 : 16, 22),
            child: compact ? const Center(child: NexonicLogo(size: 36)) : const NexonicWordmark(size: 34),
          ),
          Expanded(
            child: ListView(padding: EdgeInsets.symmetric(horizontal: compact ? 10 : 12), children: [
              for (final n in sections) item(n, count: n.kind == null || n == Nav.live && compact ? null : catalog.count(n.kind!)),
              const SizedBox(height: 14),
              if (!compact) const _Label('LIBRARY'),
              item(Nav.favorites, count: compact || catalog.favorites.isEmpty ? null : catalog.favorites.length),
              item(Nav.search),
            ]),
          ),
          if (!compact && enabled.length > 1)
            Padding(padding: const EdgeInsets.fromLTRB(12, 0, 12, 8), child: _SourceSwitcher(catalog: catalog)),
          Padding(
            padding: EdgeInsets.symmetric(horizontal: compact ? 10 : 12),
            child: Column(children: [
              item(
                Nav.sources,
                trailing: catalog.isBusy ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)) : null,
              ),
              item(Nav.settings),
            ]),
          ),
          const SizedBox(height: 14),
        ]),
      ),
    );
  }
}

class _Label extends StatelessWidget {
  const _Label(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(12, 4, 12, 8),
        child: Text(text, style: Theme.of(context).textTheme.labelSmall?.copyWith(color: textMuted)),
      );
}

class _NavItem extends StatefulWidget {
  const _NavItem({required this.nav, required this.selected, required this.compact, required this.onTap, this.count, this.trailing});
  final Nav nav;
  final bool selected;
  final bool compact;
  final VoidCallback onTap;
  final int? count;
  final Widget? trailing;

  @override
  State<_NavItem> createState() => _NavItemState();
}

class _NavItemState extends State<_NavItem> {
  bool hover = false;

  @override
  Widget build(BuildContext context) {
    final sel = widget.selected;
    final fg = sel ? textPrimary : (hover ? textPrimary : textSecondary);
    final content = widget.compact
        ? Column(mainAxisSize: MainAxisSize.min, children: [
            Icon(sel ? widget.nav.icon : widget.nav.outline, color: sel ? accent : fg, size: 24),
            const SizedBox(height: 4),
            Text(widget.nav.label, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w600, color: fg)),
          ])
        : Row(children: [
            Icon(sel ? widget.nav.icon : widget.nav.outline, color: sel ? accent : fg, size: 22),
            const SizedBox(width: 14),
            Expanded(child: Text(widget.nav.label, style: TextStyle(fontSize: 14, fontWeight: sel ? FontWeight.w700 : FontWeight.w500, color: fg))),
            if (widget.trailing != null) widget.trailing!,
            if (widget.count != null && widget.count! > 0)
              Text(compact(widget.count!), style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: sel ? accent : textMuted)),
          ]);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Tooltip(
        message: widget.compact ? widget.nav.label : '',
        child: MouseRegion(
          onEnter: (_) => setState(() => hover = true),
          onExit: (_) => setState(() => hover = false),
          child: Material(
            color: sel ? accent.withValues(alpha: 0.12) : (hover ? Colors.white.withValues(alpha: 0.04) : Colors.transparent),
            borderRadius: BorderRadius.circular(radiusS),
            child: InkWell(
              borderRadius: BorderRadius.circular(radiusS),
              onTap: widget.onTap,
              child: Container(
                padding: EdgeInsets.symmetric(horizontal: widget.compact ? 4 : 12, vertical: widget.compact ? 10 : 11),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(radiusS),
                  border: Border(left: BorderSide(color: sel && !widget.compact ? accent : Colors.transparent, width: 3)),
                ),
                child: content,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _SourceSwitcher extends StatelessWidget {
  const _SourceSwitcher({required this.catalog});
  final Catalog catalog;

  @override
  Widget build(BuildContext context) {
    final enabled = catalog.sources.where((s) => s.enabled).toList();
    final current = catalog.activeSource == null ? 'All playlists' : (catalog.source(catalog.activeSource!)?.name ?? 'All playlists');
    return PopupMenuButton<String>(
      tooltip: 'Show one playlist',
      onSelected: (v) => catalog.showSource(v.isEmpty ? null : v),
      itemBuilder: (_) => [
        const PopupMenuItem(value: '', child: Text('All playlists')),
        const PopupMenuDivider(),
        for (final s in enabled) PopupMenuItem(value: s.id, child: Text(s.name, maxLines: 1, overflow: TextOverflow.ellipsis)),
      ],
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        decoration: BoxDecoration(color: surfaceHigh, borderRadius: BorderRadius.circular(radiusS), border: Border.all(color: stroke)),
        child: Row(children: [
          const Icon(Icons.layers_outlined, size: 18, color: textSecondary),
          const SizedBox(width: 10),
          Expanded(child: Text(current, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600))),
          const Icon(Icons.unfold_more_rounded, size: 18, color: textSecondary),
        ]),
      ),
    );
  }
}

class _MorePage extends StatelessWidget {
  const _MorePage({required this.items, required this.nav});
  final List<Nav> items;
  final Navigate nav;

  @override
  Widget build(BuildContext context) => ListView(
        padding: const EdgeInsets.only(bottom: 24),
        children: [
          const Padding(padding: EdgeInsets.fromLTRB(16, 16, 16, 12), child: NexonicWordmark(size: 32)),
          for (final n in items)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
              child: Material(
                color: surface,
                borderRadius: BorderRadius.circular(radiusM),
                child: ListTile(
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(radiusM), side: const BorderSide(color: stroke)),
                  leading: Icon(n.icon, color: accent),
                  title: Text(n.label, style: const TextStyle(fontWeight: FontWeight.w600)),
                  trailing: const Icon(Icons.chevron_right_rounded),
                  onTap: () => nav(n),
                ),
              ),
            ),
        ],
      );
}
