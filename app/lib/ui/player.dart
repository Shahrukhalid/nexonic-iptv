import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:media_kit/media_kit.dart';
import 'package:media_kit_video/media_kit_video.dart';

import '../catalog.dart';
import '../m3u.dart';
import 'theme.dart';
import 'widgets.dart';

/// Video output settings shared by the player and the CI self-test. Hardware decoding follows the setting, except on
/// macOS where it stays off by default (the zero-copy path crashed on the test machines).
VideoControllerConfiguration get videoConfiguration =>
    VideoControllerConfiguration(enableHardwareAcceleration: !Platform.isMacOS);

VideoControllerConfiguration videoConfigurationFor(bool hardware) =>
    VideoControllerConfiguration(enableHardwareAcceleration: hardware);

Media mediaFor(Channel c) => Media(c.url, httpHeaders: c.headers.isEmpty ? null : c.headers);

/// Opens the full-screen player on item [index] of [list].
Future<void> openPlayer(BuildContext context, Catalog catalog, List<Channel> list, int index) {
  final playable = [for (final c in list) if (!c.opensSeries) c];
  final i = playable.indexOf(list[index]);
  return Navigator.of(context).push(PageRouteBuilder<void>(
    pageBuilder: (_, __, ___) => PlayerScreen(catalog: catalog, list: playable, index: i < 0 ? 0 : i),
    transitionsBuilder: (_, a, __, child) => FadeTransition(opacity: a, child: child),
    transitionDuration: const Duration(milliseconds: 220),
  ));
}

/// Playback state shared by the windowed and the full-screen view of the player.
class PlayerSession extends ChangeNotifier {
  PlayerSession(this.catalog, this.list, this.index)
      : player = Player(configuration: PlayerConfiguration(bufferSize: catalog.settings.bufferMb * 1024 * 1024)) {
    controller = VideoController(player, configuration: videoConfigurationFor(catalog.settings.hardwareDecoding));
    _subs
      ..add(player.stream.buffering.listen((b) {
        buffering = b;
        _stall?.cancel();
        // A stream that keeps buffering for 30 s is treated as broken and reopened.
        if (b) _stall = Timer(const Duration(seconds: 30), () => _fail('The stream stopped sending data.'));
        notifyListeners();
      }))
      ..add(player.stream.playing.listen((p) {
        if (p && failure == null) retries = 0;
        notifyListeners();
      }))
      ..add(player.stream.width.listen((w) {
        hasVideo = (w ?? 0) > 0;
        notifyListeners();
      }))
      ..add(player.stream.error.listen(_fail))
      ..add(player.stream.duration.listen(_maybeResume))
      ..add(player.stream.position.listen(_saveProgress))
      ..add(player.stream.completed.listen((done) {
        if (!done) return;
        if (channel.isLive) {
          _fail('The stream ended.'); // live streams should not end: reopen them
        } else {
          catalog.setProgress(channel, Duration.zero, Duration.zero);
        }
      }));
    play();
  }

  static const maxRetries = 3;

  final Catalog catalog;
  final List<Channel> list;
  int index;
  final Player player;
  late final VideoController controller;
  final _subs = <StreamSubscription<dynamic>>[];
  bool buffering = true;
  bool hasVideo = false;
  String? failure;
  int retries = 0;
  BoxFit fit = BoxFit.contain;
  DateTime switchedAt = DateTime.now();
  Timer? _retry;
  Timer? _stall;
  bool _resumed = false;
  DateTime _lastSave = DateTime.fromMillisecondsSinceEpoch(0);
  bool _disposed = false;

  Channel get channel => list[index];

  void play() {
    _retry?.cancel();
    _stall?.cancel();
    failure = null;
    buffering = true;
    hasVideo = false;
    _resumed = false;
    switchedAt = DateTime.now();
    final c = channel;
    // After the current frame: pages listening to the catalogue must not rebuild during this build.
    Future.microtask(() => catalog.watched(c));
    player.open(mediaFor(c));
    notifyListeners();
  }

  void _maybeResume(Duration d) {
    if (_resumed || d <= Duration.zero || channel.isLive || !catalog.settings.resume) return;
    _resumed = true;
    final r = catalog.resume[channel.key];
    if (r != null && r.position < d - const Duration(minutes: 1)) player.seek(r.position);
  }

  void _saveProgress(Duration p) {
    if (channel.isLive || DateTime.now().difference(_lastSave) < const Duration(seconds: 10)) return;
    _lastSave = DateTime.now();
    catalog.setProgress(channel, p, player.state.duration);
  }

  void _fail(String why) {
    if (_disposed || failure != null || (_retry?.isActive ?? false)) return;
    _stall?.cancel();
    if (retries < maxRetries) {
      retries++;
      buffering = true;
      _retry = Timer(Duration(seconds: 2 << retries), () {
        if (!_disposed) player.open(mediaFor(channel));
      });
      notifyListeners();
      return;
    }
    catalog.markFailing(channel);
    failure = why;
    buffering = false;
    notifyListeners();
  }

  void retry() {
    retries = 0;
    play();
  }

  void step(int delta) {
    if (list.length < 2) return;
    _saveNow();
    index = (index + delta) % list.length;
    if (index < 0) index += list.length;
    retries = 0;
    play();
  }

  void jumpTo(int i) {
    if (i < 0 || i >= list.length || i == index) return;
    _saveNow();
    index = i;
    retries = 0;
    play();
  }

  /// Switches to the live channel with this number, if there is one.
  bool jumpToNumber(int n) {
    final i = list.indexWhere((c) => c.number == n);
    if (i < 0) return false;
    jumpTo(i);
    return true;
  }

  Future<void> toggleMute() async {
    await player.setVolume(player.state.volume > 0 ? 0 : 100);
    notifyListeners();
  }

  void cycleFit(VideoState? v) {
    fit = switch (fit) { BoxFit.contain => BoxFit.cover, BoxFit.cover => BoxFit.fill, _ => BoxFit.contain };
    v?.update(fit: fit);
    notifyListeners();
  }

  void _saveNow() {
    if (!channel.isLive) catalog.setProgress(channel, player.state.position, player.state.duration);
  }

  @override
  void notifyListeners() {
    if (!_disposed) super.notifyListeners();
  }

  @override
  void dispose() {
    _saveNow();
    _disposed = true;
    _retry?.cancel();
    _stall?.cancel();
    for (final s in _subs) {
      s.cancel();
    }
    player.dispose();
    super.dispose();
  }
}

class PlayerScreen extends StatefulWidget {
  const PlayerScreen({super.key, required this.catalog, required this.list, required this.index});
  final Catalog catalog;
  final List<Channel> list;
  final int index;

  @override
  State<PlayerScreen> createState() => _PlayerScreenState();
}

class _PlayerScreenState extends State<PlayerScreen> {
  late final session = PlayerSession(widget.catalog, widget.list, widget.index);
  final videoKey = GlobalKey<VideoState>();

  @override
  void dispose() {
    session.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: Colors.black,
        body: Video(
          key: videoKey,
          controller: session.controller,
          fill: Colors.black,
          controls: (state) => PlayerOverlay(session: session, state: state),
        ),
      );
}

/// Controls drawn over the video (in the window and in full screen).
///
/// Keys: Space play/pause · F full screen · M mute · ↑/↓ or Page Up/Down change channel · ←/→ seek (films)
/// · C channel list · A aspect · 0-9 channel number · Esc back.
class PlayerOverlay extends StatefulWidget {
  const PlayerOverlay({super.key, required this.session, required this.state});
  final PlayerSession session;
  final VideoState state;

  @override
  State<PlayerOverlay> createState() => _PlayerOverlayState();
}

class _PlayerOverlayState extends State<PlayerOverlay> {
  PlayerSession get s => widget.session;
  Player get player => s.player;

  bool visible = true;
  bool channels = false;
  Timer? _hide;
  String digits = '';
  Timer? _digitTimer;
  Duration position = Duration.zero;
  Duration total = Duration.zero;
  double? dragging;
  final _subs = <StreamSubscription<dynamic>>[];
  final focus = FocusNode();

  @override
  void initState() {
    super.initState();
    s.addListener(_onSession);
    _subs
      ..add(player.stream.position.listen((p) {
        if (mounted && dragging == null && (p - position).abs() >= const Duration(milliseconds: 500)) setState(() => position = p);
      }))
      ..add(player.stream.duration.listen((d) {
        if (mounted) setState(() => total = d);
      }))
      ..add(player.stream.playing.listen((_) {
        if (mounted) setState(() {});
      }))
      ..add(player.stream.volume.listen((_) {
        if (mounted) setState(() {});
      }));
    _poke();
  }

  @override
  void dispose() {
    s.removeListener(_onSession);
    _hide?.cancel();
    _digitTimer?.cancel();
    for (final x in _subs) {
      x.cancel();
    }
    focus.dispose();
    super.dispose();
  }

  void _onSession() {
    if (mounted) setState(() {});
  }

  /// Shows the controls and hides them again after a few seconds without input.
  void _poke() {
    _hide?.cancel();
    if (!visible) setState(() => visible = true);
    _hide = Timer(const Duration(seconds: 4), () {
      if (mounted && !channels && player.state.playing) setState(() => visible = false);
    });
  }

  void _back() {
    if (channels) {
      setState(() => channels = false);
    } else if (widget.state.isFullscreen()) {
      widget.state.exitFullscreen();
    } else {
      Navigator.of(context).maybePop();
    }
  }

  void _digit(int d) {
    if (!s.channel.isLive) return;
    _digitTimer?.cancel();
    setState(() => digits = (digits + '$d').characters.takeLast(4).toString());
    _digitTimer = Timer(const Duration(milliseconds: 1300), () {
      final n = int.tryParse(digits) ?? 0;
      if (mounted) setState(() => digits = '');
      if (n > 0 && !s.jumpToNumber(n) && mounted) {
        ScaffoldMessenger.maybeOf(context)?.showSnackBar(SnackBar(content: Text('No channel number $n')));
      }
    });
  }

  void _seekBy(int seconds) {
    if (s.channel.isLive || total <= Duration.zero) return;
    final t = player.state.position + Duration(seconds: seconds);
    player.seek(t < Duration.zero ? Duration.zero : (t > total ? total : t));
    _poke();
  }

  KeyEventResult _onKey(FocusNode _, KeyEvent e) {
    if (e is! KeyDownEvent && e is! KeyRepeatEvent) return KeyEventResult.ignored;
    final k = e.logicalKey;
    _poke();
    final live = s.channel.isLive;
    final digit = {
      LogicalKeyboardKey.digit0: 0, LogicalKeyboardKey.digit1: 1, LogicalKeyboardKey.digit2: 2, LogicalKeyboardKey.digit3: 3,
      LogicalKeyboardKey.digit4: 4, LogicalKeyboardKey.digit5: 5, LogicalKeyboardKey.digit6: 6, LogicalKeyboardKey.digit7: 7,
      LogicalKeyboardKey.digit8: 8, LogicalKeyboardKey.digit9: 9, LogicalKeyboardKey.numpad0: 0, LogicalKeyboardKey.numpad1: 1,
      LogicalKeyboardKey.numpad2: 2, LogicalKeyboardKey.numpad3: 3, LogicalKeyboardKey.numpad4: 4, LogicalKeyboardKey.numpad5: 5,
      LogicalKeyboardKey.numpad6: 6, LogicalKeyboardKey.numpad7: 7, LogicalKeyboardKey.numpad8: 8, LogicalKeyboardKey.numpad9: 9,
    }[k];
    if (digit != null) {
      _digit(digit);
      return KeyEventResult.handled;
    }
    if (channels && (k == LogicalKeyboardKey.arrowUp || k == LogicalKeyboardKey.arrowDown)) return KeyEventResult.ignored;
    if (k == LogicalKeyboardKey.space || k == LogicalKeyboardKey.mediaPlayPause) {
      player.playOrPause();
    } else if (k == LogicalKeyboardKey.keyF) {
      widget.state.toggleFullscreen();
    } else if (k == LogicalKeyboardKey.keyM) {
      s.toggleMute();
    } else if (k == LogicalKeyboardKey.keyC && live) {
      setState(() => channels = !channels);
    } else if (k == LogicalKeyboardKey.keyA) {
      s.cycleFit(widget.state);
    } else if (k == LogicalKeyboardKey.pageUp || k == LogicalKeyboardKey.channelUp || k == LogicalKeyboardKey.keyP ||
        (live && k == LogicalKeyboardKey.arrowUp)) {
      s.step(-1);
    } else if (k == LogicalKeyboardKey.pageDown || k == LogicalKeyboardKey.channelDown || k == LogicalKeyboardKey.keyN ||
        (live && k == LogicalKeyboardKey.arrowDown)) {
      s.step(1);
    } else if (!live && k == LogicalKeyboardKey.arrowLeft) {
      _seekBy(-10);
    } else if (!live && k == LogicalKeyboardKey.arrowRight) {
      _seekBy(10);
    } else if (k == LogicalKeyboardKey.escape || k == LogicalKeyboardKey.goBack || k == LogicalKeyboardKey.browserBack) {
      _back();
    } else {
      return KeyEventResult.ignored;
    }
    return KeyEventResult.handled;
  }

  @override
  Widget build(BuildContext context) {
    final c = s.channel;
    final wide = MediaQuery.sizeOf(context).width >= 700;
    return Focus(
      focusNode: focus,
      autofocus: true,
      onKeyEvent: _onKey,
      child: MouseRegion(
        onHover: (_) => _poke(),
        cursor: visible ? SystemMouseCursors.basic : SystemMouseCursors.none,
        child: Stack(fit: StackFit.expand, children: [
          GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: () {
              if (visible && !channels) {
                _hide?.cancel();
                setState(() => visible = false);
              } else {
                _poke();
              }
            },
            onDoubleTap: () => widget.state.toggleFullscreen(),
            onHorizontalDragEnd: (d) {
              final v = d.primaryVelocity ?? 0;
              if (c.isLive && v.abs() > 600) s.step(v < 0 ? 1 : -1);
            },
          ),
          if (!s.hasVideo && s.failure == null) IgnorePointer(child: _stage(c)),
          if (s.buffering && s.failure == null) IgnorePointer(child: _buffering()),
          if (s.failure != null) _failure(),
          Positioned(left: 24, top: 24, child: IgnorePointer(child: _zapToast(c))),
          IgnorePointer(
            ignoring: !visible,
            child: AnimatedOpacity(
              opacity: visible ? 1 : 0,
              duration: const Duration(milliseconds: 220),
              child: Stack(fit: StackFit.expand, children: [
                Align(alignment: Alignment.topCenter, child: _top(c, wide)),
                Align(alignment: Alignment.bottomCenter, child: _bottom(c, wide)),
              ]),
            ),
          ),
          AnimatedPositioned(
            duration: const Duration(milliseconds: 240),
            curve: Curves.easeOutCubic,
            top: 0,
            bottom: 0,
            right: channels ? 0 : -380,
            width: wide ? 360 : MediaQuery.sizeOf(context).width * 0.86,
            child: _channelDrawer(),
          ),
        ]),
      ),
    );
  }

  Widget _stage(Channel c) => Container(
        decoration: BoxDecoration(
          gradient: RadialGradient(colors: [tintFor(c.name).$1.withValues(alpha: 0.25), Colors.black], radius: 1.1),
        ),
        child: Center(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            ChannelLogo(c, size: 140, radius: radiusL),
            const SizedBox(height: 18),
            Text(c.name, style: Theme.of(context).textTheme.headlineSmall),
            if (c.isRadio && !s.buffering) ...[
              const SizedBox(height: 8),
              const Row(mainAxisSize: MainAxisSize.min, children: [
                Icon(Icons.graphic_eq_rounded, color: accent),
                SizedBox(width: 6),
                Text('Playing radio', style: TextStyle(color: textSecondary)),
              ]),
            ],
          ]),
        ),
      );

  Widget _buffering() => Center(
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
          margin: const EdgeInsets.only(top: 260),
          decoration: BoxDecoration(color: Colors.black54, borderRadius: BorderRadius.circular(radiusM)),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2.4)),
            const SizedBox(width: 12),
            Text(s.retries > 0 ? 'Reconnecting… (${s.retries}/${PlayerSession.maxRetries})' : 'Connecting…',
                style: const TextStyle(fontWeight: FontWeight.w600)),
          ]),
        ),
      );

  Widget _zapToast(Channel c) {
    final recent = DateTime.now().difference(s.switchedAt) < const Duration(seconds: 3);
    final show = digits.isNotEmpty || (recent && !visible);
    return AnimatedOpacity(
      opacity: show ? 1 : 0,
      duration: const Duration(milliseconds: 200),
      child: Container(
        padding: const EdgeInsets.fromLTRB(14, 10, 18, 10),
        decoration: BoxDecoration(color: const Color(0xCC0A101D), borderRadius: BorderRadius.circular(radiusM), border: Border.all(color: stroke)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Text(digits.isNotEmpty ? digits : (c.number > 0 ? '${c.number}' : ''),
              style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w800, color: accent)),
          if (digits.isEmpty) ...[const SizedBox(width: 12), ChannelLogo(c, size: 32), const SizedBox(width: 10), Text(c.name, style: Theme.of(context).textTheme.titleMedium)],
        ]),
      ),
    );
  }

  Widget _top(Channel c, bool wide) {
    final (now, next) = s.catalog.nowNext(c);
    final fav = s.catalog.isFavorite(c);
    return Container(
      padding: EdgeInsets.fromLTRB(12, MediaQuery.paddingOf(context).top + 10, 12, 36),
      decoration: const BoxDecoration(
        gradient: LinearGradient(begin: Alignment.topCenter, end: Alignment.bottomCenter, colors: [Color(0xE6000000), Colors.transparent]),
      ),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        IconButton(tooltip: 'Back (Esc)', icon: const Icon(Icons.arrow_back_rounded), onPressed: _back),
        const SizedBox(width: 6),
        ChannelLogo(c, size: 44),
        const SizedBox(width: 12),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              if (c.isLive) ...[const LiveBadge(small: true), const SizedBox(width: 8)],
              if (c.number > 0) ...[Text('${c.number}', style: const TextStyle(color: accent, fontWeight: FontWeight.w800)), const SizedBox(width: 8)],
              Flexible(child: Text(c.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: Theme.of(context).textTheme.titleLarge)),
            ]),
            const SizedBox(height: 4),
            if (now != null)
              Text('${clock(now.start)}–${clock(now.stop)}  ${now.title}', maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: textPrimary))
            else
              Text(c.group.isNotEmpty ? c.group : (c.isLive ? 'Live' : ''), maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: textSecondary)),
            if (next != null && wide)
              Text('Next  ${clock(next.start)}  ${next.title}', maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: textSecondary, fontSize: 12.5)),
            if (now != null) ...[const SizedBox(height: 6), SizedBox(width: 240, child: ProgressLine(now.progress(DateTime.now().toUtc())))],
          ]),
        ),
        IconButton(
          tooltip: fav ? 'Remove from favourites' : 'Add to favourites',
          icon: Icon(fav ? Icons.star_rounded : Icons.star_outline_rounded, color: fav ? gold : null),
          onPressed: () => setState(() => s.catalog.toggleFavorite(c)),
        ),
        _tracksMenu(),
        if (c.isLive && s.list.length > 1)
          IconButton(tooltip: 'Channels (C)', icon: const Icon(Icons.format_list_bulleted_rounded), onPressed: () => setState(() => channels = !channels)),
      ]),
    );
  }

  Widget _tracksMenu() {
    final tracks = player.state.tracks;
    final audio = tracks.audio.where((t) => t.id != 'auto' && t.id != 'no').toList();
    final subs = tracks.subtitle.where((t) => t.id != 'auto' && t.id != 'no').toList();
    if (audio.length < 2 && subs.isEmpty) return const SizedBox.shrink();
    String label(dynamic t, int i) {
      final parts = [t.title, t.language].whereType<String>().where((x) => x.isNotEmpty).toList();
      return parts.isEmpty ? 'Track ${i + 1}' : parts.join(' · ');
    }

    return PopupMenuButton<VoidCallback>(
      tooltip: 'Audio and subtitles',
      icon: const Icon(Icons.subtitles_outlined),
      onSelected: (f) => f(),
      itemBuilder: (_) => [
        if (audio.length > 1) ...[
          const PopupMenuItem(enabled: false, child: Text('AUDIO', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w800))),
          for (var i = 0; i < audio.length; i++)
            CheckedPopupMenuItem(
              value: () => player.setAudioTrack(audio[i]),
              checked: player.state.track.audio.id == audio[i].id,
              child: Text(label(audio[i], i)),
            ),
        ],
        if (subs.isNotEmpty) ...[
          const PopupMenuItem(enabled: false, child: Text('SUBTITLES', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w800))),
          CheckedPopupMenuItem(
            value: () => player.setSubtitleTrack(SubtitleTrack.no()),
            checked: player.state.track.subtitle.id == 'no',
            child: const Text('Off'),
          ),
          for (var i = 0; i < subs.length; i++)
            CheckedPopupMenuItem(
              value: () => player.setSubtitleTrack(subs[i]),
              checked: player.state.track.subtitle.id == subs[i].id,
              child: Text(label(subs[i], i)),
            ),
        ],
      ],
    );
  }

  Widget _bottom(Channel c, bool wide) {
    final playing = player.state.playing;
    final muted = player.state.volume == 0;
    final fitIcon = switch (s.fit) { BoxFit.cover => Icons.crop_rounded, BoxFit.fill => Icons.aspect_ratio_rounded, _ => Icons.fit_screen_rounded };
    final pos = dragging != null ? Duration(milliseconds: (dragging! * total.inMilliseconds).round()) : position;
    return Container(
      padding: EdgeInsets.fromLTRB(16, 40, 16, MediaQuery.paddingOf(context).bottom + 12),
      decoration: const BoxDecoration(
        gradient: LinearGradient(begin: Alignment.bottomCenter, end: Alignment.topCenter, colors: [Color(0xE6000000), Colors.transparent]),
      ),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        if (!c.isLive && total > Duration.zero)
          Row(children: [
            Text(duration(pos), style: const TextStyle(fontSize: 12, color: textSecondary)),
            Expanded(
              child: Slider(
                value: (total.inMilliseconds == 0 ? 0.0 : pos.inMilliseconds / total.inMilliseconds).clamp(0.0, 1.0),
                onChanged: (v) => setState(() => dragging = v),
                onChangeEnd: (v) {
                  player.seek(Duration(milliseconds: (v * total.inMilliseconds).round()));
                  setState(() => dragging = null);
                },
              ),
            ),
            Text(duration(total), style: const TextStyle(fontSize: 12, color: textSecondary)),
          ]),
        Row(children: [
          if (c.isLive && s.list.length > 1) _btn(Icons.skip_previous_rounded, 'Previous channel', () => s.step(-1)),
          if (!c.isLive) _btn(Icons.replay_10_rounded, 'Back 10 s (←)', () => _seekBy(-10)),
          const SizedBox(width: 4),
          _playButton(playing),
          const SizedBox(width: 4),
          if (!c.isLive) _btn(Icons.forward_10_rounded, 'Forward 10 s (→)', () => _seekBy(10)),
          if (c.isLive && s.list.length > 1) _btn(Icons.skip_next_rounded, 'Next channel', () => s.step(1)),
          const SizedBox(width: 8),
          _btn(muted ? Icons.volume_off_rounded : Icons.volume_up_rounded, 'Mute (M)', s.toggleMute),
          if (wide)
            SizedBox(
              width: 120,
              child: Slider(value: (player.state.volume / 100).clamp(0.0, 1.0), onChanged: (v) => player.setVolume(v * 100)),
            ),
          const Spacer(),
          if (wide && c.isLive && s.list.length > 1)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: Text('${s.index + 1} / ${s.list.length}', style: const TextStyle(color: textMuted, fontSize: 12)),
            ),
          _btn(fitIcon, 'Aspect: ${s.fit == BoxFit.contain ? 'fit' : s.fit == BoxFit.cover ? 'zoom' : 'stretch'} (A)', () => s.cycleFit(widget.state)),
          _btn(widget.state.isFullscreen() ? Icons.fullscreen_exit_rounded : Icons.fullscreen_rounded, 'Full screen (F)',
              () => widget.state.toggleFullscreen()),
        ]),
      ]),
    );
  }

  Widget _btn(IconData icon, String tip, VoidCallback onTap) => IconButton(tooltip: tip, iconSize: 26, icon: Icon(icon), onPressed: () {
        onTap();
        _poke();
      });

  Widget _playButton(bool playing) => Material(
        color: Colors.white,
        shape: const CircleBorder(),
        child: InkWell(
          customBorder: const CircleBorder(),
          onTap: () {
            player.playOrPause();
            _poke();
          },
          child: Padding(
            padding: const EdgeInsets.all(10),
            child: Icon(playing ? Icons.pause_rounded : Icons.play_arrow_rounded, color: Colors.black, size: 28),
          ),
        ),
      );

  Widget _failure() => Center(
        child: Container(
          constraints: const BoxConstraints(maxWidth: 400),
          padding: const EdgeInsets.all(24),
          decoration: BoxDecoration(color: const Color(0xF20A101D), borderRadius: BorderRadius.circular(radiusL), border: Border.all(color: stroke)),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Icon(Icons.wifi_tethering_error_rounded, size: 40, color: warning),
            const SizedBox(height: 12),
            Text('This stream is not working right now', textAlign: TextAlign.center, style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 6),
            Text('${s.failure}', textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodyMedium),
            const SizedBox(height: 18),
            Wrap(spacing: 10, runSpacing: 10, alignment: WrapAlignment.center, children: [
              OutlinedButton.icon(icon: const Icon(Icons.refresh_rounded), label: const Text('Try again'), onPressed: s.retry),
              if (s.list.length > 1)
                FilledButton.icon(icon: const Icon(Icons.skip_next_rounded), label: Text(s.channel.isLive ? 'Next channel' : 'Next'), onPressed: () => s.step(1)),
            ]),
          ]),
        ),
      );

  Widget _channelDrawer() => _ChannelDrawer(
        session: s,
        onPick: (i) {
          s.jumpTo(i);
          _poke();
        },
        onClose: () => setState(() => channels = false),
      );
}

class _ChannelDrawer extends StatefulWidget {
  const _ChannelDrawer({required this.session, required this.onPick, required this.onClose});
  final PlayerSession session;
  final ValueChanged<int> onPick;
  final VoidCallback onClose;

  @override
  State<_ChannelDrawer> createState() => _ChannelDrawerState();
}

class _ChannelDrawerState extends State<_ChannelDrawer> {
  String query = '';

  @override
  Widget build(BuildContext context) {
    final s = widget.session;
    final q = query.toLowerCase();
    final shown = [for (var i = 0; i < s.list.length; i++) if (q.isEmpty || s.list[i].name.toLowerCase().contains(q)) i];
    return Container(
      decoration: const BoxDecoration(color: Color(0xF00A101D), border: Border(left: BorderSide(color: stroke))),
      padding: EdgeInsets.only(top: MediaQuery.paddingOf(context).top),
      child: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 14, 8, 8),
          child: Row(children: [
            Text('Channels', style: Theme.of(context).textTheme.titleLarge),
            const Spacer(),
            IconButton(icon: const Icon(Icons.close_rounded), onPressed: widget.onClose),
          ]),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12),
          child: SearchField(hint: 'Find a channel', onChanged: (v) => setState(() => query = v)),
        ),
        const SizedBox(height: 8),
        Expanded(
          child: ListView.builder(
            itemExtent: 62,
            itemCount: shown.length,
            itemBuilder: (_, j) {
              final i = shown[j];
              final c = s.list[i];
              final on = i == s.index;
              final (now, _) = s.catalog.nowNext(c);
              return InkWell(
                onTap: () => widget.onPick(i),
                child: Container(
                  margin: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  decoration: BoxDecoration(
                    color: on ? accent.withValues(alpha: 0.14) : Colors.transparent,
                    borderRadius: BorderRadius.circular(radiusS),
                    border: Border.all(color: on ? accent.withValues(alpha: 0.4) : Colors.transparent),
                  ),
                  child: Row(children: [
                    SizedBox(width: 34, child: Text(c.number > 0 ? '${c.number}' : '', style: TextStyle(color: on ? accent : textMuted, fontWeight: FontWeight.w700, fontSize: 12))),
                    ChannelLogo(c, size: 38),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text(c.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontWeight: FontWeight.w600, color: on ? accent : textPrimary)),
                        if (now != null) Text(now.title, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 12, color: textSecondary)),
                      ]),
                    ),
                    if (on) const Icon(Icons.equalizer_rounded, color: accent, size: 18),
                  ]),
                ),
              );
            },
          ),
        ),
      ]),
    );
  }
}

/// A small embedded player for the Live TV preview panel.
class PreviewPlayer extends StatefulWidget {
  const PreviewPlayer({super.key, required this.catalog, required this.channel});
  final Catalog catalog;
  final Channel channel;

  @override
  State<PreviewPlayer> createState() => PreviewPlayerState();
}

class PreviewPlayerState extends State<PreviewPlayer> {
  late final Player player = Player(configuration: PlayerConfiguration(bufferSize: widget.catalog.settings.bufferMb * 1024 * 1024));
  late final VideoController controller = VideoController(player, configuration: videoConfigurationFor(widget.catalog.settings.hardwareDecoding));
  final _subs = <StreamSubscription<dynamic>>[];
  bool buffering = true;
  bool hasVideo = false;
  bool failed = false;
  bool muted = false;

  @override
  void initState() {
    super.initState();
    _subs
      ..add(player.stream.buffering.listen((b) {
        if (mounted) setState(() => buffering = b);
      }))
      ..add(player.stream.width.listen((w) {
        if (mounted) setState(() => hasVideo = (w ?? 0) > 0);
      }))
      ..add(player.stream.error.listen((_) {
        if (mounted) setState(() => failed = true);
      }));
    _open();
  }

  @override
  void didUpdateWidget(PreviewPlayer old) {
    super.didUpdateWidget(old);
    if (old.channel.key != widget.channel.key) _open();
  }

  void _open() {
    setState(() {
      buffering = true;
      hasVideo = false;
      failed = false;
    });
    player.open(mediaFor(widget.channel));
  }

  /// Stops sound and network use while the full-screen player is open.
  Future<void> pause() => player.stop();
  void resume() => _open();

  Future<void> toggleMute() async {
    muted = !muted;
    await player.setVolume(muted ? 0 : 100);
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    for (final s in _subs) {
      s.cancel();
    }
    player.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Stack(fit: StackFit.expand, children: [
        const ColoredBox(color: Colors.black),
        Video(controller: controller, controls: NoVideoControls, fill: Colors.black),
        if (!hasVideo)
          Center(child: Opacity(opacity: 0.9, child: ChannelLogo(widget.channel, size: 84, radius: radiusM))),
        if (buffering && !failed)
          const Positioned(right: 12, bottom: 12, child: SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2.2))),
        if (failed)
          const Positioned(left: 12, bottom: 12, child: Pill('Not available right now', icon: Icons.error_outline_rounded, foreground: warning)),
        Positioned(
          right: 6,
          top: 6,
          child: IconButton(
            tooltip: muted ? 'Unmute' : 'Mute',
            icon: Icon(muted ? Icons.volume_off_rounded : Icons.volume_up_rounded, size: 20),
            onPressed: toggleMute,
          ),
        ),
      ]);
}
