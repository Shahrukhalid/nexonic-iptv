import 'package:flutter/material.dart';

import '../catalog.dart';
import '../epg.dart';
import '../m3u.dart';
import 'player.dart';
import 'shell.dart';
import 'theme.dart';
import 'widgets.dart';

/// TV guide: a timeline grid of programmes per channel, with a "now" line and jump-to-now.
class GuidePage extends StatefulWidget {
  const GuidePage({super.key, required this.catalog, required this.nav, this.now});
  final Catalog catalog;
  final Navigate nav;

  /// Fixed "now" for screenshots.
  final DateTime? now;

  @override
  State<GuidePage> createState() => _GuidePageState();
}

class _GuidePageState extends State<GuidePage> {
  String group = '';
  final hScroll = ScrollController();
  final vNames = ScrollController();
  final vGrid = ScrollController();
  bool _syncing = false;
  late DateTime now = (widget.now ?? DateTime.now()).toUtc();
  late DateTime start = DateTime.utc(now.year, now.month, now.day, now.hour, now.minute >= 30 ? 30 : 0).subtract(const Duration(minutes: 30));
  static const hours = 24;
  static const rowHeight = 66.0;

  Catalog get catalog => widget.catalog;

  @override
  void initState() {
    super.initState();
    vNames.addListener(() => _sync(vNames, vGrid));
    vGrid.addListener(() => _sync(vGrid, vNames));
  }

  void _sync(ScrollController from, ScrollController to) {
    if (_syncing || !to.hasClients) return;
    _syncing = true;
    to.jumpTo(from.offset.clamp(0, to.position.maxScrollExtent));
    _syncing = false;
  }

  @override
  void dispose() {
    hScroll.dispose();
    vNames.dispose();
    vGrid.dispose();
    super.dispose();
  }

  double _perMinute(BuildContext context) => MediaQuery.sizeOf(context).width < 700 ? 3.2 : 4.4;

  void _jumpNow(double perMin) {
    if (!hScroll.hasClients) return;
    final x = (DateTime.now().toUtc().difference(start).inMinutes - 20) * perMin;
    hScroll.animateTo(x.clamp(0, hScroll.position.maxScrollExtent), duration: const Duration(milliseconds: 400), curve: Curves.easeOutCubic);
  }

  @override
  Widget build(BuildContext context) {
    final g = catalog.guide;
    final narrow = MediaQuery.sizeOf(context).width < 700;
    final perMin = _perMinute(context);
    final all = catalog.items('live');
    final groups = groupCounts(all);
    final channels = [for (final c in filterChannels(all, group: group)) if (g.programmes(c.tvgId, c.name).isNotEmpty) c];
    final header = PageHeader(
      title: 'TV guide',
      padding: narrow ? 16 : 24,
      subtitle: g.isEmpty ? null : '${channels.length} channels with programme information',
      actions: [
        if (!g.isEmpty && groups.length > 1)
          FilterMenu(label: 'Category', icon: Icons.category_outlined, value: group, options: [for (final (x, _) in groups) (x, x)], onChanged: (v) => setState(() => group = v)),
        const SizedBox(width: 8),
        if (!g.isEmpty) FilledButton.tonalIcon(icon: const Icon(Icons.my_location_rounded, size: 18), label: const Text('Now'), onPressed: () => _jumpNow(perMin)),
      ],
    );
    if (g.isEmpty || channels.isEmpty) {
      return Column(children: [
        header,
        Expanded(
          child: EmptyState(
            icon: Icons.calendar_view_week_outlined,
            title: g.isEmpty ? 'No programme guide yet' : 'No guide for these channels',
            message: g.isEmpty
                ? 'Guides come from your playlists. Xtream Codes logins include one, and you can add an XMLTV (EPG) link to any M3U playlist.'
                : 'Pick another category, or add a guide (EPG) link that covers these channels.',
            action: OutlinedButton.icon(icon: const Icon(Icons.playlist_play_rounded), label: const Text('Open playlists'), onPressed: () => widget.nav(Nav.sources)),
          ),
        ),
      ]);
    }
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (hScroll.hasClients && hScroll.offset == 0) {
        hScroll.jumpTo(((now.difference(start).inMinutes - 20) * perMin).clamp(0, hScroll.position.maxScrollExtent));
      }
    });
    final nameWidth = narrow ? 112.0 : 210.0;
    final width = hours * 60 * perMin;
    final nowX = now.difference(start).inMinutes * perMin;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      header,
      Expanded(
        child: Container(
          margin: EdgeInsets.fromLTRB(narrow ? 8 : 24, 0, narrow ? 8 : 24, narrow ? 8 : 24),
          decoration: BoxDecoration(color: background2, borderRadius: BorderRadius.circular(radiusL), border: Border.all(color: stroke)),
          clipBehavior: Clip.antiAlias,
          child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            SizedBox(
              width: nameWidth,
              child: Column(children: [
                Container(height: 44, alignment: Alignment.centerLeft, padding: const EdgeInsets.symmetric(horizontal: 14),
                    child: Text(_day(now), style: const TextStyle(fontWeight: FontWeight.w700))),
                const Divider(),
                Expanded(
                  child: ListView.builder(
                    controller: vNames,
                    itemExtent: rowHeight,
                    itemCount: channels.length,
                    itemBuilder: (_, i) => _ChannelCell(channel: channels[i], compact: narrow, onTap: () => openPlayer(context, catalog, channels, i)),
                  ),
                ),
              ]),
            ),
            const VerticalDivider(width: 1),
            Expanded(
              child: Scrollbar(
                controller: hScroll,
                child: SingleChildScrollView(
                  controller: hScroll,
                  scrollDirection: Axis.horizontal,
                  child: SizedBox(
                    width: width,
                    child: Stack(children: [
                      Column(children: [
                        SizedBox(height: 44, child: _TimeRuler(start: start, hours: hours, perMinute: perMin)),
                        const Divider(),
                        Expanded(
                          child: ListView.builder(
                            controller: vGrid,
                            itemExtent: rowHeight,
                            itemCount: channels.length,
                            itemBuilder: (_, i) {
                              final c = channels[i];
                              return _ProgrammeRow(
                                programmes: g.programmes(c.tvgId, c.name),
                                start: start,
                                perMinute: perMin,
                                now: now,
                                onTap: (p) => _details(context, c, channels, i, p),
                              );
                            },
                          ),
                        ),
                      ]),
                      if (nowX > 0 && nowX < width)
                        Positioned(
                          left: nowX - 1,
                          top: 30,
                          bottom: 0,
                          child: IgnorePointer(
                            child: Column(children: [
                              Container(width: 10, height: 10, decoration: const BoxDecoration(color: live, shape: BoxShape.circle)),
                              Expanded(child: Container(width: 2, color: live)),
                            ]),
                          ),
                        ),
                    ]),
                  ),
                ),
              ),
            ),
          ]),
        ),
      ),
    ]);
  }

  static String _day(DateTime t) {
    const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    final l = t.toLocal();
    return '${days[l.weekday - 1]} ${l.day} ${months[l.month - 1]}';
  }

  void _details(BuildContext context, Channel c, List<Channel> list, int i, Programme p) {
    final t = DateTime.now().toUtc();
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      constraints: const BoxConstraints(maxWidth: 640),
      builder: (_) => Padding(
        padding: const EdgeInsets.fromLTRB(24, 0, 24, 28),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            ChannelLogo(c, size: 40),
            const SizedBox(width: 12),
            Expanded(child: Text(c.name, style: Theme.of(context).textTheme.titleMedium)),
            if (p.isOn(t)) const LiveBadge(),
          ]),
          const SizedBox(height: 16),
          Text(p.title, style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 6),
          Text('${_day(p.start)} · ${clock(p.start)} – ${clock(p.stop)} · ${p.stop.difference(p.start).inMinutes} min', style: Theme.of(context).textTheme.bodyMedium),
          if (p.isOn(t)) ...[const SizedBox(height: 12), ProgressLine(p.progress(t), height: 4)],
          if (p.desc.isNotEmpty) ...[const SizedBox(height: 14), Text(p.desc, style: Theme.of(context).textTheme.bodyLarge?.copyWith(color: textSecondary))],
          const SizedBox(height: 20),
          FilledButton.icon(
            icon: const Icon(Icons.play_arrow_rounded),
            label: Text(p.isOn(t) ? 'Watch now' : 'Watch channel'),
            onPressed: () {
              Navigator.of(context).pop();
              openPlayer(context, catalog, list, i);
            },
          ),
        ]),
      ),
    );
  }
}

class _ChannelCell extends StatelessWidget {
  const _ChannelCell({required this.channel, required this.compact, required this.onTap});
  final Channel channel;
  final bool compact;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => InkWell(
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10),
          decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: stroke))),
          child: Row(children: [
            ChannelLogo(channel, size: compact ? 34 : 40),
            if (!compact) ...[
              const SizedBox(width: 10),
              Expanded(
                child: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [
                  if (channel.number > 0) Text('${channel.number}', style: const TextStyle(fontSize: 11, color: textMuted, fontWeight: FontWeight.w700)),
                  Text(channel.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                ]),
              ),
            ] else ...[
              const SizedBox(width: 6),
              Expanded(child: Text(channel.name, maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600))),
            ],
          ]),
        ),
      );
}

class _TimeRuler extends StatelessWidget {
  const _TimeRuler({required this.start, required this.hours, required this.perMinute});
  final DateTime start;
  final int hours;
  final double perMinute;

  @override
  Widget build(BuildContext context) => Stack(children: [
        for (var m = 0; m < hours * 60; m += 30)
          Positioned(
            left: m * perMinute,
            top: 0,
            bottom: 0,
            child: Container(
              padding: const EdgeInsets.only(left: 8),
              alignment: Alignment.centerLeft,
              decoration: const BoxDecoration(border: Border(left: BorderSide(color: stroke))),
              child: Text(clock(start.add(Duration(minutes: m))),
                  style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: m % 60 == 0 ? textPrimary : textMuted)),
            ),
          ),
      ]);
}

class _ProgrammeRow extends StatelessWidget {
  const _ProgrammeRow({required this.programmes, required this.start, required this.perMinute, required this.now, required this.onTap});
  final List<Programme> programmes;
  final DateTime start;
  final double perMinute;
  final DateTime now;
  final ValueChanged<Programme> onTap;

  @override
  Widget build(BuildContext context) {
    final end = start.add(const Duration(hours: 24));
    final visible = programmes.where((p) => p.stop.isAfter(start) && p.start.isBefore(end));
    return Container(
      decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: stroke))),
      child: Stack(children: [
        for (final p in visible)
          Builder(builder: (context) {
            final s = p.start.isBefore(start) ? start : p.start;
            final left = s.difference(start).inMinutes * perMinute;
            final w = (p.stop.difference(s).inMinutes * perMinute - 4).clamp(8.0, double.infinity);
            final on = p.isOn(now);
            final past = !p.stop.isAfter(now);
            return Positioned(
              left: left + 2,
              top: 5,
              bottom: 5,
              width: w,
              child: Material(
                color: on ? accent.withValues(alpha: 0.16) : (past ? Colors.white.withValues(alpha: 0.025) : surfaceHigh),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(8),
                  side: BorderSide(color: on ? accent.withValues(alpha: 0.5) : stroke),
                ),
                child: InkWell(
                  borderRadius: BorderRadius.circular(8),
                  onTap: () => onTap(p),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisAlignment: MainAxisAlignment.center, children: [
                      Text(p.title, maxLines: 1, overflow: TextOverflow.ellipsis,
                          style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: past ? textMuted : textPrimary)),
                      if (w > 90)
                        Text('${clock(p.start)} – ${clock(p.stop)}', maxLines: 1, style: TextStyle(fontSize: 11, color: on ? accent : textMuted)),
                    ]),
                  ),
                ),
              ),
            );
          }),
      ]),
    );
  }
}
