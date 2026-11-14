import 'package:flutter/material.dart';

import '../catalog.dart';
import '../m3u.dart';
import 'player.dart';
import 'shell.dart';
import 'theme.dart';
import 'widgets.dart';

/// Set to false in tests and screenshots: the preview panel shows the channel artwork instead of playing.
bool previewPlayback = true;

const _favGroup = '★';

/// Live TV: categories, the channel list with what is on now, and a preview with the programme guide.
class LivePage extends StatefulWidget {
  const LivePage({super.key, required this.catalog, required this.nav, this.initialGroup});
  final Catalog catalog;
  final Navigate nav;
  final String? initialGroup;

  @override
  State<LivePage> createState() => _LivePageState();
}

class _LivePageState extends State<LivePage> {
  late String group = widget.initialGroup ?? '';
  String country = '';
  String query = '';
  Channel? selected;
  final previewKey = GlobalKey<PreviewPlayerState>();
  final listController = ScrollController();

  Catalog get catalog => widget.catalog;

  @override
  void dispose() {
    listController.dispose();
    super.dispose();
  }

  List<Channel> get _all => catalog.items('live');

  List<Channel> _shown() {
    final base = group == _favGroup ? [for (final c in _all) if (catalog.isFavorite(c)) c] : _all;
    return filterChannels(base, query: query, country: country, group: group == _favGroup ? '' : group);
  }

  Future<void> _play(List<Channel> list, int i) async {
    await previewKey.currentState?.pause();
    if (!mounted) return;
    await openPlayer(context, catalog, list, i);
    if (mounted) previewKey.currentState?.resume();
  }

  @override
  Widget build(BuildContext context) {
    final w = MediaQuery.sizeOf(context).width;
    final layout = w >= 1180 ? 3 : (w >= 900 ? 2 : 1);
    final list = _shown();
    if (_all.isEmpty) {
      return catalog.isBusy
          ? const Center(child: CircularProgressIndicator())
          : EmptyState(
              icon: Icons.live_tv_outlined,
              title: 'No live channels',
              message: 'Add a playlist with live channels, or turn on the free Nexonic channels in Playlists.',
              action: FilledButton(onPressed: () => widget.nav(Nav.sources), child: const Text('Open playlists')),
            );
    }
    if (layout == 3 && (selected == null || !list.contains(selected)) && list.isNotEmpty) selected = list.first;
    final groups = groupCounts(_all);
    final countries = {for (final c in _all) if (c.country.isNotEmpty) c.country}.toList()
      ..sort((a, b) => (catalog.countryNames[a] ?? a).compareTo(catalog.countryNames[b] ?? b));

    final header = Padding(
      padding: EdgeInsets.fromLTRB(layout == 1 ? 16 : 20, layout == 1 ? 12 : 22, layout == 1 ? 16 : 20, 12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Expanded(child: Text(group.isEmpty ? 'All channels' : (group == _favGroup ? 'Favourites' : group), style: Theme.of(context).textTheme.headlineSmall)),
          Text('${list.length}', style: const TextStyle(color: textMuted, fontWeight: FontWeight.w700)),
        ]),
        const SizedBox(height: 12),
        Row(children: [
          Expanded(child: SearchField(hint: 'Search channels', onChanged: (v) => setState(() => query = v))),
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
        ]),
      ]),
    );

    final channelList = Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      header,
      if (layout == 1)
        Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: ChipBar(
            padding: 16,
            items: [('', 'All'), if (catalog.favorites.isNotEmpty) (_favGroup, 'Favourites'), for (final (g, _) in groups) (g, g)],
            selected: group,
            onSelected: (v) => setState(() => group = v),
          ),
        ),
      Expanded(
        child: list.isEmpty
            ? const EmptyState(icon: Icons.search_off_rounded, title: 'Nothing matches', message: 'Try another search or category.')
            : Scrollbar(
                controller: listController,
                child: ListView.builder(
                  controller: listController,
                  padding: EdgeInsets.fromLTRB(layout == 1 ? 8 : 12, 0, layout == 1 ? 8 : 12, 16),
                  itemExtent: 72,
                  itemCount: list.length,
                  itemBuilder: (_, i) {
                    final c = list[i];
                    return _ChannelRow(
                      channel: c,
                      catalog: catalog,
                      selected: layout == 3 && selected?.key == c.key,
                      onTap: () {
                        if (layout == 3 && selected?.key != c.key) {
                          setState(() => selected = c);
                        } else {
                          _play(list, i);
                        }
                      },
                      onPlay: () => _play(list, i),
                    );
                  },
                ),
              ),
      ),
    ]);

    if (layout == 1) return channelList;
    return Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      SizedBox(
        width: 236,
        child: _Categories(
          groups: groups,
          total: _all.length,
          favorites: [for (final c in _all) if (catalog.isFavorite(c)) c].length,
          selected: group,
          onSelect: (g) => setState(() => group = g),
        ),
      ),
      const VerticalDivider(width: 1),
      if (layout == 2) Expanded(child: channelList) else SizedBox(width: 420, child: channelList),
      if (layout == 3) ...[
        const VerticalDivider(width: 1),
        Expanded(
          child: selected == null
              ? const SizedBox.shrink()
              : _Preview(
                  catalog: catalog,
                  channel: selected!,
                  previewKey: previewKey,
                  onWatch: () {
                    final i = list.indexWhere((c) => c.key == selected!.key);
                    if (i >= 0) _play(list, i);
                  },
                ),
        ),
      ],
    ]);
  }
}

class _Categories extends StatelessWidget {
  const _Categories({required this.groups, required this.total, required this.favorites, required this.selected, required this.onSelect});
  final List<(String, int)> groups;
  final int total;
  final int favorites;
  final String selected;
  final ValueChanged<String> onSelect;

  @override
  Widget build(BuildContext context) {
    Widget tile(String value, String label, int count, {IconData? icon}) {
      final on = selected == value;
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 1),
        child: Material(
          color: on ? accent.withValues(alpha: 0.12) : Colors.transparent,
          borderRadius: BorderRadius.circular(radiusS),
          child: InkWell(
            borderRadius: BorderRadius.circular(radiusS),
            onTap: () => onSelect(value),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              child: Row(children: [
                if (icon != null) ...[Icon(icon, size: 18, color: on ? accent : textSecondary), const SizedBox(width: 10)],
                Expanded(
                  child: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontSize: 13.5, fontWeight: on ? FontWeight.w700 : FontWeight.w500, color: on ? textPrimary : textSecondary)),
                ),
                Text(compact(count), style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w600, color: on ? accent : textMuted)),
              ]),
            ),
          ),
        ),
      );
    }

    return ListView(padding: const EdgeInsets.fromLTRB(10, 22, 10, 16), children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
        child: Text('CATEGORIES', style: Theme.of(context).textTheme.labelSmall?.copyWith(color: textMuted)),
      ),
      tile('', 'All channels', total, icon: Icons.apps_rounded),
      if (favorites > 0) tile(_favGroup, 'Favourites', favorites, icon: Icons.star_rounded),
      const Padding(padding: EdgeInsets.symmetric(vertical: 8), child: Divider()),
      for (final (g, n) in groups) tile(g, g, n),
    ]);
  }
}

class _ChannelRow extends StatelessWidget {
  const _ChannelRow({required this.channel, required this.catalog, required this.selected, required this.onTap, required this.onPlay});
  final Channel channel;
  final Catalog catalog;
  final bool selected;
  final VoidCallback onTap;
  final VoidCallback onPlay;

  @override
  Widget build(BuildContext context) {
    final c = channel;
    final (now, _) = catalog.nowNext(c);
    final fav = catalog.isFavorite(c);
    final failing = catalog.failing.contains(c.key);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Tappable(
        scale: 1.0,
        radius: radiusS,
        onTap: onTap,
        onSecondaryTap: () => catalog.toggleFavorite(c),
        onLongPress: () => catalog.toggleFavorite(c),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10),
          decoration: BoxDecoration(
            color: selected ? accent.withValues(alpha: 0.12) : surface.withValues(alpha: 0.6),
            borderRadius: BorderRadius.circular(radiusS),
            border: Border.all(color: selected ? accent.withValues(alpha: 0.45) : stroke),
          ),
          child: Row(children: [
            SizedBox(
              width: 38,
              child: Text(c.number > 0 ? '${c.number}' : '',
                  style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: selected ? accent : textMuted)),
            ),
            ChannelLogo(c, size: 44),
            const SizedBox(width: 12),
            Expanded(
              child: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(c.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14)),
                const SizedBox(height: 3),
                Text(
                  now?.title ?? (c.group.isNotEmpty ? c.group : 'Live'),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 12, color: textSecondary),
                ),
                if (now != null) ...[const SizedBox(height: 5), ProgressLine(now.progress(DateTime.now().toUtc()), height: 2)],
              ]),
            ),
            if (failing) const Padding(padding: EdgeInsets.only(left: 6), child: Icon(Icons.error_outline_rounded, size: 16, color: warning)),
            if (fav) const Padding(padding: EdgeInsets.only(left: 6), child: Icon(Icons.star_rounded, size: 16, color: gold)),
            if (selected)
              IconButton(tooltip: 'Watch full screen', icon: const Icon(Icons.play_circle_fill_rounded, color: accent), onPressed: onPlay),
          ]),
        ),
      ),
    );
  }
}

class _Preview extends StatelessWidget {
  const _Preview({required this.catalog, required this.channel, required this.previewKey, required this.onWatch});
  final Catalog catalog;
  final Channel channel;
  final GlobalKey<PreviewPlayerState> previewKey;
  final VoidCallback onWatch;

  @override
  Widget build(BuildContext context) {
    final c = channel;
    final t = DateTime.now().toUtc();
    final programmes = catalog.guide.programmes(c.tvgId, c.name).where((p) => p.stop.isAfter(t)).take(6).toList();
    final now = programmes.where((p) => p.isOn(t)).firstOrNull;
    final fav = catalog.isFavorite(c);
    final (a, _) = tintFor(c.name);
    final play = previewPlayback && catalog.settings.livePreview;
    return ListView(padding: const EdgeInsets.all(22), children: [
      ClipRRect(
        borderRadius: BorderRadius.circular(radiusL),
        child: AspectRatio(
          aspectRatio: 16 / 9,
          child: play
              ? PreviewPlayer(key: previewKey, catalog: catalog, channel: c)
              : Container(
                  decoration: BoxDecoration(gradient: RadialGradient(colors: [a.withValues(alpha: 0.35), Colors.black], radius: 1.0)),
                  child: Center(child: ChannelLogo(c, size: 96, radius: radiusM)),
                ),
        ),
      ),
      const SizedBox(height: 18),
      Row(children: [
        ChannelLogo(c, size: 52),
        const SizedBox(width: 14),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              const LiveBadge(small: true),
              const SizedBox(width: 8),
              if (c.number > 0) Text('CH ${c.number}', style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: textMuted)),
            ]),
            const SizedBox(height: 4),
            Text(c.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: Theme.of(context).textTheme.headlineSmall),
            if (c.group.isNotEmpty) Text(c.group, style: Theme.of(context).textTheme.bodyMedium),
          ]),
        ),
      ]),
      const SizedBox(height: 16),
      Wrap(spacing: 10, runSpacing: 10, children: [
        FilledButton.icon(icon: const Icon(Icons.fullscreen_rounded), label: const Text('Watch full screen'), onPressed: onWatch),
        OutlinedButton.icon(
          icon: Icon(fav ? Icons.star_rounded : Icons.star_outline_rounded, color: fav ? gold : null),
          label: Text(fav ? 'In favourites' : 'Favourite'),
          onPressed: () => catalog.toggleFavorite(c),
        ),
      ]),
      const SizedBox(height: 24),
      if (programmes.isEmpty)
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(color: surface, borderRadius: BorderRadius.circular(radiusM), border: Border.all(color: stroke)),
          child: const Row(children: [
            Icon(Icons.event_note_outlined, color: textMuted),
            SizedBox(width: 12),
            Expanded(child: Text('No programme information for this channel. Add a guide (EPG) link to its playlist to see what is on.')),
          ]),
        )
      else ...[
        Text('PROGRAMME GUIDE', style: Theme.of(context).textTheme.labelSmall?.copyWith(color: textMuted)),
        const SizedBox(height: 10),
        for (final p in programmes)
          Container(
            margin: const EdgeInsets.only(bottom: 8),
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: p == now ? accent.withValues(alpha: 0.10) : surface,
              borderRadius: BorderRadius.circular(radiusM),
              border: Border.all(color: p == now ? accent.withValues(alpha: 0.4) : stroke),
            ),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Text('${clock(p.start)} – ${clock(p.stop)}', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: p == now ? accent : textSecondary)),
                if (p == now) ...[const SizedBox(width: 8), const Pill('NOW', color: Color(0x3322D3EE), foreground: accent)],
              ]),
              const SizedBox(height: 4),
              Text(p.title, style: const TextStyle(fontWeight: FontWeight.w600)),
              if (p.desc.isNotEmpty && p == now) ...[
                const SizedBox(height: 6),
                Text(p.desc, maxLines: 4, overflow: TextOverflow.ellipsis, style: Theme.of(context).textTheme.bodyMedium),
              ],
              if (p == now) ...[const SizedBox(height: 10), ProgressLine(p.progress(t))],
            ]),
          ),
      ],
    ]);
  }
}
