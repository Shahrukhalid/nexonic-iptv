import 'package:flutter/material.dart';

import '../catalog.dart';
import '../m3u.dart';
import 'details.dart';
import 'player.dart';
import 'widgets.dart';

/// One search across live TV, films, series, radio and open media.
class SearchPage extends StatefulWidget {
  const SearchPage({super.key, required this.catalog});
  final Catalog catalog;

  @override
  State<SearchPage> createState() => _SearchPageState();
}

class _SearchPageState extends State<SearchPage> {
  String query = '';

  static const _titles = {'live': 'Live TV', 'movie': 'Films', 'series': 'Series', 'radio': 'Radio', 'media': 'Open media'};

  @override
  Widget build(BuildContext context) {
    final narrow = MediaQuery.sizeOf(context).width < 600;
    final pad = narrow ? 16.0 : 32.0;
    final catalog = widget.catalog;
    final q = query.trim();
    final results = <(String, List<Channel>)>[
      if (q.length >= 2)
        for (final k in kinds)
          if (filterChannels(catalog.items(k), query: q) case final hits when hits.isNotEmpty) (k, hits),
    ];
    final total = results.fold<int>(0, (a, r) => a + r.$2.length);
    return ListView(padding: const EdgeInsets.only(bottom: 32), children: [
      Padding(
        padding: EdgeInsets.fromLTRB(pad, narrow ? 12 : 28, pad, 8),
        child: Text('Search', style: narrow ? Theme.of(context).textTheme.headlineSmall : Theme.of(context).textTheme.headlineMedium),
      ),
      Padding(
        padding: EdgeInsets.fromLTRB(pad, 8, pad, 24),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 640),
          child: SearchField(autofocus: !narrow, hint: 'Channels, films, series, stations…', onChanged: (v) => setState(() => query = v)),
        ),
      ),
      if (q.length < 2)
        const SizedBox(height: 360, child: EmptyState(icon: Icons.manage_search_rounded, title: 'Find anything', message: 'Type at least two letters to search every playlist.'))
      else if (results.isEmpty)
        const SizedBox(height: 360, child: EmptyState(icon: Icons.search_off_rounded, title: 'No results', message: 'Check the spelling or try a shorter word.'))
      else ...[
        Padding(padding: EdgeInsets.fromLTRB(pad, 0, pad, 16), child: Text('$total results', style: Theme.of(context).textTheme.bodyMedium)),
        for (final (kind, hits) in results) ...[
          kind == 'movie' || kind == 'series' || kind == 'media'
              ? ContentRow(
                  title: _titles[kind]!,
                  count: hits.length,
                  padding: pad,
                  itemCount: hits.length.clamp(0, 60),
                  itemWidth: narrow ? 120 : 150,
                  height: narrow ? 220 : 268,
                  itemBuilder: (_, i) => PosterCard(
                    item: hits[i],
                    favorite: catalog.isFavorite(hits[i]),
                    onFavorite: () => catalog.toggleFavorite(hits[i]),
                    onTap: () => openItem(context, catalog, hits, i),
                  ),
                )
              : ContentRow(
                  title: _titles[kind]!,
                  count: hits.length,
                  padding: pad,
                  itemCount: hits.length.clamp(0, 60),
                  itemWidth: narrow ? 170 : 210,
                  height: narrow ? 160 : 180,
                  itemBuilder: (_, i) => ChannelCard(
                    channel: hits[i],
                    now: catalog.nowNext(hits[i]).$1,
                    favorite: catalog.isFavorite(hits[i]),
                    onFavorite: () => catalog.toggleFavorite(hits[i]),
                    onTap: () => openPlayer(context, catalog, hits, i),
                  ),
                ),
          const SizedBox(height: 28),
        ],
      ],
    ]);
  }
}
