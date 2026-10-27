"""Layered stream verification engine.

Level 1  URL syntax and policy (scheme, host, port, tokens)            -> INVALID_STREAM / UNSUPPORTED
Level 2  DNS resolution; every address must be public                  -> UNAVAILABLE
Level 3  Bounded HTTP GET of the manifest, redirects re-validated       -> UNAVAILABLE / AUTH / GEO / RATE / TIMEOUT
Level 4  Manifest parsing (HLS master -> one media playlist; DASH MPD)  -> INVALID_STREAM / UNSUPPORTED (DRM)
Level 5  Small byte-range read of one media segment (+ optional FFprobe)-> INVALID_STREAM
Level 6  Record latency, error type, timestamp and result

Politeness: global concurrency limit, one request at a time per host with a minimum interval, at most
``max_requests`` requests and ``max_bytes`` bytes per channel, bounded retries with exponential backoff that honour
``Retry-After``. The checker never sends cookies or credentials and never retries an access-control response.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import shutil
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from . import hls
from .models import Channel
from .safety import SafeNetworkBackend, UnsafeURLError, check_url_policy, resolve_public
from .status import CheckResult, Status
from .timeutil import utc_now_iso

USER_AGENT = "NexonicIPTV-Verifier/1.0 (+https://github.com/Shahrukhalid/nexonic-iptv; stream health check)"
HLS_TYPES = (
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
    "audio/mpegurl",
    "audio/x-mpegurl",
    "text/plain",
    "application/octet-stream",
    "binary/octet-stream",
    "video/mp2t",
)
DASH_TYPES = ("application/dash+xml", "video/vnd.mpeg.dash.mpd", "application/xml", "text/xml")
GEO_HINTS = ("geo", "country", "region", "territor", "not available in your", "location")


@dataclass
class Limits:
    timeout: float = 10.0
    manifest_bytes: int = 512 * 1024
    segment_bytes: int = 188 * 1024
    max_bytes: int = 1024 * 1024
    max_requests: int = 5
    max_redirects: int = 3
    retries: int = 1
    backoff_base: float = 1.0
    per_host_interval: float = 1.0
    concurrency: int = 12
    use_ffprobe: bool = False
    ffprobe_timeout: float = 15.0
    channel_timeout: float = 60.0  # hard cap per channel; exceeded -> TIMEOUT
    run_budget: float = 40 * 60.0  # channels not started within the budget are recorded NOT_TESTED


class Budget:
    def __init__(self, limits: Limits):
        self.requests = 0
        self.bytes = 0
        self.limits = limits

    def take_request(self) -> None:
        self.requests += 1
        if self.requests > self.limits.max_requests:
            raise BudgetExceeded("request budget exhausted")

    def add_bytes(self, n: int) -> None:
        self.bytes += n
        if self.bytes > self.limits.max_bytes:
            raise BudgetExceeded("byte budget exhausted")


class BudgetExceeded(Exception):
    pass


class HostGate:
    """Serialises requests per host and enforces a minimum interval between them."""

    def __init__(self, interval: float):
        self.interval = interval
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}

    def lock(self, host: str) -> asyncio.Lock:
        return self._locks.setdefault(host, asyncio.Lock())

    async def wait_turn(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            delay = self.interval - (time.monotonic() - last)
            if delay > 0:
                await asyncio.sleep(delay)

    def mark(self, host: str) -> None:
        self._last[host] = time.monotonic()


class GateWait:
    """Time one channel check has spent queued on a HostGate (any request host, including redirect targets)."""

    def __init__(self) -> None:
        self.total = 0.0
        self.since: float | None = None  # start of the wait in progress, if any

    def waited(self, now: float) -> float:
        return self.total + (now - self.since if self.since is not None else 0.0)


_gate_wait: ContextVar[GateWait | None] = ContextVar("nexonic_gate_wait", default=None)


def _active(start: float, gw: GateWait) -> float:
    now = time.monotonic()
    return (now - start) - gw.waited(now)


async def _with_active_timeout(coro, limit: float, gw: GateWait):
    """Run ``coro`` but apply ``limit`` to time spent doing real work, not queued on a HostGate."""
    task = asyncio.ensure_future(coro)
    start = time.monotonic()
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=max(limit - _active(start, gw), 0))
            if _active(start, gw) >= limit:  # also catches a result that arrived after the cap (blocked loop)
                raise TimeoutError
            if done:
                return task.result()
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@dataclass
class FetchResult:
    url: str  # final URL after redirects
    status: int
    headers: httpx.Headers
    body: bytes
    elapsed_ms: int


class Fetcher:
    def __init__(self, client: httpx.AsyncClient, limits: Limits, gate: HostGate, resolver=resolve_public):
        self.client = client
        self.limits = limits
        self.gate = gate
        self.resolver = resolver

    @asynccontextmanager
    async def _turn(self, host: str):
        """Hold the host's gate for one request, recording the time spent queued for it."""
        gw = _gate_wait.get()
        lock = self.gate.lock(host)
        if gw is not None:
            gw.since = time.monotonic()
        try:
            await lock.acquire()
            try:
                await self.gate.wait_turn(host)
            except BaseException:
                lock.release()
                raise
        finally:
            if gw is not None:
                gw.total, gw.since = gw.waited(time.monotonic()), None
        try:
            yield
        finally:
            lock.release()

    async def get(
        self, url: str, budget: Budget, max_bytes: int, byte_range: bool = False, derived: bool = False
    ) -> FetchResult:
        """GET with manual, re-validated redirects. ``derived`` marks URLs taken from a manifest or redirect,
        which may legitimately carry server-issued tokens; the record's own URL may not."""
        current = url
        for hop in range(self.limits.max_redirects + 1):
            server_issued = derived or hop > 0
            policy = check_url_policy(current, allow_ip_literal=server_issued, check_tokens=not server_issued)
            if not policy.ok:
                raise UnsafeURLError(f"{'redirect target ' if hop else ''}{policy.reason}")
            parts = urlsplit(current)
            port = parts.port or (443 if parts.scheme == "https" else 80)
            await asyncio.to_thread(self.resolver, parts.hostname, port)  # raises on private addresses
            budget.take_request()
            headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
            if byte_range:
                headers["Range"] = f"bytes=0-{max_bytes - 1}"
            host = parts.hostname or ""
            async with self._turn(host):
                start = time.monotonic()
                try:
                    async with self.client.stream("GET", current, headers=headers) as resp:
                        elapsed = int((time.monotonic() - start) * 1000)
                        if resp.is_redirect:
                            location = resp.headers.get("location")
                            if not location:
                                raise httpx.RemoteProtocolError("redirect without Location")
                            current = urljoin(current, location)
                            continue
                        chunks: list[bytes] = []
                        size = 0
                        async for chunk in resp.aiter_bytes():
                            take = chunk[: max_bytes - size]
                            chunks.append(take)
                            size += len(take)
                            if size >= max_bytes:
                                break
                        budget.add_bytes(size)
                        return FetchResult(current, resp.status_code, resp.headers, b"".join(chunks), elapsed)
                finally:
                    self.gate.mark(host)
        raise UnsafeURLError("too many redirects")


def _classify_http(code: int, body: bytes, headers: httpx.Headers, channel: Channel) -> tuple[Status, str]:
    text = body[:2048].decode("utf-8", "replace").lower()
    if code == 451:
        return Status.GEO_RESTRICTED, "HTTP 451 (unavailable for legal reasons, typically regional)"
    if code in (401, 407):
        return Status.AUTH_REQUIRED, f"HTTP {code} (authentication required)"
    if code == 403:
        if channel.geo.restricted is True or any(h in text for h in GEO_HINTS) or "x-geo" in str(headers).lower():
            return Status.GEO_RESTRICTED, "HTTP 403 for a stream known or hinted to be region-limited"
        return Status.UNKNOWN, "HTTP 403 forbidden (could be regional limits or access control)"
    if code == 429:
        return Status.RATE_LIMITED, "HTTP 429 (rate limited by host)"
    if code in (404, 410):
        return Status.UNAVAILABLE, f"HTTP {code} (stream not found)"
    if code >= 500:
        return Status.UNAVAILABLE, f"HTTP {code} (server error)"
    if code >= 400:
        return Status.UNAVAILABLE, f"HTTP {code}"
    return Status.VERIFIED_WORKING, ""


def _retry_after(headers: httpx.Headers) -> float | None:
    value = headers.get("retry-after")
    if value and value.isdigit():
        return min(float(value), 30.0)
    return None


async def _get_with_retry(fetcher: Fetcher, url: str, budget: Budget, max_bytes: int, byte_range=False, derived=False):
    attempt = 0
    while True:
        try:
            res = await fetcher.get(url, budget, max_bytes, byte_range, derived)
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt >= fetcher.limits.retries:
                raise
        else:
            if res.status not in (429, 500, 502, 503, 504) or attempt >= fetcher.limits.retries:
                return res
            delay = _retry_after(res.headers)
            if delay is not None:
                await asyncio.sleep(delay)
                attempt += 1
                continue
        await asyncio.sleep(fetcher.limits.backoff_base * (2**attempt) * (0.8 + 0.4 * random.random()))
        attempt += 1


async def _ffprobe(url: str, timeout: float) -> tuple[bool, str, dict]:
    """Optional playback-readability probe. Only called on URLs that already passed every network check."""
    exe = shutil.which("ffprobe")
    if not exe:
        return False, "ffprobe not installed", {}
    args = [
        exe,
        "-v",
        "error",
        "-hide_banner",
        "-protocol_whitelist",
        "https,http,tls,tcp,hls,crypto",
        "-rw_timeout",
        str(int(timeout * 1_000_000)),
        "-user_agent",
        USER_AGENT,
        "-show_entries",
        "stream=codec_type,codec_name,width,height",
        "-of",
        "json",
        "-i",
        url,
    ]
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, stdin=asyncio.subprocess.DEVNULL
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout + 5)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return False, "ffprobe timed out", {}
    if proc.returncode != 0:
        return False, err.decode("utf-8", "replace").strip()[:300] or "ffprobe failed", {}
    try:
        data = json.loads(out or b"{}")
    except json.JSONDecodeError:
        return False, "ffprobe returned invalid JSON", {}
    streams = data.get("streams", [])
    kinds = sorted({s.get("codec_type") for s in streams if s.get("codec_type")})
    return ("video" in kinds or "audio" in kinds), "", {"ffprobe_streams": kinds}


async def check_channel(fetcher: Fetcher, channel: Channel, location: str) -> CheckResult:
    started = utc_now_iso()
    res = CheckResult(channel.id, Status.UNKNOWN, started, location=location)
    url = channel.stream.url
    budget = Budget(fetcher.limits)

    # Level 1
    policy = check_url_policy(url)
    if not policy.ok:
        res.status, res.error = Status.INVALID_STREAM, f"URL policy: {policy.reason}"
        return res
    if channel.stream.protocol not in ("hls", "dash"):
        res.status, res.error = Status.UNSUPPORTED, f"protocol {channel.stream.protocol} not verifiable"
        res.level = 1
        return res
    res.level = 1

    # Level 2
    parts = urlsplit(url)
    try:
        await asyncio.to_thread(
            fetcher.resolver, parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)
        )
    except UnsafeURLError as exc:
        res.status, res.error = Status.INVALID_STREAM, f"unsafe target: {exc}"
        return res
    except OSError as exc:
        res.status, res.error = Status.UNAVAILABLE, str(exc)[:300]
        return res
    res.level = 2

    # Level 3
    try:
        manifest = await _get_with_retry(fetcher, url, budget, fetcher.limits.manifest_bytes)
    except UnsafeURLError as exc:
        res.status, res.error = Status.INVALID_STREAM, f"unsafe redirect: {exc}"
        return res
    except httpx.TimeoutException:
        res.status, res.error = Status.TIMEOUT, f"no response within {fetcher.limits.timeout:.0f}s"
        return res
    except httpx.TransportError as exc:
        res.status, res.error = Status.UNAVAILABLE, f"connection error: {type(exc).__name__}: {exc}"[:300]
        return res
    except (BudgetExceeded, OSError) as exc:
        res.status, res.error = Status.UNKNOWN, str(exc)[:300]
        return res
    res.http_status = manifest.status
    res.latency_ms = manifest.elapsed_ms
    status, why = _classify_http(manifest.status, manifest.body, manifest.headers, channel)
    if status is not Status.VERIFIED_WORKING:
        res.status, res.error = status, why
        return res
    ctype = manifest.headers.get("content-type", "").split(";")[0].strip().lower()
    res.details["content_type"] = ctype or "missing"
    if manifest.url != url:
        res.details["redirected_to_host"] = urlsplit(manifest.url).hostname
    res.level = 3

    # Level 4
    body = manifest.body.decode("utf-8", "replace")
    try:
        if channel.stream.protocol == "dash" or (ctype in DASH_TYPES and not hls.looks_like_hls(body)):
            info = hls.inspect_dash(body)
            if info["drm"]:
                res.status, res.error = Status.UNSUPPORTED, "DASH ContentProtection (DRM) present"
                return res
            res.level = 4
            res.status = Status.VERIFIED_WORKING
            res.details["note"] = "DASH manifest valid; segment probe not implemented for DASH"
            return res
        if ctype and ctype not in HLS_TYPES and not hls.looks_like_hls(body):
            res.status, res.error = Status.INVALID_STREAM, f"unexpected content type {ctype}"
            return res
        playlist = hls.parse_hls(body, manifest.url)
        media_url = manifest.url
        if playlist.kind == "master":
            res.details["variants"] = len(playlist.variants)
            best = hls.best_resolution(playlist.variants)
            if best:
                res.details["max_resolution"] = best
            if playlist.drm:
                res.status, res.error = Status.UNSUPPORTED, f"DRM ({playlist.drm})"
                return res
            variant = hls.choose_variant(playlist.variants)
            media_url = variant.uri
            media = await _get_with_retry(fetcher, media_url, budget, fetcher.limits.manifest_bytes, derived=True)
            st, why = _classify_http(media.status, media.body, media.headers, channel)
            if st is not Status.VERIFIED_WORKING:
                res.status, res.error = st, f"variant playlist: {why}"
                return res
            media_url = media.url
            playlist = hls.parse_hls(media.body.decode("utf-8", "replace"), media.url)
            if playlist.kind != "media":
                raise hls.ManifestError("variant playlist is another master playlist")
        if playlist.drm:
            res.status, res.error = Status.UNSUPPORTED, f"DRM ({playlist.drm})"
            return res
        res.details["segments_listed"] = len(playlist.segments)
        res.details["target_duration"] = playlist.target_duration
        if playlist.endlist:
            res.details["note"] = "playlist has EXT-X-ENDLIST (not a live window)"
        res.level = 4

        # Level 5
        if playlist.encrypted:
            res.details["segment_probe"] = "skipped (AES-128 encrypted segments)"
            res.media_readable = None
        else:
            segment_url = playlist.segments[-1]
            seg = await _get_with_retry(
                fetcher, segment_url, budget, fetcher.limits.segment_bytes, byte_range=True, derived=True
            )
            st, why = _classify_http(seg.status, seg.body, seg.headers, channel)
            if st is not Status.VERIFIED_WORKING:
                res.status, res.error = st, f"segment: {why}"
                return res
            container = hls.sniff_media(seg.body)
            res.details["segment_container"] = container or "unrecognised"
            res.media_readable = container is not None
            if not container:
                res.status, res.error = Status.INVALID_STREAM, "segment bytes are not a recognised media container"
                return res
            res.level = 5
        if fetcher.limits.use_ffprobe:
            ok, err, info = await _ffprobe(media_url, fetcher.limits.ffprobe_timeout)
            res.details.update(info)
            res.details["ffprobe"] = "ok" if ok else f"failed: {err}"
            if ok:
                res.method = "httpx+ffprobe"
                res.media_readable = True
    except hls.ManifestError as exc:
        res.status, res.error = Status.INVALID_STREAM, f"manifest: {exc}"
        return res
    except UnsafeURLError as exc:
        res.status, res.error = Status.INVALID_STREAM, f"unsafe URL in manifest: {exc}"
        return res
    except httpx.TimeoutException:
        res.status, res.error = Status.TIMEOUT, "timed out after manifest was fetched"
        return res
    except httpx.TransportError as exc:
        res.status, res.error = Status.UNAVAILABLE, f"connection error: {type(exc).__name__}"[:300]
        return res
    except BudgetExceeded as exc:
        res.status, res.error = Status.UNKNOWN, str(exc)
        return res

    res.status = Status.VERIFIED_WORKING
    res.level = max(res.level, 4)
    return res


def _proxy_endpoints() -> tuple[str | None, set[tuple[str, int]]]:
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not proxy:
        return None, set()
    p = urlsplit(proxy)
    return proxy, {(p.hostname or "", p.port or 80)}


def build_client(limits: Limits) -> httpx.AsyncClient:
    proxy, allowed = _proxy_endpoints()
    transport = httpx.AsyncHTTPTransport(proxy=proxy, retries=0, http2=False)
    # Pin every TCP connection to a validated public address (see safety.SafeNetworkBackend).
    transport._pool._network_backend = SafeNetworkBackend(allowed_proxies=allowed)  # noqa: SLF001
    return httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(limits.timeout),
        follow_redirects=False,
        trust_env=False,
        headers={"User-Agent": USER_AGENT},
        cookies=None,
    )


def location_label() -> str:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return f"github-actions ({os.environ.get('RUNNER_OS', 'unknown')}, GitHub-hosted runner)"
    return os.environ.get("NEXONIC_CHECK_LOCATION", "local")


async def check_all(
    channels: list[Channel], limits: Limits, client: httpx.AsyncClient | None = None, resolver=resolve_public
) -> list[CheckResult]:
    own = client is None
    client = client or build_client(limits)
    gate = HostGate(limits.per_host_interval)
    fetcher = Fetcher(client, limits, gate, resolver=resolver)
    sem = asyncio.Semaphore(limits.concurrency)
    # One channel at a time per stream host. Without this, many channels on one CDN take every global slot and
    # queue behind each other in HostGate. Gate waits are also excluded from ``channel_timeout`` (see GateWait).
    host_slots: dict[str, asyncio.Semaphore] = {}
    location = location_label()
    deadline = time.monotonic() + limits.run_budget

    async def one(ch: Channel) -> CheckResult:
        try:
            host = (urlsplit(ch.stream.url).hostname or "").lower()
        except ValueError:  # malformed URL (e.g. unbalanced "["): check_channel's policy check classifies it
            host = ""
        async with host_slots.setdefault(host, asyncio.Semaphore(1)), sem:
            if time.monotonic() > deadline:
                return CheckResult(
                    ch.id, Status.NOT_TESTED, utc_now_iso(), error="run time budget exhausted", location=location
                )
            gw = GateWait()
            _gate_wait.set(gw)  # each ``one()`` runs in its own task, so this is per-channel
            try:
                # Time queued on any host's HostGate (the stream host or a redirect/CDN target) is not charged.
                return await _with_active_timeout(check_channel(fetcher, ch, location), limits.channel_timeout, gw)
            except TimeoutError:
                return CheckResult(
                    ch.id,
                    Status.TIMEOUT,
                    utc_now_iso(),
                    error=f"channel check exceeded {limits.channel_timeout:.0f}s",
                    location=location,
                )
            except Exception as exc:  # never let one channel abort the run; record honestly
                return CheckResult(
                    ch.id, Status.UNKNOWN, utc_now_iso(), error=f"checker error: {exc!r}"[:300], location=location
                )

    try:
        return list(await asyncio.gather(*(one(c) for c in channels)))
    finally:
        if own:
            await client.aclose()
