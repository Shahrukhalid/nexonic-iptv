import 'package:flutter/material.dart';

import '../catalog.dart';
import 'theme.dart';
import 'widgets.dart';

const appVersion = String.fromEnvironment('APP_VERSION', defaultValue: '1.4.0');

class SettingsPage extends StatelessWidget {
  const SettingsPage({super.key, required this.catalog});
  final Catalog catalog;

  @override
  Widget build(BuildContext context) {
    final s = catalog.settings;
    final narrow = MediaQuery.sizeOf(context).width < 600;
    final pad = narrow ? 16.0 : 32.0;
    void save() => catalog.saveSettings();
    return ListView(padding: const EdgeInsets.only(bottom: 32), children: [
      PageHeader(title: 'Settings', padding: pad),
      Padding(
        padding: EdgeInsets.symmetric(horizontal: pad),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            _Group(title: 'Playback', children: [
              _Toggle(
                icon: Icons.memory_rounded,
                title: 'Hardware video decoding',
                subtitle: 'Smoother, cooler playback. Turn off if a stream shows a black picture.',
                value: s.hardwareDecoding,
                onChanged: (v) {
                  s.hardwareDecoding = v;
                  save();
                },
              ),
              _Toggle(
                icon: Icons.restore_rounded,
                title: 'Resume films and episodes',
                subtitle: 'Continue where you stopped.',
                value: s.resume,
                onChanged: (v) {
                  s.resume = v;
                  save();
                },
              ),
              _Toggle(
                icon: Icons.picture_in_picture_alt_outlined,
                title: 'Live preview',
                subtitle: 'Play the selected channel in the Live TV panel on large screens.',
                value: s.livePreview,
                onChanged: (v) {
                  s.livePreview = v;
                  save();
                },
              ),
              _Choice<int>(
                icon: Icons.speed_rounded,
                title: 'Buffer',
                subtitle: 'A larger buffer rides out slow connections.',
                value: s.bufferMb,
                options: const [(32, 'Small'), (64, 'Normal'), (128, 'Large')],
                onChanged: (v) {
                  s.bufferMb = v;
                  save();
                },
              ),
              _Choice<String>(
                icon: Icons.stream_rounded,
                title: 'Xtream live format',
                subtitle: 'Try HLS if live channels from a login do not start.',
                value: s.xtreamFormat,
                options: const [('ts', 'MPEG-TS'), ('m3u8', 'HLS')],
                onChanged: (v) {
                  s.xtreamFormat = v;
                  save();
                },
              ),
            ]),
            _Group(title: 'Playlists', children: [
              _Choice<int>(
                icon: Icons.update_rounded,
                title: 'Update playlists',
                subtitle: 'New channels appear and removed ones disappear automatically.',
                value: s.refreshHours,
                options: const [(3, '3 h'), (6, '6 h'), (24, 'Daily'), (0, 'Off')],
                onChanged: (v) {
                  s.refreshHours = v;
                  save();
                },
              ),
              _Choice<String>(
                icon: Icons.home_outlined,
                title: 'Start on',
                value: s.startPage,
                options: const [('home', 'Home'), ('live', 'Live TV')],
                onChanged: (v) {
                  s.startPage = v;
                  save();
                },
              ),
            ]),
            _Group(title: 'Your data', children: [
              _Action(icon: Icons.history_rounded, title: 'Clear watch history', subtitle: 'Recently watched and resume points.', onTap: () => _confirm(context, 'Clear watch history?', catalog.clearHistory)),
              _Action(icon: Icons.star_outline_rounded, title: 'Clear favourites', onTap: () => _confirm(context, 'Clear all favourites?', catalog.clearFavorites)),
            ]),
            _Group(title: 'About', children: [
              const ListTile(
                leading: NexonicLogo(size: 30),
                title: Text('Nexonic IPTV', style: TextStyle(fontWeight: FontWeight.w700)),
                subtitle: Text('Version $appVersion · Free and open source (MIT)'),
              ),
              const ListTile(
                leading: Icon(Icons.keyboard_outlined),
                title: Text('Keyboard and remote'),
                subtitle: Text('Space play/pause · F full screen · M mute · ↑/↓ change channel · 0–9 channel number · C channel list · A aspect · Esc back'),
              ),
              const ListTile(
                leading: Icon(Icons.public_rounded),
                title: Text('Website'),
                subtitle: SelectableText('shahrukhalid.github.io/nexonic-iptv'),
              ),
            ]),
          ]),
        ),
      ),
    ]);
  }

  Future<void> _confirm(BuildContext context, String title, Future<void> Function() action) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text(title),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Clear')),
        ],
      ),
    );
    if (ok == true) await action();
  }
}

class _Group extends StatelessWidget {
  const _Group({required this.title, required this.children});
  final String title;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 22),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Padding(padding: const EdgeInsets.fromLTRB(4, 0, 4, 10), child: Text(title.toUpperCase(), style: Theme.of(context).textTheme.labelSmall?.copyWith(color: textMuted))),
          Material(
            color: surface,
            clipBehavior: Clip.antiAlias,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(radiusL), side: const BorderSide(color: stroke)),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Column(children: [
              for (var i = 0; i < children.length; i++) ...[
                if (i > 0) const Divider(indent: 16, endIndent: 16),
                children[i],
              ],
            ]),
            ),
          ),
        ]),
      );
}

class _Toggle extends StatelessWidget {
  const _Toggle({required this.icon, required this.title, required this.value, required this.onChanged, this.subtitle});
  final IconData icon;
  final String title;
  final String? subtitle;
  final bool value;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) => SwitchListTile(
        secondary: Icon(icon),
        title: Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: subtitle == null ? null : Text(subtitle!),
        value: value,
        onChanged: onChanged,
      );
}

class _Choice<T> extends StatelessWidget {
  const _Choice({required this.icon, required this.title, required this.value, required this.options, required this.onChanged, this.subtitle});
  final IconData icon;
  final String title;
  final String? subtitle;
  final T value;
  final List<(T, String)> options;
  final ValueChanged<T> onChanged;

  @override
  Widget build(BuildContext context) {
    final narrow = MediaQuery.sizeOf(context).width < 600;
    final picker = SegmentedButton<T>(
      showSelectedIcon: false,
      segments: [for (final (v, l) in options) ButtonSegment(value: v, label: Text(l))],
      selected: {value},
      onSelectionChanged: (s) => onChanged(s.first),
    );
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      child: narrow
          ? Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [Icon(icon, color: textSecondary), const SizedBox(width: 16), Expanded(child: Text(title, style: const TextStyle(fontWeight: FontWeight.w600)))]),
              const SizedBox(height: 10),
              picker,
            ])
          : Row(children: [
              Icon(icon, color: textSecondary),
              const SizedBox(width: 16),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
                  if (subtitle != null) Text(subtitle!, style: Theme.of(context).textTheme.bodySmall),
                ]),
              ),
              const SizedBox(width: 12),
              picker,
            ]),
    );
  }
}

class _Action extends StatelessWidget {
  const _Action({required this.icon, required this.title, required this.onTap, this.subtitle});
  final IconData icon;
  final String title;
  final String? subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => ListTile(
        leading: Icon(icon),
        title: Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: subtitle == null ? null : Text(subtitle!),
        trailing: const Icon(Icons.chevron_right_rounded),
        onTap: onTap,
      );
}
