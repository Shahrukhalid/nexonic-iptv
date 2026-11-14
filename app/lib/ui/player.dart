import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:media_kit/media_kit.dart';
import 'package:media_kit_video/media_kit_video.dart';

import '../catalog.dart';
import '../m3u.dart';
import 'theme.dart';
import 'widgets.dart';

/// Full-screen capable player for live channels, films and radio, with automatic recovery.
///
/// Keys: Space play/pause · F fullscreen · M mute · Page Up/P previous · Page Down/N next · Esc back.
class PlayerScreen extends StatefulWidget {
  const PlayerScreen({super.key, required this.catalog, required this.list, required this.index});
  final Catalog catalog;
  final List<Channel> list;
  final int index;

  @override
  State<PlayerScreen> createState() => _PlayerScreenState();
}

class _PlayerScreenState extends State<PlayerScreen> {
  static const maxRetries = 3;

  late final Player player = Player(configuration: const PlayerConfiguration(bufferSize: 48 * 1024 * 1024));
  late final VideoController controller = VideoController(player);
  final videoKey = GlobalKey<VideoState>();
  final subs = <StreamSubscription<dynamic>>[];
  late int index = widget.index;
  bool buffering = true;
  bool hasVideo = false;
  String? failure;
  int retries = 0;
  Timer? retryTimer;
  Timer? stallTimer;

  Channel get channel => widget.list[index];

  @override
  void initState() {
    super.initState();
    subs
      ..add(player.stream.buffering.listen((b) {
        setState(() => buffering = b);
        stallTimer?.cancel();
        // A stream that stays buffering for 30 s is treated as broken and reopened.
        if (b) stallTimer = Timer(const Duration(seconds: 30), () => _fail('The stream stopped sending data.'));
      }))
      ..add(player.stream.playing.listen((p) {
        if (p && failure == null) retries = 0;
      }))
      ..add(player.stream.width.listen((w) => setState(() => hasVideo = (w ?? 0) > 0)))
      ..add(player.stream.error.listen((e) => _fail(e)))
      ..add(player.stream.completed.listen((done) {
        // Live streams should not end; reopen them. Films simply stop.
        if (done && (channel.kind == 'live' || channel.kind == 'radio')) _fail('The stream ended.');
      }));
    _play();
  }

  void _play() {
    retryTimer?.cancel();
    stallTimer?.cancel();
    setState(() {
      failure = null;
      buffering = true;
      hasVideo = false;
    });
    final c = channel;
    // After the current frame: the home screen listens to the catalogue and must not rebuild during this build.
    Future.microtask(() => widget.catalog.watched(c));
    player.open(Media(c.url));
  }

  void _fail(String why) {
    if (!mounted || failure != null || (retryTimer?.isActive ?? false)) return;
    stallTimer?.cancel();
    if (retries < maxRetries) {
      retries++;
      final wait = Duration(seconds: 2 << retries);
      setState(() => buffering = true);
      retryTimer?.cancel();
      retryTimer = Timer(wait, () {
        if (mounted) player.open(Media(channel.url));
      });
      return;
    }
    widget.catalog.markFailing(channel);
    setState(() {
      failure = why;
      buffering = false;
    });
  }

  void _step(int delta) {
    if (widget.list.length < 2) return;
    index = (index + delta) % widget.list.length;
    if (index < 0) index += widget.list.length;
    retries = 0;
    _play();
  }

  Future<void> _toggleMute() async {
    await player.setVolume(player.state.volume > 0 ? 0 : 100);
    if (mounted) setState(() {});
  }

  void _back() {
    final v = videoKey.currentState;
    if (v != null && v.isFullscreen()) {
      v.exitFullscreen();
    } else {
      Navigator.of(context).maybePop();
    }
  }

  @override
  void dispose() {
    retryTimer?.cancel();
    stallTimer?.cancel();
    for (final s in subs) {
      s.cancel();
    }
    player.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final (now, next) = widget.catalog.guide.nowNext(channel.tvgId);
    return CallbackShortcuts(
      bindings: {
        const SingleActivator(LogicalKeyboardKey.keyF): () => videoKey.currentState?.toggleFullscreen(),
        const SingleActivator(LogicalKeyboardKey.keyM): _toggleMute,
        const SingleActivator(LogicalKeyboardKey.pageUp): () => _step(-1),
        const SingleActivator(LogicalKeyboardKey.pageDown): () => _step(1),
        const SingleActivator(LogicalKeyboardKey.keyP): () => _step(-1),
        const SingleActivator(LogicalKeyboardKey.keyN): () => _step(1),
        const SingleActivator(LogicalKeyboardKey.escape): _back,
        const SingleActivator(LogicalKeyboardKey.space): player.playOrPause,
      },
      child: Focus(
        autofocus: true,
        child: Scaffold(
          backgroundColor: Colors.black,
          appBar: AppBar(
            backgroundColor: Colors.black,
            titleSpacing: 0,
            title: Row(
              children: [
                ChannelLogo(channel, size: 32),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(channel.name, maxLines: 1, overflow: TextOverflow.ellipsis),
                      if (now != null || next != null)
                        Text(
                          [if (now != null) 'Now: ${now.title}', if (next != null) 'Next: ${next.title}'].join(' · '),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.white60),
                        ),
                    ],
                  ),
                ),
              ],
            ),
            actions: [
              IconButton(tooltip: 'Previous (Page Up)', icon: const Icon(Icons.skip_previous_rounded), onPressed: () => _step(-1)),
              IconButton(tooltip: 'Next (Page Down)', icon: const Icon(Icons.skip_next_rounded), onPressed: () => _step(1)),
              IconButton(
                tooltip: 'Mute (M)',
                icon: Icon(player.state.volume > 0 ? Icons.volume_up_rounded : Icons.volume_off_rounded),
                onPressed: _toggleMute,
              ),
              IconButton(
                tooltip: 'Favourite',
                icon: Icon(widget.catalog.isFavorite(channel) ? Icons.star_rounded : Icons.star_outline_rounded),
                onPressed: () => setState(() => widget.catalog.toggleFavorite(channel)),
              ),
              IconButton(
                tooltip: 'Fullscreen (F)',
                icon: const Icon(Icons.fullscreen_rounded),
                onPressed: () => videoKey.currentState?.toggleFullscreen(),
              ),
            ],
          ),
          body: GestureDetector(
            // Touch: swipe left or right to change channel.
            onHorizontalDragEnd: (d) {
              final v = d.primaryVelocity ?? 0;
              if (v.abs() > 600) _step(v < 0 ? 1 : -1);
            },
            child: Stack(
              fit: StackFit.expand,
              children: [
                Video(key: videoKey, controller: controller, controls: AdaptiveVideoControls),
                if (!hasVideo && failure == null && !buffering)
                  IgnorePointer(child: Center(child: ChannelLogo(channel, size: 160))),
                if (buffering && failure == null)
                  IgnorePointer(
                    child: Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const CircularProgressIndicator(color: accent),
                          const SizedBox(height: 12),
                          Text(retries > 0 ? 'Reconnecting… ($retries/$maxRetries)' : 'Loading…'),
                        ],
                      ),
                    ),
                  ),
                if (failure != null) _failureCard(),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _failureCard() => Center(
        child: Card(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.portable_wifi_off_rounded, size: 40, color: Colors.amber),
                const SizedBox(height: 8),
                const Text('This channel is not working right now.', style: TextStyle(fontWeight: FontWeight.w600)),
                const SizedBox(height: 4),
                Text(failure ?? '', style: const TextStyle(color: Colors.white54), textAlign: TextAlign.center),
                const SizedBox(height: 12),
                Wrap(
                  spacing: 8,
                  children: [
                    OutlinedButton.icon(
                      icon: const Icon(Icons.refresh_rounded),
                      label: const Text('Try again'),
                      onPressed: () {
                        retries = 0;
                        _play();
                      },
                    ),
                    FilledButton.icon(icon: const Icon(Icons.skip_next_rounded), label: const Text('Next channel'), onPressed: () => _step(1)),
                  ],
                ),
              ],
            ),
          ),
        ),
      );
}
