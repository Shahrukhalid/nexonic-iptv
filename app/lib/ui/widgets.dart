import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../epg.dart';
import '../m3u.dart';
import 'theme.dart';

/// Set to false in tests: network images are replaced by their fallback.
bool loadImages = true;

/// Initials of a name for artwork fallbacks.
String initials(String name) {
  final words = name.replaceAll(RegExp(r'[^\p{L}\p{N} ]', unicode: true), ' ').split(' ').where((w) => w.isNotEmpty).toList();
  if (words.isEmpty) return '?';
  if (words.length == 1) return words.first.characters.take(2).toString().toUpperCase();
  return (words[0].characters.first + words[1].characters.first).toUpperCase();
}

String ago(DateTime? t) {
  if (t == null) return 'never';
  final d = DateTime.now().difference(t);
  if (d.inMinutes < 1) return 'just now';
  if (d.inHours < 1) return '${d.inMinutes} min ago';
  if (d.inDays < 1) return '${d.inHours} h ago';
  return '${d.inDays} d ago';
}

String clock(DateTime t) {
  final l = t.toLocal();
  return '${l.hour.toString().padLeft(2, '0')}:${l.minute.toString().padLeft(2, '0')}';
}

String duration(Duration d) {
  final h = d.inHours;
  final m = d.inMinutes.remainder(60).toString().padLeft(2, '0');
  final s = d.inSeconds.remainder(60).toString().padLeft(2, '0');
  return h > 0 ? '$h:$m:$s' : '$m:$s';
}

String compact(int n) => n >= 10000 ? '${(n / 1000).toStringAsFixed(n >= 100000 ? 0 : 1)}k' : '$n';

/// Network artwork with a gradient-and-initials fallback.
class Artwork extends StatelessWidget {
  const Artwork({super.key, required this.url, required this.name, this.fit = BoxFit.contain, this.padding = 10, this.radius = radiusS, this.textSize});
  final String url;
  final String name;
  final BoxFit fit;
  final double padding;
  final double radius;
  final double? textSize;

  @override
  Widget build(BuildContext context) {
    final (a, b) = tintFor(name);
    final fallback = DecoratedBox(
      decoration: BoxDecoration(
        gradient: LinearGradient(colors: [a.withValues(alpha: 0.85), b.withValues(alpha: 0.85)], begin: Alignment.topLeft, end: Alignment.bottomRight),
      ),
      child: Center(
        child: LayoutBuilder(
          builder: (_, c) => Text(
            initials(name),
            style: TextStyle(
              fontSize: textSize ?? (c.biggest.shortestSide * 0.32).clamp(10, 54),
              fontWeight: FontWeight.w800,
              color: Colors.white,
              letterSpacing: -0.5,
            ),
          ),
        ),
      ),
    );
    final ok = loadImages && url.startsWith('http');
    return ClipRRect(
      borderRadius: BorderRadius.circular(radius),
      child: !ok
          ? fallback
          : Container(
              color: fit == BoxFit.cover ? surfaceHigh : Colors.white.withValues(alpha: 0.04),
              padding: fit == BoxFit.cover ? EdgeInsets.zero : EdgeInsets.all(padding),
              child: Image.network(
                url,
                fit: fit,
                cacheWidth: 360,
                filterQuality: FilterQuality.medium,
                errorBuilder: (_, __, ___) => fit == BoxFit.cover ? fallback : _logoFallback(a, b),
                loadingBuilder: (_, child, p) => p == null ? child : const SizedBox.expand(),
              ),
            ),
    );
  }

  Widget _logoFallback(Color a, Color b) => Center(
        child: Text(initials(name),
            style: TextStyle(fontSize: textSize ?? 18, fontWeight: FontWeight.w800, color: Color.lerp(a, Colors.white, 0.35))),
      );
}

/// A square channel logo.
class ChannelLogo extends StatelessWidget {
  const ChannelLogo(this.channel, {super.key, this.size = 44, this.radius = radiusS});
  final Channel channel;
  final double size;
  final double radius;

  @override
  Widget build(BuildContext context) => SizedBox(
        width: size,
        height: size,
        child: Artwork(url: channel.logo, name: channel.name, padding: size * 0.12, radius: radius),
      );
}

/// Red "LIVE" pill.
class LiveBadge extends StatelessWidget {
  const LiveBadge({super.key, this.small = false});
  final bool small;

  @override
  Widget build(BuildContext context) => Container(
        padding: EdgeInsets.symmetric(horizontal: small ? 6 : 8, vertical: small ? 2 : 3),
        decoration: BoxDecoration(color: live, borderRadius: BorderRadius.circular(6)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Container(width: small ? 5 : 6, height: small ? 5 : 6, decoration: const BoxDecoration(color: Colors.white, shape: BoxShape.circle)),
          SizedBox(width: small ? 4 : 5),
          Text('LIVE', style: TextStyle(fontSize: small ? 9.5 : 10.5, fontWeight: FontWeight.w800, letterSpacing: 0.8, color: Colors.white)),
        ]),
      );
}

/// Small rounded label.
class Pill extends StatelessWidget {
  const Pill(this.text, {super.key, this.color = surfaceTop, this.foreground = textSecondary, this.icon});
  final String text;
  final Color color;
  final Color foreground;
  final IconData? icon;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(6)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          if (icon != null) ...[Icon(icon, size: 12, color: foreground), const SizedBox(width: 4)],
          Text(text, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: foreground)),
        ]),
      );
}

/// Thin progress line (programme or film progress).
class ProgressLine extends StatelessWidget {
  const ProgressLine(this.value, {super.key, this.height = 3, this.color = accent});
  final double value;
  final double height;
  final Color color;

  @override
  Widget build(BuildContext context) => ClipRRect(
        borderRadius: BorderRadius.circular(height),
        child: SizedBox(
          height: height,
          child: Stack(fit: StackFit.expand, children: [
            const ColoredBox(color: Color(0x26FFFFFF)),
            FractionallySizedBox(alignment: Alignment.centerLeft, widthFactor: value.clamp(0.0, 1.0), child: ColoredBox(color: color)),
          ]),
        ),
      );
}

/// A focusable, hoverable surface that lifts and shows an accent outline (mouse, keyboard and TV remotes).
class Tappable extends StatefulWidget {
  const Tappable({super.key, required this.child, this.onTap, this.onLongPress, this.onSecondaryTap, this.radius = radiusM, this.scale = 1.03, this.autofocus = false, this.focusNode});
  final Widget child;
  final VoidCallback? onTap;
  final VoidCallback? onLongPress;
  final VoidCallback? onSecondaryTap;
  final double radius;
  final double scale;
  final bool autofocus;
  final FocusNode? focusNode;

  @override
  State<Tappable> createState() => _TappableState();
}

class _TappableState extends State<Tappable> {
  bool hover = false;
  bool focus = false;

  @override
  Widget build(BuildContext context) {
    final on = hover || focus;
    return FocusableActionDetector(
      autofocus: widget.autofocus,
      focusNode: widget.focusNode,
      mouseCursor: SystemMouseCursors.click,
      onShowHoverHighlight: (v) => setState(() => hover = v),
      onShowFocusHighlight: (v) => setState(() => focus = v),
      shortcuts: const {
        SingleActivator(LogicalKeyboardKey.enter): ActivateIntent(),
        SingleActivator(LogicalKeyboardKey.select): ActivateIntent(),
        SingleActivator(LogicalKeyboardKey.gameButtonA): ActivateIntent(),
      },
      actions: {
        ActivateIntent: CallbackAction<ActivateIntent>(onInvoke: (_) {
          widget.onTap?.call();
          return null;
        }),
      },
      child: GestureDetector(
        onTap: widget.onTap,
        onLongPress: widget.onLongPress,
        onSecondaryTap: widget.onSecondaryTap,
        child: AnimatedScale(
          scale: on ? widget.scale : 1,
          duration: const Duration(milliseconds: 160),
          curve: Curves.easeOutCubic,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 160),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(widget.radius + 2),
              border: Border.all(color: focus ? accent : (hover ? Colors.white24 : Colors.transparent), width: focus ? 2 : 1),
              boxShadow: on ? [BoxShadow(color: Colors.black.withValues(alpha: 0.45), blurRadius: 24, offset: const Offset(0, 10))] : const [],
            ),
            child: widget.child,
          ),
        ),
      ),
    );
  }
}

/// A live channel card for rows and grids: logo on a tinted stage, name, and what is on now.
class ChannelCard extends StatelessWidget {
  const ChannelCard({super.key, required this.channel, required this.onTap, this.now, this.favorite = false, this.failing = false, this.onFavorite, this.subtitle, this.progress});
  final Channel channel;
  final VoidCallback onTap;
  final Programme? now;
  final bool favorite;
  final bool failing;
  final VoidCallback? onFavorite;
  final String? subtitle;
  final double? progress;

  @override
  Widget build(BuildContext context) {
    final (a, b) = tintFor(channel.name);
    final t = DateTime.now().toUtc();
    return Tappable(
      onTap: onTap,
      onSecondaryTap: onFavorite,
      onLongPress: onFavorite,
      child: Container(
        decoration: BoxDecoration(
          color: surface,
          borderRadius: BorderRadius.circular(radiusM),
          border: Border.all(color: stroke),
        ),
        clipBehavior: Clip.antiAlias,
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Expanded(
            child: Stack(fit: StackFit.expand, children: [
              DecoratedBox(
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    colors: [a.withValues(alpha: 0.22), b.withValues(alpha: 0.10), surface],
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                  ),
                ),
              ),
              Center(child: FractionallySizedBox(heightFactor: 0.62, child: AspectRatio(aspectRatio: 1, child: Artwork(url: channel.logo, name: channel.name, padding: 6)))),
              Positioned(
                left: 8,
                top: 8,
                child: channel.isRadio
                    ? const Pill('RADIO', icon: Icons.graphic_eq_rounded)
                    : channel.isLive
                        ? const LiveBadge(small: true)
                        : const Pill('VIDEO', icon: Icons.movie_outlined),
              ),
              if (channel.number > 0)
                Positioned(right: 10, top: 8, child: Text('${channel.number}', style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: textMuted))),
              if (favorite) const Positioned(right: 8, bottom: 6, child: Icon(Icons.star_rounded, size: 16, color: gold)),
              if (failing) const Positioned(left: 8, bottom: 6, child: Icon(Icons.error_outline_rounded, size: 16, color: warning)),
            ]),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 9, 12, 10),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(channel.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: Theme.of(context).textTheme.titleSmall),
              const SizedBox(height: 3),
              Text(
                subtitle ?? now?.title ?? (channel.group.isNotEmpty ? channel.group : (channel.isRadio ? 'Radio' : 'Live')),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.bodySmall,
              ),
              if (now != null) ...[const SizedBox(height: 6), ProgressLine(now!.progress(t), height: 2.5)],
              if (now == null && progress != null) ...[const SizedBox(height: 6), ProgressLine(progress!, height: 2.5)],
            ]),
          ),
        ]),
      ),
    );
  }
}

/// A 2:3 poster for films and series.
class PosterCard extends StatelessWidget {
  const PosterCard({super.key, required this.item, required this.onTap, this.progress, this.favorite = false, this.onFavorite});
  final Channel item;
  final VoidCallback onTap;
  final double? progress;
  final bool favorite;
  final VoidCallback? onFavorite;

  @override
  Widget build(BuildContext context) {
    return Tappable(
      onTap: onTap,
      onSecondaryTap: onFavorite,
      onLongPress: onFavorite,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Expanded(
          child: Container(
            decoration: BoxDecoration(borderRadius: BorderRadius.circular(radiusM), border: Border.all(color: stroke)),
            clipBehavior: Clip.antiAlias,
            child: Stack(fit: StackFit.expand, children: [
              Artwork(url: item.logo, name: item.name, fit: BoxFit.cover, radius: radiusM),
              const DecoratedBox(
                decoration: BoxDecoration(
                  gradient: LinearGradient(begin: Alignment.center, end: Alignment.bottomCenter, colors: [Colors.transparent, Color(0xCC000000)]),
                ),
              ),
              if (item.rating.isNotEmpty && item.rating != '0')
                Positioned(left: 8, top: 8, child: Pill(item.rating, icon: Icons.star_rounded, color: const Color(0xCC000000), foreground: gold)),
              if (item.opensSeries) const Positioned(right: 8, top: 8, child: Pill('SERIES', color: Color(0xCC000000), foreground: textPrimary)),
              if (favorite) const Positioned(right: 8, bottom: 8, child: Icon(Icons.star_rounded, size: 18, color: gold)),
              if (progress != null) Positioned(left: 8, right: 8, bottom: 8, child: ProgressLine(progress!, height: 3)),
            ]),
          ),
        ),
        const SizedBox(height: 8),
        Text(item.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: Theme.of(context).textTheme.titleSmall),
        Text(
          [if (item.year.isNotEmpty) item.year, if (item.group.isNotEmpty) item.group].join(' · '),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: Theme.of(context).textTheme.bodySmall,
        ),
      ]),
    );
  }
}

/// Title row above a section, with an optional "See all" action.
class SectionHeader extends StatelessWidget {
  const SectionHeader(this.title, {super.key, this.count, this.onMore, this.icon});
  final String title;
  final int? count;
  final VoidCallback? onMore;
  final IconData? icon;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(0, 0, 0, 12),
        child: Row(children: [
          if (icon != null) ...[Icon(icon, size: 20, color: accent), const SizedBox(width: 8)],
          Text(title, style: Theme.of(context).textTheme.titleLarge),
          if (count != null) ...[const SizedBox(width: 8), Text(compact(count!), style: const TextStyle(color: textMuted, fontWeight: FontWeight.w600))],
          const Spacer(),
          if (onMore != null)
            TextButton(onPressed: onMore, child: const Row(mainAxisSize: MainAxisSize.min, children: [Text('See all'), Icon(Icons.chevron_right_rounded, size: 18)])),
        ]),
      );
}

/// A horizontally scrolling row with arrow buttons on wide screens.
class ContentRow extends StatefulWidget {
  const ContentRow({super.key, required this.title, required this.itemCount, required this.itemBuilder, required this.itemWidth, required this.height, this.onMore, this.count, this.icon, this.padding = 24});
  final String title;
  final int itemCount;
  final IndexedWidgetBuilder itemBuilder;
  final double itemWidth;
  final double height;
  final VoidCallback? onMore;
  final int? count;
  final IconData? icon;
  final double padding;

  @override
  State<ContentRow> createState() => _ContentRowState();
}

class _ContentRowState extends State<ContentRow> {
  final controller = ScrollController();

  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  void _page(int dir) {
    final w = context.size?.width ?? 600;
    controller.animateTo((controller.offset + dir * (w * 0.8)).clamp(0, controller.position.maxScrollExtent),
        duration: const Duration(milliseconds: 420), curve: Curves.easeOutCubic);
  }

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= 840;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Padding(
        padding: EdgeInsets.symmetric(horizontal: widget.padding),
        child: Row(children: [
          Expanded(child: SectionHeader(widget.title, count: widget.count, onMore: widget.onMore, icon: widget.icon)),
          if (wide) ...[
            const SizedBox(width: 4),
            _arrow(Icons.chevron_left_rounded, () => _page(-1)),
            const SizedBox(width: 6),
            _arrow(Icons.chevron_right_rounded, () => _page(1)),
          ],
        ]),
      ),
      SizedBox(
        height: widget.height,
        child: ListView.separated(
          controller: controller,
          scrollDirection: Axis.horizontal,
          clipBehavior: Clip.none,
          padding: EdgeInsets.symmetric(horizontal: widget.padding),
          itemCount: widget.itemCount,
          separatorBuilder: (_, __) => const SizedBox(width: 14),
          itemBuilder: (c, i) => SizedBox(width: widget.itemWidth, child: widget.itemBuilder(c, i)),
        ),
      ),
    ]);
  }

  Widget _arrow(IconData icon, VoidCallback onTap) => Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: Material(
          color: surfaceHigh,
          shape: const CircleBorder(side: BorderSide(color: stroke)),
          child: InkWell(customBorder: const CircleBorder(), onTap: onTap, child: Padding(padding: const EdgeInsets.all(5), child: Icon(icon, size: 20))),
        ),
      );
}

/// Centered icon, message and an optional action.
class EmptyState extends StatelessWidget {
  const EmptyState({super.key, required this.icon, required this.title, this.message, this.action});
  final IconData icon;
  final String title;
  final String? message;
  final Widget? action;

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Container(
                width: 72,
                height: 72,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  gradient: LinearGradient(colors: [accent.withValues(alpha: 0.18), accent2.withValues(alpha: 0.10)]),
                  border: Border.all(color: stroke),
                ),
                child: Icon(icon, size: 32, color: accent),
              ),
              const SizedBox(height: 18),
              Text(title, textAlign: TextAlign.center, style: Theme.of(context).textTheme.titleLarge),
              if (message != null) ...[const SizedBox(height: 8), Text(message!, textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodyMedium)],
              if (action != null) ...[const SizedBox(height: 20), action!],
            ]),
          ),
        ),
      );
}

/// Search box with a clear button.
class SearchField extends StatefulWidget {
  const SearchField({super.key, required this.onChanged, this.hint = 'Search', this.autofocus = false, this.initial = ''});
  final ValueChanged<String> onChanged;
  final String hint;
  final bool autofocus;
  final String initial;

  @override
  State<SearchField> createState() => _SearchFieldState();
}

class _SearchFieldState extends State<SearchField> {
  late final controller = TextEditingController(text: widget.initial);

  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => TextField(
        controller: controller,
        autofocus: widget.autofocus,
        onChanged: (v) {
          setState(() {});
          widget.onChanged(v);
        },
        decoration: InputDecoration(
          hintText: widget.hint,
          prefixIcon: const Icon(Icons.search_rounded, size: 20),
          suffixIcon: controller.text.isEmpty
              ? null
              : IconButton(
                  icon: const Icon(Icons.close_rounded, size: 18),
                  onPressed: () {
                    controller.clear();
                    setState(() {});
                    widget.onChanged('');
                  },
                ),
        ),
      );
}

/// A compact dropdown filter: "Country: Any".
class FilterMenu extends StatelessWidget {
  const FilterMenu({super.key, required this.label, required this.value, required this.options, required this.onChanged, this.icon});
  final String label;
  final String value;
  final List<(String, String)> options;
  final ValueChanged<String> onChanged;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final current = options.where((o) => o.$1 == value).firstOrNull?.$2;
    return PopupMenuButton<String>(
      tooltip: label,
      onSelected: onChanged,
      constraints: const BoxConstraints(maxHeight: 460, minWidth: 220),
      itemBuilder: (_) => [
        PopupMenuItem(value: '', child: Text('Any ${label.toLowerCase()}')),
        const PopupMenuDivider(),
        for (final (v, l) in options) PopupMenuItem(value: v, child: Text(l, maxLines: 1, overflow: TextOverflow.ellipsis)),
      ],
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
        decoration: BoxDecoration(
          color: value.isEmpty ? surfaceHigh : accent.withValues(alpha: 0.14),
          borderRadius: BorderRadius.circular(999),
          border: Border.all(color: value.isEmpty ? stroke : accent.withValues(alpha: 0.5)),
        ),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          if (icon != null) ...[Icon(icon, size: 16, color: value.isEmpty ? textSecondary : accent), const SizedBox(width: 6)],
          Text(current ?? label, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: value.isEmpty ? textPrimary : accent)),
          const SizedBox(width: 4),
          Icon(Icons.expand_more_rounded, size: 18, color: value.isEmpty ? textSecondary : accent),
        ]),
      ),
    );
  }
}

/// Horizontal category chips.
class ChipBar extends StatelessWidget {
  const ChipBar({super.key, required this.items, required this.selected, required this.onSelected, this.padding = 24});
  final List<(String, String)> items;
  final String selected;
  final ValueChanged<String> onSelected;
  final double padding;

  @override
  Widget build(BuildContext context) => SizedBox(
        height: 40,
        child: ListView.separated(
          scrollDirection: Axis.horizontal,
          padding: EdgeInsets.symmetric(horizontal: padding),
          itemCount: items.length,
          separatorBuilder: (_, __) => const SizedBox(width: 8),
          itemBuilder: (_, i) {
            final (value, label) = items[i];
            final on = value == selected;
            return ChoiceChip(
              label: Text(label),
              selected: on,
              labelStyle: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: on ? accent : textPrimary),
              side: BorderSide(color: on ? accent.withValues(alpha: 0.5) : stroke),
              onSelected: (_) => onSelected(value),
            );
          },
        ),
      );
}

/// Page title with a subtitle and trailing actions.
class PageHeader extends StatelessWidget {
  const PageHeader({super.key, required this.title, this.subtitle, this.actions = const [], this.padding = 24});
  final String title;
  final String? subtitle;
  final List<Widget> actions;
  final double padding;

  @override
  Widget build(BuildContext context) {
    final narrow = MediaQuery.sizeOf(context).width < 600;
    return Padding(
      padding: EdgeInsets.fromLTRB(padding, narrow ? 12 : 24, padding, 14),
      child: Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: narrow ? Theme.of(context).textTheme.headlineSmall : Theme.of(context).textTheme.headlineMedium),
            if (subtitle != null) ...[const SizedBox(height: 4), Text(subtitle!, style: Theme.of(context).textTheme.bodyMedium)],
          ]),
        ),
        ...actions,
      ]),
    );
  }
}
