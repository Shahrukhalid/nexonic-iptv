/// HTTP for playlists, provider logins and guides: timeouts, a size cap and readable errors.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

const userAgent = 'NexonicIPTV/1.4';

class FetchError implements Exception {
  FetchError(this.message);
  final String message;
  @override
  String toString() => message;
}

/// A downloaded body and the server's ETag (when it sent one).
class Fetched {
  const Fetched(this.status, this.bytes, this.etag);
  final int status;
  final List<int> bytes;
  final String? etag;
  String get text => utf8.decode(bytes, allowMalformed: true);
}

/// Replaces network access in tests: returns the body, or null when the address is not available.
typedef Fetcher = Future<String?> Function(Uri uri);

/// Downloads a URL. A 304 answer (when `etag` is given) returns an empty body with status 304.
Future<Fetched> download(
  Uri uri, {
  Map<String, String> headers = const {},
  String? etag,
  int maxMb = 200,
  Duration timeout = const Duration(minutes: 3),
}) async {
  final c = HttpClient()
    ..connectionTimeout = const Duration(seconds: 20)
    ..userAgent = headers['User-Agent'] ?? userAgent;
  try {
    final req = await c.getUrl(uri).timeout(const Duration(seconds: 30));
    req.followRedirects = true;
    req.maxRedirects = 8;
    headers.forEach((k, v) {
      if (k.toLowerCase() != 'user-agent') req.headers.set(k, v);
    });
    if (etag != null) req.headers.set(HttpHeaders.ifNoneMatchHeader, etag);
    final res = await req.close().timeout(const Duration(seconds: 60));
    if (res.statusCode == 304) {
      await res.drain<void>();
      return Fetched(304, const [], etag);
    }
    if (res.statusCode != 200) {
      await res.drain<void>();
      throw FetchError(switch (res.statusCode) {
        401 || 403 => 'The server refused access (HTTP ${res.statusCode}). Check the login.',
        404 => 'Not found (HTTP 404). Check the address.',
        _ => 'The server answered HTTP ${res.statusCode}.',
      });
    }
    final limit = maxMb * 1024 * 1024;
    final out = BytesBuilder(copy: false);
    await for (final chunk in res.timeout(timeout)) {
      out.add(chunk);
      if (out.length > limit) throw FetchError('The file is larger than $maxMb MB.');
    }
    return Fetched(200, out.takeBytes(), res.headers.value(HttpHeaders.etagHeader));
  } on FetchError {
    rethrow;
  } on TimeoutException {
    throw FetchError('The server did not answer in time.');
  } on SocketException catch (e) {
    throw FetchError('Could not connect (${e.osError?.message ?? e.message}).');
  } on HandshakeException {
    throw FetchError('Secure connection failed. Try the http:// address.');
  } on HttpException catch (e) {
    throw FetchError('Connection error (${e.message}).');
  } on FormatException {
    throw FetchError('That is not a valid address.');
  } on ArgumentError {
    throw FetchError('That is not a valid address.');
  } finally {
    c.close(force: true);
  }
}

/// Downloads text, through the test fetcher when one is given.
Future<String> fetchText(Uri uri, {Fetcher? fetcher, Map<String, String> headers = const {}, int maxMb = 200}) async {
  if (fetcher != null) {
    final t = await fetcher(uri);
    if (t == null) throw FetchError('Not available offline.');
    return t;
  }
  return (await download(uri, headers: headers, maxMb: maxMb)).text;
}

/// Downloads bytes (guides may be gzip files), through the test fetcher when one is given.
Future<List<int>> fetchBytes(Uri uri, {Fetcher? fetcher, Map<String, String> headers = const {}, int maxMb = 200}) async {
  if (fetcher != null) {
    final t = await fetcher(uri);
    if (t == null) throw FetchError('Not available offline.');
    return utf8.encode(t);
  }
  return (await download(uri, headers: headers, maxMb: maxMb)).bytes;
}
