import 'package:flutter/material.dart';

import '../catalog.dart';
import '../m3u.dart';
import 'details.dart';
import 'player.dart';
import 'theme.dart';
import 'widgets.dart';

/// Films, series, radio and open media: category chips, search, sorting and a poster (or station) grid.
class BrowsePage extends StatefulWidget {
  const BrowsePage({super.key, required this.catalog, required this.kind, required this.title, this.initialGroup});
  final Catalog catalog;
  final String kind;
  final String title;
  final String? initialGroup;

  @override
  State<BrowsePage> createState() => _BrowsePageState();
}

class _BrowsePageState extends State<BrowsePage> {
  late String group = widget.initialGroup ?? '';
  String query = '';
  String country = '';
  String sort = 'default';

  Catalog get catalog => widget.catalog;

  List<Channel> _sorted(List<Channel> items) {
    if (sort == 'name') return [...items]..sort((a, b) => a.name.toLowerCase().compareTo(b.name.toLowerCase()));
    if (sort == 'year') return [...items]..sort((a, b) => b.year.compareTo(a.year));
    if (sort == 'rating') return [...items]..sort((a, b) => (double.tryParse(b.rating) ?? 0).compareTo(double.tryParse(a.rating) ?? 0));
    return items;
  }

  @override
  Widget build(BuildContext context) {
    final w = MediaQuery.sizeOf(context).width;
    final narrow = w < 600;
    final pad = narrow ? 16.0 : 24.0;
    final all = catalog.items(widget.kind);
    final radio = widget.kind == 'radio';
    final items = _sorted(filterChannels(all, query: query, group: group, country: country));
    final groups = groupCounts(all);
    final countries = radio
        ? ({for (final c in all) if (c.country.isNotEmpty) c.country}.toList()..sort((a, b) => (catalog.countryNames[a] ?? a).compareTo(catalog.countryNames[b] ?? b)))
        : const <String>[];
    final search = SizedBox(width: narrow ? double.infinity : 300, child: SearchField(hint: 'Search ${widget.title.toLowerCase()}', onChanged: (v) => setState(() => query = v)));
    final sortMenu = radio
        ? null
        : PopupMenuButton<String>(
            tooltip: 'Sort',
            initialValue: sort,
            onSelected: (v) => setState(() => sort = v),
            itemBuilder: (_) => const [
              PopupMenuItem(value: 'default', child: Text('Playlist order')),
              PopupMenuItem(value: 'name', child: Text('Name A–Z')),
              PopupMenuItem(value: 'year', child: Text('Newest first')),
              PopupMenuItem(value: 'rating', child: Text('Top rated')),
            ],
            icon: const Icon(Icons.sort_rounded),
          );
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      PageHeader(
        title: widget.title,
        padding: pad,
        subtitle: '${compact(all.length)} ${radio ? 'stations' : 'titles'}',
        actions: [
          if (!narrow) search,
          if (countries.length > 1) ...[
            const SizedBox(width: 8),
            FilterMenu(
              label: 'Country',
              icon: Icons.public_rounded,
              value: country,
              options: [for (final c in countries) (c, catalog.countryNames[c] ?? c)],
              onChanged: (v) => setState(() => country = v),
            ),
          ],
          if (sortMenu != null) ...[const SizedBox(width: 4), sortMenu],
        ],
      ),
      if (narrow) Padding(padding: EdgeInsets.fromLTRB(pad, 0, pad, 10), child: search),
      if (groups.length > 1 && groups.length <= 400)
        Padding(
          padding: const EdgeInsets.only(bottom: 14),
          child: ChipBar(
            padding: pad,
            items: [('', 'All'), for (final (g, _) in groups) (g, g)],
            selected: group,
            onSelected: (v) => setState(() => group = v),
          ),
        ),
      Expanded(
        child: all.isEmpty
            ? (catalog.isBusy
                ? const Center(child: CircularProgressIndicator())
                : EmptyState(icon: Icons.video_library_outlined, title: 'Nothing here yet', message: 'Playlists with ${widget.title.toLowerCase()} will show them here.'))
            : items.isEmpty
                ? const EmptyState(icon: Icons.search_off_rounded, title: 'Nothing matches', message: 'Try another search or category.')
                : GridView.builder(
                    padding: EdgeInsets.fromLTRB(pad, 4, pad, 32),
                    gridDelegate: radio
                        ? SliverGridDelegateWithMaxCrossAxisExtent(maxCrossAxisExtent: narrow ? 180 : 210, mainAxisExtent: narrow ? 150 : 172, crossAxisSpacing: 14, mainAxisSpacing: 14)
                        : SliverGridDelegateWithMaxCrossAxisExtent(
                            maxCrossAxisExtent: narrow ? 130 : 168,
                            childAspectRatio: 0.54,
                            crossAxisSpacing: narrow ? 12 : 18,
                            mainAxisSpacing: 20,
                          ),
                    itemCount: items.length,
                    itemBuilder: (_, i) {
                      final c = items[i];
                      if (radio) {
                        return ChannelCard(
                          channel: c,
                          favorite: catalog.isFavorite(c),
                          failing: catalog.failing.contains(c.key),
                          onFavorite: () => catalog.toggleFavorite(c),
                          onTap: () => openPlayer(context, catalog, items, i),
                        );
                      }
                      return PosterCard(
                        item: c,
                        favorite: catalog.isFavorite(c),
                        progress: catalog.resume[c.key]?.fraction,
                        onFavorite: () => catalog.toggleFavorite(c),
                        onTap: () => openItem(context, catalog, items, i),
                      );
                    },
                  ),
      ),
    ]);
  }
}

/// My list: favourites and recently watched.
class FavoritesPage extends StatefulWidget {
  const FavoritesPage({super.key, required this.catalog});
  final Catalog catalog;

  @override
  State<FavoritesPage> createState() => _FavoritesPageState();
}

class _FavoritesPageState extends State<FavoritesPage> {
  String tab = 'fav';

  @override
  Widget build(BuildContext context) {
    final narrow = MediaQuery.sizeOf(context).width < 600;
    final pad = narrow ? 16.0 : 24.0;
    final catalog = widget.catalog;
    final list = tab == 'fav' ? catalog.favoriteList : catalog.recents;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      PageHeader(
        title: 'My list',
        padding: pad,
        actions: [
          if (tab == 'recent' && list.isNotEmpty) TextButton(onPressed: catalog.clearHistory, child: const Text('Clear history')),
        ],
      ),
      Padding(
        padding: EdgeInsets.fromLTRB(pad, 0, pad, 16),
        child: Align(
          alignment: Alignment.centerLeft,
          child: SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'fav', icon: Icon(Icons.star_rounded), label: Text('Favourites')),
              ButtonSegment(value: 'recent', icon: Icon(Icons.history_rounded), label: Text('Recently watched')),
            ],
            selected: {tab},
            onSelectionChanged: (s) => setState(() => tab = s.first),
          ),
        ),
      ),
      Expanded(
        child: list.isEmpty
            ? EmptyState(
                icon: tab == 'fav' ? Icons.star_outline_rounded : Icons.history_rounded,
                title: tab == 'fav' ? 'No favourites yet' : 'Nothing watched yet',
                message: tab == 'fav' ? 'Press the star on any channel, film or station (or right-click it) to keep it here.' : 'What you watch shows up here.',
              )
            : GridView.builder(
                padding: EdgeInsets.fromLTRB(pad, 0, pad, 32),
                gridDelegate: SliverGridDelegateWithMaxCrossAxisExtent(maxCrossAxisExtent: narrow ? 180 : 220, mainAxisExtent: narrow ? 160 : 186, crossAxisSpacing: 14, mainAxisSpacing: 14),
                itemCount: list.length,
                itemBuilder: (_, i) {
                  final c = list[i];
                  final removed = catalog.isRemoved(c);
                  return ChannelCard(
                    channel: c,
                    now: c.isLive ? catalog.nowNext(c).$1 : null,
                    progress: catalog.resume[c.key]?.fraction,
                    favorite: catalog.isFavorite(c),
                    failing: removed || catalog.failing.contains(c.key),
                    subtitle: removed ? 'No longer in its playlist' : null,
                    onFavorite: () => catalog.toggleFavorite(c),
                    onTap: () => c.isLive ? openPlayer(context, catalog, list, i) : openItem(context, catalog, list, i),
                  );
                },
              ),
      ),
    ]);
  }
}
