import 'package:flutter/material.dart';

import '../catalog.dart';
import '../m3u.dart';
import 'details.dart';
import 'player.dart';
import 'shell.dart';
import 'theme.dart';
import 'widgets.dart';

/// Discover: a featured channel, then rows for continue watching, favourites, live categories, films and radio.
class HomePage extends StatelessWidget {
  const HomePage({super.key, required this.catalog, required this.nav});
  final Catalog catalog;
  final Navigate nav;

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    final narrow = width < 600;
    final pad = narrow ? 16.0 : 32.0;
    final liveItems = catalog.items('live');
    if (catalog.isEmpty) {
      return catalog.isBusy || !catalog.loaded
          ? const Center(child: CircularProgressIndicator())
          : EmptyState(
              icon: Icons.playlist_add_rounded,
              title: 'No channels yet',
              message: 'Turn on the free Nexonic channels or add your own playlist (M3U link, file or Xtream Codes login).',
              action: FilledButton.icon(icon: const Icon(Icons.add_rounded), label: const Text('Add a playlist'), onPressed: () => nav(Nav.sources)),
            );
    }
    final featured = _featured(liveItems);
    final rows = <Widget>[];
    void add(Widget w) => rows
      ..add(w)
      ..add(const SizedBox(height: 32));

    final recent = catalog.recents.take(20).toList();
    if (recent.isNotEmpty) {
      add(_channelRow(context, 'Continue watching', recent, pad, icon: Icons.history_rounded, onMore: () => nav(Nav.favorites)));
    }
    final favs = catalog.favoriteList;
    if (favs.isNotEmpty) add(_channelRow(context, 'Favourites', favs.take(30).toList(), pad, icon: Icons.star_rounded, onMore: () => nav(Nav.favorites)));
    if (liveItems.isNotEmpty) {
      final g = catalog.guide;
      final t = DateTime.now().toUtc();
      final onNow = g.isEmpty ? const <Channel>[] : [for (final c in liveItems) if (g.nowNext(c.tvgId, t, c.name).$1 != null) c];
      add(_channelRow(context, onNow.isNotEmpty ? 'On now' : 'Live channels', (onNow.isNotEmpty ? onNow : liveItems).take(30).toList(), pad,
          count: liveItems.length, icon: Icons.sensors_rounded, onMore: () => nav(Nav.live)));
      final groups = groupCounts(liveItems).where((g) => g.$1 != 'Other' && g.$2 >= 4).toList()..sort((a, b) => b.$2.compareTo(a.$2));
      for (final (name, count) in groups.take(4)) {
        final list = filterChannels(liveItems, group: name);
        add(_channelRow(context, name, list.take(30).toList(), pad, count: count, onMore: () => nav(Nav.live, group: name)));
      }
    }
    for (final (kind, title, page) in const [('movie', 'Films', Nav.movies), ('series', 'Series', Nav.series), ('media', 'Open media', Nav.media)]) {
      final list = catalog.items(kind);
      if (list.isEmpty) continue;
      add(ContentRow(
        title: title,
        count: list.length,
        padding: pad,
        itemCount: list.length.clamp(0, 30),
        itemWidth: narrow ? 120 : 150,
        height: narrow ? 220 : 268,
        onMore: () => nav(page),
        itemBuilder: (_, i) => PosterCard(
          item: list[i],
          favorite: catalog.isFavorite(list[i]),
          progress: catalog.resume[list[i].key]?.fraction,
          onFavorite: () => catalog.toggleFavorite(list[i]),
          onTap: () => openItem(context, catalog, list, i),
        ),
      ));
    }
    final radio = catalog.items('radio');
    if (radio.isNotEmpty) add(_channelRow(context, 'Radio', radio.take(30).toList(), pad, count: radio.length, icon: Icons.radio_rounded, onMore: () => nav(Nav.radio)));

    return ListView(
      padding: EdgeInsets.only(bottom: 32, top: narrow ? 8 : 20),
      children: [
        if (featured != null) Padding(padding: EdgeInsets.symmetric(horizontal: pad), child: _Hero(catalog: catalog, channel: featured, list: liveItems, nav: nav)),
        SizedBox(height: narrow ? 24 : 36),
        ...rows,
      ],
    );
  }

  Channel? _featured(List<Channel> live) {
    for (final c in catalog.recents) {
      if (c.isLive && !c.isRadio) return c;
    }
    for (final c in catalog.favoriteList) {
      if (c.kind == 'live') return c;
    }
    if (live.isEmpty) return null;
    // A different channel each day, from the top of the list.
    return live[DateTime.now().day % (live.length < 20 ? live.length : 20)];
  }

  Widget _channelRow(BuildContext context, String title, List<Channel> list, double pad, {int? count, IconData? icon, VoidCallback? onMore}) {
    final narrow = MediaQuery.sizeOf(context).width < 600;
    return ContentRow(
      title: title,
      count: count,
      icon: icon,
      padding: pad,
      onMore: onMore,
      itemCount: list.length,
      itemWidth: narrow ? 170 : 220,
      height: narrow ? 160 : 186,
      itemBuilder: (_, i) {
        final c = list[i];
        return ChannelCard(
          channel: c,
          now: c.isLive ? catalog.nowNext(c).$1 : null,
          progress: catalog.resume[c.key]?.fraction,
          favorite: catalog.isFavorite(c),
          failing: catalog.failing.contains(c.key),
          onFavorite: () => catalog.toggleFavorite(c),
          onTap: () => c.isLive ? openPlayer(context, catalog, list, i) : openItem(context, catalog, list, i),
        );
      },
    );
  }
}

class _Hero extends StatelessWidget {
  const _Hero({required this.catalog, required this.channel, required this.list, required this.nav});
  final Catalog catalog;
  final Channel channel;
  final List<Channel> list;
  final Navigate nav;

  @override
  Widget build(BuildContext context) {
    final narrow = MediaQuery.sizeOf(context).width < 700;
    final (now, next) = catalog.nowNext(channel);
    final (a, b) = tintFor(channel.name);
    final resumed = catalog.recents.isNotEmpty && catalog.recents.first.key == channel.key;
    final fav = catalog.isFavorite(channel);
    final t = DateTime.now().toUtc();
    void watch() {
      final i = list.indexWhere((c) => c.key == channel.key);
      if (i >= 0) {
        openPlayer(context, catalog, list, i);
      } else {
        openPlayer(context, catalog, [channel], 0);
      }
    }

    return Container(
      height: narrow ? 300 : 340,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(radiusL + 4),
        border: Border.all(color: stroke),
        gradient: LinearGradient(
          colors: [a.withValues(alpha: 0.38), b.withValues(alpha: 0.18), surface],
          stops: const [0, 0.45, 1],
          begin: Alignment.topRight,
          end: Alignment.bottomLeft,
        ),
      ),
      clipBehavior: Clip.antiAlias,
      child: Stack(children: [
        Positioned(
          right: narrow ? -30 : 40,
          top: narrow ? 20 : 40,
          child: Opacity(
            opacity: narrow ? 0.35 : 1,
            child: Container(
              width: narrow ? 150 : 260,
              height: narrow ? 150 : 260,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(36),
                color: Colors.white.withValues(alpha: 0.06),
                border: Border.all(color: Colors.white.withValues(alpha: 0.10)),
                boxShadow: [BoxShadow(color: a.withValues(alpha: 0.35), blurRadius: 80, spreadRadius: 6)],
              ),
              padding: const EdgeInsets.all(28),
              child: Artwork(url: channel.logo, name: channel.name, padding: 0, radius: 18, textSize: narrow ? 40 : 72),
            ),
          ),
        ),
        Padding(
          padding: EdgeInsets.all(narrow ? 20 : 36),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisAlignment: MainAxisAlignment.end, children: [
            Row(children: [
              const LiveBadge(),
              const SizedBox(width: 10),
              Text(resumed ? 'CONTINUE WATCHING' : 'FEATURED', style: Theme.of(context).textTheme.labelSmall?.copyWith(color: textPrimary)),
            ]),
            const SizedBox(height: 14),
            ConstrainedBox(
              constraints: BoxConstraints(maxWidth: narrow ? 260 : 560),
              child: Text(channel.name, maxLines: 2, overflow: TextOverflow.ellipsis,
                  style: (narrow ? Theme.of(context).textTheme.headlineMedium : Theme.of(context).textTheme.displaySmall)),
            ),
            const SizedBox(height: 8),
            ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 520),
              child: now != null
                  ? Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text('Now · ${now.title}', maxLines: 1, overflow: TextOverflow.ellipsis, style: Theme.of(context).textTheme.titleMedium),
                      const SizedBox(height: 8),
                      SizedBox(width: 260, child: ProgressLine(now.progress(t), height: 3)),
                      if (next != null) ...[
                        const SizedBox(height: 8),
                        Text('Next ${clock(next.start)} · ${next.title}', maxLines: 1, overflow: TextOverflow.ellipsis, style: Theme.of(context).textTheme.bodyMedium),
                      ],
                    ])
                  : Text(
                      [if (channel.group.isNotEmpty) channel.group, if (channel.number > 0) 'Channel ${channel.number}', 'Streaming live now'].join(' · '),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodyLarge?.copyWith(color: textSecondary),
                    ),
            ),
            const SizedBox(height: 22),
            Wrap(spacing: 10, runSpacing: 10, children: [
              FilledButton.icon(icon: const Icon(Icons.play_arrow_rounded), label: const Text('Watch now'), onPressed: watch),
              OutlinedButton.icon(
                icon: Icon(fav ? Icons.star_rounded : Icons.star_outline_rounded, color: fav ? gold : null),
                label: Text(fav ? 'In favourites' : 'Favourite'),
                onPressed: () => catalog.toggleFavorite(channel),
              ),
              if (!narrow) OutlinedButton.icon(icon: const Icon(Icons.live_tv_rounded), label: const Text('All live TV'), onPressed: () => nav(Nav.live)),
            ]),
          ]),
        ),
      ]),
    );
  }
}
