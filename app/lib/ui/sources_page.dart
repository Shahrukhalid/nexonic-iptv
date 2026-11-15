import 'dart:io';

import 'package:file_selector/file_selector.dart';
import 'package:flutter/material.dart';

import '../catalog.dart';
import '../sources.dart';
import 'theme.dart';
import 'widgets.dart';

/// Playlists: the free Nexonic channels plus the M3U links, M3U files and Xtream Codes logins the user adds.
class SourcesPage extends StatelessWidget {
  const SourcesPage({super.key, required this.catalog});
  final Catalog catalog;

  @override
  Widget build(BuildContext context) {
    final narrow = MediaQuery.sizeOf(context).width < 600;
    final pad = narrow ? 16.0 : 32.0;
    return ListView(padding: EdgeInsets.fromLTRB(0, 0, 0, 32), children: [
      PageHeader(
        title: 'Playlists',
        padding: pad,
        subtitle: narrow ? null : 'Watch the free Nexonic channels and your own IPTV playlists in one place.',
        actions: [
          if (!narrow)
            OutlinedButton.icon(
              icon: catalog.isBusy ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.sync_rounded, size: 18),
              label: const Text('Refresh all'),
              onPressed: catalog.isBusy ? null : catalog.refreshAll,
            ),
          const SizedBox(width: 10),
          FilledButton.icon(icon: const Icon(Icons.add_rounded), label: const Text('Add playlist'), onPressed: () => showSourceEditor(context, catalog)),
        ],
      ),
      Padding(
        padding: EdgeInsets.symmetric(horizontal: pad),
        child: Column(children: [
          for (final s in catalog.sources) Padding(padding: const EdgeInsets.only(bottom: 12), child: _SourceCard(catalog: catalog, source: s)),
          const SizedBox(height: 8),
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(color: surface.withValues(alpha: 0.6), borderRadius: BorderRadius.circular(radiusM), border: Border.all(color: stroke)),
            child: const Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Icon(Icons.shield_outlined, color: textSecondary, size: 20),
              SizedBox(width: 12),
              Expanded(
                child: Text(
                  'Nexonic IPTV is a player. It does not sell or provide playlists or logins other than the free Nexonic channels. '
                  'Add only playlists you are allowed to use. Logins are stored on this device only and are sent only to the server you enter.',
                  style: TextStyle(color: textSecondary, fontSize: 12.5, height: 1.45),
                ),
              ),
            ]),
          ),
        ]),
      ),
    ]);
  }
}

class _SourceCard extends StatelessWidget {
  const _SourceCard({required this.catalog, required this.source});
  final Catalog catalog;
  final Source source;

  IconData get _icon => switch (source.type) {
        SourceType.nexonic => Icons.verified_rounded,
        SourceType.m3u => Icons.link_rounded,
        SourceType.file => Icons.description_outlined,
        SourceType.xtream => Icons.dns_rounded,
      };

  @override
  Widget build(BuildContext context) {
    final s = source;
    final busy = catalog.busy.contains(s.id);
    final narrow = MediaQuery.sizeOf(context).width < 600;
    final counts = [
      for (final (k, l) in const [('live', 'channels'), ('movie', 'films'), ('series', 'series'), ('radio', 'stations'), ('media', 'videos')])
        if ((s.counts[k] ?? 0) > 0) '${compact(s.counts[k]!)} $l'
    ];
    final days = s.expires?.difference(DateTime.now()).inDays;
    return Opacity(
      opacity: s.enabled ? 1 : 0.6,
      child: Container(
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          color: surface,
          borderRadius: BorderRadius.circular(radiusL),
          border: Border.all(color: s.error != null && s.enabled ? live.withValues(alpha: 0.45) : stroke),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Container(
              width: 48,
              height: 48,
              decoration: BoxDecoration(
                gradient: s.isBuiltIn ? brandGradient : null,
                color: s.isBuiltIn ? null : surfaceHigh,
                borderRadius: BorderRadius.circular(radiusM),
              ),
              child: Icon(_icon, color: s.isBuiltIn ? Colors.white : accent),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Flexible(child: Text(s.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: Theme.of(context).textTheme.titleMedium)),
                  const SizedBox(width: 8),
                  Pill(s.isBuiltIn ? 'FREE' : s.type.label.toUpperCase(), foreground: s.isBuiltIn ? success : textSecondary),
                ]),
                const SizedBox(height: 4),
                Text(
                  s.isBuiltIn
                      ? 'Free-to-air channels, films, radio and open media, checked every day'
                      : (s.type == SourceType.file ? 'Imported file' : _host(s.url)),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ]),
            ),
            Switch(value: s.enabled, onChanged: (v) => catalog.setEnabled(s, v)),
          ]),
          const SizedBox(height: 14),
          Wrap(spacing: 8, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
            if (busy)
              const Pill('Updating…', icon: Icons.sync_rounded, foreground: accent)
            else if (s.error != null && s.enabled)
              Pill(s.error!, icon: Icons.error_outline_rounded, foreground: live)
            else
              s.lastSync == null
                  ? const Pill('Not loaded yet', icon: Icons.schedule_rounded)
                  : Pill('Updated ${ago(s.lastSync)}', icon: Icons.check_circle_outline_rounded, foreground: success),
            for (final c in counts) Pill(c),
            if (days != null) Pill(days < 0 ? 'Expired' : 'Expires in $days days', icon: Icons.event_outlined, foreground: days < 7 ? warning : textSecondary),
          ]),
          const SizedBox(height: 12),
          Row(children: [
            TextButton.icon(
              icon: const Icon(Icons.sync_rounded, size: 18),
              label: const Text('Refresh'),
              onPressed: busy || !s.enabled ? null : () => _refresh(context),
            ),
            if (!s.isBuiltIn) ...[
              TextButton.icon(icon: const Icon(Icons.edit_outlined, size: 18), label: const Text('Edit'), onPressed: () => showSourceEditor(context, catalog, existing: s)),
              const Spacer(),
              TextButton.icon(
                style: TextButton.styleFrom(foregroundColor: live),
                icon: const Icon(Icons.delete_outline_rounded, size: 18),
                label: Text(narrow ? 'Remove' : 'Remove playlist'),
                onPressed: () => _remove(context),
              ),
            ],
          ]),
        ]),
      ),
    );
  }

  static String _host(String url) => Uri.tryParse(url)?.host ?? url;

  Future<void> _refresh(BuildContext context) async {
    final messenger = ScaffoldMessenger.of(context);
    final err = await catalog.refreshSource(source.id);
    messenger.showSnackBar(SnackBar(content: Text(err ?? '${source.name} is up to date')));
  }

  Future<void> _remove(BuildContext context) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Remove playlist?'),
        content: Text('“${source.name}” and its saved login will be removed from this device. Favourites from it stay in My list.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
          FilledButton(style: FilledButton.styleFrom(backgroundColor: live, foregroundColor: Colors.white), onPressed: () => Navigator.pop(c, true), child: const Text('Remove')),
        ],
      ),
    );
    if (ok == true) await catalog.removeSource(source.id);
  }
}

/// Add or edit a playlist: Xtream Codes login, M3U link or M3U file, with an optional guide link and User-Agent.
Future<void> showSourceEditor(BuildContext context, Catalog catalog, {Source? existing}) => showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (_) => SourceEditor(catalog: catalog, existing: existing),
    );

class SourceEditor extends StatefulWidget {
  const SourceEditor({super.key, required this.catalog, this.existing, this.initialType});
  final Catalog catalog;
  final Source? existing;
  final SourceType? initialType;

  @override
  State<SourceEditor> createState() => _SourceEditorState();
}

class _SourceEditorState extends State<SourceEditor> {
  late SourceType type = widget.existing?.type ?? widget.initialType ?? SourceType.xtream;
  late final name = TextEditingController(text: widget.existing?.name ?? '');
  late final url = TextEditingController(text: widget.existing?.url ?? '');
  late final user = TextEditingController(text: widget.existing?.username ?? '');
  late final pass = TextEditingController(text: widget.existing?.password ?? '');
  late final epg = TextEditingController(text: widget.existing?.epgUrl ?? '');
  late final agent = TextEditingController(text: widget.existing?.userAgent ?? '');
  String? fileText;
  String? fileName;
  bool showPassword = false;
  bool working = false;
  String? error;

  bool get editing => widget.existing != null;

  @override
  void dispose() {
    for (final c in [name, url, user, pass, epg, agent]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _pickFile() async {
    try {
      final f = await openFile(
        acceptedTypeGroups: Platform.isAndroid
            ? const <XTypeGroup>[]
            : const [XTypeGroup(label: 'Playlists', extensions: ['m3u', 'm3u8', 'txt'])],
      );
      if (f == null) return;
      final text = await f.readAsString();
      setState(() {
        fileText = text;
        fileName = f.name;
        if (name.text.trim().isEmpty) name.text = f.name.replaceAll(RegExp(r'\.(m3u8?|txt)$', caseSensitive: false), '');
        error = null;
      });
    } catch (e) {
      setState(() => error = 'Could not read the file ($e).');
    }
  }

  /// A pasted provider link like `http://host/get.php?username=a&password=b` becomes an Xtream login.
  void _detectXtream(String v) {
    final u = Uri.tryParse(v.trim());
    if (type != SourceType.m3u || u == null) return;
    final q = u.queryParameters;
    if (u.path.endsWith('get.php') && (q['username'] ?? '').isNotEmpty && (q['password'] ?? '').isNotEmpty) {
      setState(() {
        type = SourceType.xtream;
        url.text = normaliseServer(v);
        user.text = q['username']!;
        pass.text = q['password']!;
      });
    }
  }

  String? _validate() {
    if (type == SourceType.xtream) {
      if (url.text.trim().isEmpty) return 'Enter the server address.';
      if (user.text.trim().isEmpty || pass.text.isEmpty) return 'Enter the username and password.';
    } else if (type == SourceType.m3u) {
      final u = Uri.tryParse(url.text.trim());
      if (u == null || !(u.scheme == 'http' || u.scheme == 'https') || u.host.isEmpty) return 'Enter a playlist link that starts with http:// or https://.';
    } else if (type == SourceType.file && fileText == null && !editing) {
      return 'Choose a playlist file.';
    }
    final e = epg.text.trim();
    if (e.isNotEmpty && !(e.startsWith('http://') || e.startsWith('https://'))) return 'The guide link must start with http:// or https://.';
    return null;
  }

  Future<void> _save() async {
    final problem = _validate();
    if (problem != null) {
      setState(() => error = problem);
      return;
    }
    setState(() {
      working = true;
      error = null;
    });
    final server = type == SourceType.xtream ? normaliseServer(url.text) : url.text.trim();
    final fallbackName = switch (type) {
      SourceType.xtream => Uri.tryParse(server)?.host ?? 'My IPTV',
      SourceType.m3u => Uri.tryParse(server)?.host ?? 'My playlist',
      _ => fileName ?? 'My playlist',
    };
    final title = name.text.trim().isEmpty ? fallbackName : name.text.trim();
    String? err;
    final existing = widget.existing;
    if (existing != null) {
      existing
        ..name = title
        ..url = type == SourceType.file ? existing.url : server
        ..username = user.text.trim()
        ..password = pass.text
        ..epgUrl = epg.text.trim()
        ..userAgent = agent.text.trim();
      err = await widget.catalog.updateSource(existing, fileText: fileText);
    } else {
      final s = Source(
        id: newSourceId(),
        type: type,
        name: title,
        url: type == SourceType.file ? '' : server,
        username: type == SourceType.xtream ? user.text.trim() : '',
        password: type == SourceType.xtream ? pass.text : '',
        epgUrl: epg.text.trim(),
        userAgent: agent.text.trim(),
      );
      err = await widget.catalog.addSource(s, fileText: fileText);
    }
    if (!mounted) return;
    if (err != null) {
      setState(() {
        working = false;
        error = err;
      });
      return;
    }
    final messenger = ScaffoldMessenger.of(context);
    Navigator.of(context).pop();
    messenger.showSnackBar(SnackBar(content: Text('$title ${editing ? 'updated' : 'added'}')));
  }

  @override
  Widget build(BuildContext context) {
    final narrow = MediaQuery.sizeOf(context).width < 600;
    final fields = <Widget>[
      if (!editing) ...[
        SegmentedButton<SourceType>(
          showSelectedIcon: false,
          segments: [
            ButtonSegment(value: SourceType.xtream, icon: const Icon(Icons.dns_outlined, size: 18), label: Text(narrow ? 'Xtream' : 'Xtream Codes')),
            const ButtonSegment(value: SourceType.m3u, icon: Icon(Icons.link_rounded, size: 18), label: Text('M3U link')),
            const ButtonSegment(value: SourceType.file, icon: Icon(Icons.upload_file_rounded, size: 18), label: Text('File')),
          ],
          selected: {type},
          onSelectionChanged: working ? null : (s) => setState(() {
                type = s.first;
                error = null;
              }),
        ),
        const SizedBox(height: 8),
        Text(
          switch (type) {
            SourceType.xtream => 'Sign in with the server address, username and password from your IPTV provider.',
            SourceType.m3u => 'Paste the address of an M3U or M3U8 playlist.',
            _ => 'Open an .m3u or .m3u8 playlist saved on this device.',
          },
          style: Theme.of(context).textTheme.bodySmall,
        ),
        const SizedBox(height: 18),
      ],
      TextField(controller: name, enabled: !working, decoration: const InputDecoration(labelText: 'Name (optional)', prefixIcon: Icon(Icons.label_outline_rounded))),
      const SizedBox(height: 12),
      if (type == SourceType.xtream) ...[
        TextField(
          controller: url,
          enabled: !working,
          keyboardType: TextInputType.url,
          decoration: const InputDecoration(labelText: 'Server address', hintText: 'http://example.com:8080', prefixIcon: Icon(Icons.dns_outlined)),
        ),
        const SizedBox(height: 12),
        TextField(controller: user, enabled: !working, autocorrect: false, decoration: const InputDecoration(labelText: 'Username', prefixIcon: Icon(Icons.person_outline_rounded))),
        const SizedBox(height: 12),
        TextField(
          controller: pass,
          enabled: !working,
          obscureText: !showPassword,
          autocorrect: false,
          enableSuggestions: false,
          decoration: InputDecoration(
            labelText: 'Password',
            prefixIcon: const Icon(Icons.lock_outline_rounded),
            suffixIcon: IconButton(
              tooltip: showPassword ? 'Hide' : 'Show',
              icon: Icon(showPassword ? Icons.visibility_off_outlined : Icons.visibility_outlined, size: 20),
              onPressed: () => setState(() => showPassword = !showPassword),
            ),
          ),
        ),
      ] else if (type == SourceType.m3u)
        TextField(
          controller: url,
          enabled: !working,
          keyboardType: TextInputType.url,
          onChanged: _detectXtream,
          decoration: const InputDecoration(labelText: 'Playlist link', hintText: 'https://example.com/playlist.m3u', prefixIcon: Icon(Icons.link_rounded)),
        )
      else
        OutlinedButton.icon(
          icon: const Icon(Icons.folder_open_rounded),
          label: Text(fileName ?? (editing ? 'Replace the file (optional)' : 'Choose a playlist file')),
          onPressed: working ? null : _pickFile,
        ),
      const SizedBox(height: 8),
      Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          tilePadding: EdgeInsets.zero,
          childrenPadding: EdgeInsets.zero,
          initiallyExpanded: epg.text.isNotEmpty || agent.text.isNotEmpty,
          title: const Text('Advanced', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
          subtitle: const Text('TV guide link and User-Agent', style: TextStyle(fontSize: 12, color: textMuted)),
          children: [
            const SizedBox(height: 4),
            TextField(
              controller: epg,
              enabled: !working,
              keyboardType: TextInputType.url,
              decoration: InputDecoration(
                labelText: 'TV guide (XMLTV / EPG) link',
                helperText: type == SourceType.xtream ? 'Optional: the provider\'s own guide is used when empty.' : 'Optional: the playlist\'s own guide link is used when empty.',
                prefixIcon: const Icon(Icons.calendar_view_week_outlined),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: agent,
              enabled: !working,
              decoration: const InputDecoration(labelText: 'User-Agent (optional)', helperText: 'Only if your provider asks for one.', prefixIcon: Icon(Icons.badge_outlined)),
            ),
            const SizedBox(height: 4),
          ],
        ),
      ),
      if (error != null) ...[
        const SizedBox(height: 12),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(color: live.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(radiusS), border: Border.all(color: live.withValues(alpha: 0.4))),
          child: Row(children: [
            const Icon(Icons.error_outline_rounded, color: live, size: 20),
            const SizedBox(width: 10),
            Expanded(child: Text(error!, style: const TextStyle(color: textPrimary))),
          ]),
        ),
      ],
    ];
    return Dialog(
      insetPadding: EdgeInsets.all(narrow ? 12 : 24),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520),
        child: Padding(
          padding: EdgeInsets.all(narrow ? 18 : 26),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(children: [
              Container(
                width: 40,
                height: 40,
                decoration: BoxDecoration(gradient: brandGradient, borderRadius: BorderRadius.circular(radiusS)),
                child: const Icon(Icons.playlist_add_rounded, color: Colors.white),
              ),
              const SizedBox(width: 12),
              Expanded(child: Text(editing ? 'Edit playlist' : 'Add a playlist', style: Theme.of(context).textTheme.titleLarge)),
              IconButton(icon: const Icon(Icons.close_rounded), onPressed: working ? null : () => Navigator.of(context).pop()),
            ]),
            const SizedBox(height: 20),
            Flexible(child: SingleChildScrollView(child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: fields))),
            const SizedBox(height: 20),
            Row(mainAxisAlignment: MainAxisAlignment.end, children: [
              TextButton(onPressed: working ? null : () => Navigator.of(context).pop(), child: const Text('Cancel')),
              const SizedBox(width: 8),
              FilledButton.icon(
                icon: working
                    ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Color(0xFF00141A)))
                    : Icon(type == SourceType.xtream ? Icons.login_rounded : Icons.check_rounded, size: 18),
                label: Text(working ? 'Loading…' : (editing ? 'Save' : (type == SourceType.xtream ? 'Sign in' : 'Add playlist'))),
                onPressed: working ? null : _save,
              ),
            ]),
          ]),
        ),
      ),
    );
  }
}
