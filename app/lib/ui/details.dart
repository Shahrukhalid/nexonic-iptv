import 'package:flutter/material.dart';

import '../catalog.dart';
import '../m3u.dart';
import '../xtream.dart';
import 'player.dart';
import 'theme.dart';
import 'widgets.dart';

/// Opens an item the right way: series show their episodes, films show details first, channels play at once.
Future<void> openItem(BuildContext context, Catalog catalog, List<Channel> list, int index) {
  final c = list[index];
  if (c.opensSeries) {
    return Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => SeriesPage(catalog: catalog, series: c)));
  }
  if (c.isVod) return showDetails(context, catalog, list, index);
  return openPlayer(context, catalog, list, index);
}

Future<void> showDetails(BuildContext context, Catalog catalog, List<Channel> list, int index) => showDialog<void>(
      context: context,
      builder: (_) => _DetailsDialog(catalog: catalog, list: list, index: index),
    );

class _DetailsDialog extends StatelessWidget {
  const _DetailsDialog({required this.catalog, required this.list, required this.index});
  final Catalog catalog;
  final List<Channel> list;
  final int index;

  @override
  Widget build(BuildContext context) {
    final c = list[index];
    final r = catalog.resume[c.key];
    final narrow = MediaQuery.sizeOf(context).width < 640;
    final poster = SizedBox(
      width: narrow ? 120 : 200,
      child: AspectRatio(aspectRatio: 2 / 3, child: Artwork(url: c.logo, name: c.name, fit: BoxFit.cover, radius: radiusM)),
    );
    void play({bool fromStart = false}) {
      if (fromStart) catalog.setProgress(c, Duration.zero, Duration.zero);
      Navigator.of(context).pop();
      openPlayer(context, catalog, list, index);
    }

    final info = Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
      Text(c.name, style: Theme.of(context).textTheme.headlineSmall),
      const SizedBox(height: 8),
      Wrap(spacing: 8, runSpacing: 6, children: [
        if (c.year.isNotEmpty) Pill(c.year),
        if (c.rating.isNotEmpty && c.rating != '0') Pill(c.rating, icon: Icons.star_rounded, foreground: gold),
        if (c.group.isNotEmpty) Pill(c.group),
        Pill(switch (c.kind) { 'media' => 'Open media', 'episode' => 'Episode', 'series' => 'Episode', _ => 'Film' }),
      ]),
      if (c.plot.isNotEmpty) ...[
        const SizedBox(height: 14),
        Text(c.plot, maxLines: 8, overflow: TextOverflow.ellipsis, style: Theme.of(context).textTheme.bodyLarge?.copyWith(color: textSecondary)),
      ],
      if (r != null) ...[
        const SizedBox(height: 16),
        Row(children: [
          Expanded(child: ProgressLine(r.fraction, height: 4)),
          const SizedBox(width: 10),
          Text('${duration(r.duration - r.position)} left', style: Theme.of(context).textTheme.bodySmall),
        ]),
      ],
      const SizedBox(height: 20),
      Wrap(spacing: 10, runSpacing: 10, children: [
        FilledButton.icon(
          autofocus: true,
          icon: const Icon(Icons.play_arrow_rounded),
          label: Text(r != null ? 'Resume' : 'Play'),
          onPressed: play,
        ),
        if (r != null) OutlinedButton.icon(icon: const Icon(Icons.replay_rounded), label: const Text('Start over'), onPressed: () => play(fromStart: true)),
        _FavoriteButton(catalog: catalog, item: c),
      ]),
    ]);
    return Dialog(
      insetPadding: const EdgeInsets.all(24),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 720),
        child: Stack(children: [
          Padding(
            padding: const EdgeInsets.all(24),
            child: narrow
                ? SingleChildScrollView(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [poster, const SizedBox(height: 16), info]))
                : Row(crossAxisAlignment: CrossAxisAlignment.start, children: [poster, const SizedBox(width: 24), Expanded(child: info)]),
          ),
          Positioned(right: 8, top: 8, child: IconButton(icon: const Icon(Icons.close_rounded), onPressed: () => Navigator.of(context).pop())),
        ]),
      ),
    );
  }
}

class _FavoriteButton extends StatefulWidget {
  const _FavoriteButton({required this.catalog, required this.item});
  final Catalog catalog;
  final Channel item;

  @override
  State<_FavoriteButton> createState() => _FavoriteButtonState();
}

class _FavoriteButtonState extends State<_FavoriteButton> {
  @override
  Widget build(BuildContext context) {
    final on = widget.catalog.isFavorite(widget.item);
    return OutlinedButton.icon(
      icon: Icon(on ? Icons.star_rounded : Icons.star_outline_rounded, color: on ? gold : null),
      label: Text(on ? 'In favourites' : 'Favourite'),
      onPressed: () => setState(() => widget.catalog.toggleFavorite(widget.item)),
    );
  }
}

/// Seasons and episodes of an Xtream series.
class SeriesPage extends StatefulWidget {
  const SeriesPage({super.key, required this.catalog, required this.series});
  final Catalog catalog;
  final Channel series;

  @override
  State<SeriesPage> createState() => _SeriesPageState();
}

class _SeriesPageState extends State<SeriesPage> {
  late Future<List<Episode>> episodes = widget.catalog.episodes(widget.series);
  int? season;

  @override
  Widget build(BuildContext context) {
    final c = widget.series;
    final narrow = MediaQuery.sizeOf(context).width < 700;
    return Scaffold(
      body: Backdrop(
        child: SafeArea(
          child: FutureBuilder<List<Episode>>(
            future: episodes,
            builder: (context, snap) {
              final list = snap.data ?? const <Episode>[];
              final seasons = {for (final e in list) e.season}.toList()..sort();
              final current = season ?? (seasons.isEmpty ? null : seasons.first);
              final shown = [for (final e in list) if (e.season == current) e];
              final playable = [for (final e in shown) e.channel];
              return CustomScrollView(slivers: [
                SliverToBoxAdapter(
                  child: Padding(
                    padding: EdgeInsets.fromLTRB(narrow ? 12 : 24, 12, narrow ? 12 : 24, 8),
                    child: Row(children: [IconButton(icon: const Icon(Icons.arrow_back_rounded), onPressed: () => Navigator.of(context).pop())]),
                  ),
                ),
                SliverToBoxAdapter(
                  child: Padding(
                    padding: EdgeInsets.symmetric(horizontal: narrow ? 16 : 32),
                    child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      SizedBox(width: narrow ? 110 : 180, child: AspectRatio(aspectRatio: 2 / 3, child: Artwork(url: c.logo, name: c.name, fit: BoxFit.cover, radius: radiusM))),
                      const SizedBox(width: 24),
                      Expanded(
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Text(c.name, style: narrow ? Theme.of(context).textTheme.headlineSmall : Theme.of(context).textTheme.displaySmall),
                          const SizedBox(height: 10),
                          Wrap(spacing: 8, runSpacing: 6, children: [
                            if (c.year.isNotEmpty) Pill(c.year),
                            if (c.rating.isNotEmpty && c.rating != '0') Pill(c.rating, icon: Icons.star_rounded, foreground: gold),
                            if (c.group.isNotEmpty) Pill(c.group),
                            if (seasons.isNotEmpty) Pill('${seasons.length} season${seasons.length == 1 ? '' : 's'}'),
                          ]),
                          if (c.plot.isNotEmpty) ...[
                            const SizedBox(height: 14),
                            Text(c.plot, maxLines: 6, overflow: TextOverflow.ellipsis, style: Theme.of(context).textTheme.bodyLarge?.copyWith(color: textSecondary)),
                          ],
                          const SizedBox(height: 16),
                          Wrap(spacing: 10, children: [
                            if (playable.isNotEmpty)
                              FilledButton.icon(
                                icon: const Icon(Icons.play_arrow_rounded),
                                label: const Text('Play first episode'),
                                onPressed: () => openPlayer(context, widget.catalog, playable, 0),
                              ),
                            _FavoriteButton(catalog: widget.catalog, item: c),
                          ]),
                        ]),
                      ),
                    ]),
                  ),
                ),
                const SliverToBoxAdapter(child: SizedBox(height: 24)),
                if (snap.connectionState != ConnectionState.done)
                  const SliverFillRemaining(hasScrollBody: false, child: Center(child: CircularProgressIndicator()))
                else if (snap.hasError || list.isEmpty)
                  SliverFillRemaining(
                    hasScrollBody: false,
                    child: EmptyState(
                      icon: Icons.video_library_outlined,
                      title: 'No episodes found',
                      message: snap.hasError ? '${snap.error}' : 'The provider did not list episodes for this series.',
                      action: OutlinedButton(onPressed: () => setState(() => episodes = widget.catalog.episodes(c)), child: const Text('Try again')),
                    ),
                  )
                else ...[
                  SliverToBoxAdapter(
                    child: ChipBar(
                      padding: narrow ? 16 : 32,
                      items: [for (final s in seasons) ('$s', 'Season $s')],
                      selected: '$current',
                      onSelected: (v) => setState(() => season = int.tryParse(v)),
                    ),
                  ),
                  const SliverToBoxAdapter(child: SizedBox(height: 12)),
                  SliverPadding(
                    padding: EdgeInsets.symmetric(horizontal: narrow ? 16 : 32),
                    sliver: SliverList.separated(
                      itemCount: shown.length,
                      separatorBuilder: (_, __) => const SizedBox(height: 10),
                      itemBuilder: (_, i) {
                        final e = shown[i];
                        final r = widget.catalog.resume[e.channel.key];
                        return Tappable(
                          scale: 1.01,
                          onTap: () => openPlayer(context, widget.catalog, playable, i),
                          child: Container(
                            padding: const EdgeInsets.all(10),
                            decoration: BoxDecoration(color: surface, borderRadius: BorderRadius.circular(radiusM), border: Border.all(color: stroke)),
                            child: Row(children: [
                              SizedBox(
                                width: narrow ? 110 : 170,
                                child: AspectRatio(
                                  aspectRatio: 16 / 9,
                                  child: Stack(fit: StackFit.expand, children: [
                                    Artwork(url: e.channel.logo, name: e.channel.name, fit: BoxFit.cover),
                                    const Center(child: Icon(Icons.play_circle_fill_rounded, size: 36, color: Colors.white70)),
                                    if (r != null) Positioned(left: 6, right: 6, bottom: 6, child: ProgressLine(r.fraction)),
                                  ]),
                                ),
                              ),
                              const SizedBox(width: 14),
                              Expanded(
                                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                                  Text('${e.number > 0 ? '${e.number}. ' : ''}${e.channel.name}',
                                      maxLines: 1, overflow: TextOverflow.ellipsis, style: Theme.of(context).textTheme.titleMedium),
                                  if (e.duration.isNotEmpty) Text(e.duration, style: Theme.of(context).textTheme.bodySmall),
                                  if (e.plot.isNotEmpty) ...[
                                    const SizedBox(height: 4),
                                    Text(e.plot, maxLines: 2, overflow: TextOverflow.ellipsis, style: Theme.of(context).textTheme.bodyMedium),
                                  ],
                                ]),
                              ),
                            ]),
                          ),
                        );
                      },
                    ),
                  ),
                  const SliverToBoxAdapter(child: SizedBox(height: 32)),
                ],
              ]);
            },
          ),
        ),
      ),
    );
  }
}
