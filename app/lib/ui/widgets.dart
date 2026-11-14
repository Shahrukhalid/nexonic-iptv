import 'package:flutter/material.dart';

import '../m3u.dart';
import 'theme.dart';

/// Channel logo with a lettered fallback when there is no logo or it does not load.
class ChannelLogo extends StatelessWidget {
  const ChannelLogo(this.channel, {super.key, this.size = 56});
  final Channel channel;
  final double size;

  @override
  Widget build(BuildContext context) {
    final fallback = Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(size / 4),
        gradient: const LinearGradient(colors: [accent2, accent], begin: Alignment.topLeft, end: Alignment.bottomRight),
      ),
      child: Text(
        _initials(channel.name),
        style: TextStyle(fontSize: size / 3, fontWeight: FontWeight.w700, color: Colors.white),
      ),
    );
    if (channel.logo.isEmpty) return fallback;
    return SizedBox(
      width: size,
      height: size,
      child: Image.network(
        channel.logo,
        fit: BoxFit.contain,
        cacheWidth: (size * 2).round(),
        errorBuilder: (_, __, ___) => fallback,
        loadingBuilder: (c, child, p) => p == null ? child : fallback,
      ),
    );
  }

  static String _initials(String name) {
    final words = name.split(RegExp(r'\s+')).where((w) => w.isNotEmpty).toList();
    if (words.isEmpty) return '?';
    return words.take(2).map((w) => w.characters.first.toUpperCase()).join();
  }
}

class ChannelCard extends StatelessWidget {
  const ChannelCard({
    super.key,
    required this.channel,
    required this.favorite,
    required this.onTap,
    required this.onFavorite,
    this.subtitle,
    this.warning = false,
  });

  final Channel channel;
  final bool favorite;
  final VoidCallback onTap;
  final VoidCallback onFavorite;
  final String? subtitle;
  final bool warning;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  ChannelLogo(channel, size: 48),
                  const Spacer(),
                  if (warning) const Tooltip(message: 'Not working at the moment', child: Icon(Icons.error_outline, size: 18, color: Colors.amber)),
                  IconButton(
                    visualDensity: VisualDensity.compact,
                    tooltip: favorite ? 'Remove from favourites' : 'Add to favourites',
                    icon: Icon(favorite ? Icons.star_rounded : Icons.star_outline_rounded, color: favorite ? accent : null),
                    onPressed: onFavorite,
                  ),
                ],
              ),
              const Spacer(),
              Text(channel.name, maxLines: 2, overflow: TextOverflow.ellipsis, style: t.titleSmall?.copyWith(fontWeight: FontWeight.w600)),
              const SizedBox(height: 2),
              Text(
                subtitle ?? channel.group,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: t.bodySmall?.copyWith(color: Colors.white60),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Small dropdown used for the country, language and category filters.
class FilterMenu extends StatelessWidget {
  const FilterMenu({super.key, required this.label, required this.value, required this.options, required this.onChanged});
  final String label;
  final String value;
  final List<(String, String)> options; // (value, label)
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    final selected = options.where((o) => o.$1 == value).firstOrNull;
    return PopupMenuButton<String>(
      tooltip: label,
      onSelected: onChanged,
      itemBuilder: (_) => [
        PopupMenuItem(value: '', child: Text('All ${label.toLowerCase()}s')),
        for (final o in options) PopupMenuItem(value: o.$1, child: Text(o.$2)),
      ],
      child: Chip(
        avatar: Icon(Icons.filter_list_rounded, size: 16, color: value.isEmpty ? null : accent),
        label: Text(selected == null ? label : selected.$2),
        side: BorderSide(color: value.isEmpty ? Colors.white12 : accent),
      ),
    );
  }
}
