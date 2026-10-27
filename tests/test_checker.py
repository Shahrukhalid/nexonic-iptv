"""Verification engine with MOCKED network responses (no real requests). Live checks are separate (scripts/verify.py)."""

import asyncio

import httpx
import pytest

from nexonic.checker import Limits, check_all
from nexonic.models import Channel
from nexonic.safety import UnsafeURLError
from nexonic.status import Status

TS = bytes([0x47] + [0] * 187) * 3
MASTER = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=1280x720\nlo.m3u8\n"
MEDIA = "#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6,\ns1.ts\n#EXTINF:6,\ns2.ts\n"
URL = "https://live.example-broadcaster.de/hls/news/master.m3u8"


def resolver(host, port):
    if host.startswith("private") or host in ("127.0.0.1", "localhost"):
        raise UnsafeURLError(f"{host} is private")
    return ["93.184.216.34"]


def run(handler, record, limits=None, **rec_kw):
    ch = Channel.model_validate(record(**rec_kw))
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    limits = limits or Limits(timeout=2, retries=1, backoff_base=0.01, per_host_interval=0)

    async def go():
        async with client:
            return await check_all([ch], limits, client=client, resolver=resolver)

    return asyncio.run(go())[0]


def happy(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("master.m3u8"):
        return httpx.Response(200, text=MASTER, headers={"content-type": "application/vnd.apple.mpegurl"})
    if path.endswith("lo.m3u8"):
        return httpx.Response(200, text=MEDIA, headers={"content-type": "application/vnd.apple.mpegurl"})
    if path.endswith(".ts"):
        assert request.headers.get("range", "").startswith("bytes=0-")  # bounded segment read
        return httpx.Response(206, content=TS, headers={"content-type": "video/mp2t"})
    return httpx.Response(404)


def test_verified_working(record):
    r = run(happy, record)
    assert r.status is Status.VERIFIED_WORKING
    assert r.level == 5 and r.media_readable is True
    assert r.details["max_resolution"] == "720p"
    assert r.checked_at.endswith("Z") and r.latency_ms is not None


def test_http_200_html_is_not_enough(record):
    r = run(lambda req: httpx.Response(200, text="<html>Welcome</html>", headers={"content-type": "text/html"}), record)
    assert r.status is Status.INVALID_STREAM


def test_404_unavailable(record):
    assert run(lambda req: httpx.Response(404), record).status is Status.UNAVAILABLE


def test_401_auth(record):
    assert run(lambda req: httpx.Response(401), record).status is Status.AUTH_REQUIRED


def test_403_geo_when_known(record):
    r = run(lambda req: httpx.Response(403), record, geo={"restricted": True, "regions": ["de"]})
    assert r.status is Status.GEO_RESTRICTED


def test_403_geo_hint_in_body(record):
    r = run(lambda req: httpx.Response(403, text="Not available in your country"), record)
    assert r.status is Status.GEO_RESTRICTED


def test_403_without_hint_is_unknown_not_broken(record):
    assert run(lambda req: httpx.Response(403), record).status is Status.UNKNOWN


def test_451_geo(record):
    assert run(lambda req: httpx.Response(451), record).status is Status.GEO_RESTRICTED


def test_429_rate_limited_after_retries(record):
    calls = []

    def h(req):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "0"})

    r = run(h, record)
    assert r.status is Status.RATE_LIMITED and len(calls) == 2  # 1 try + 1 retry


def test_timeout(record):
    def h(req):
        raise httpx.ReadTimeout("slow", request=req)

    assert run(h, record).status is Status.TIMEOUT


def test_connection_error(record):
    def h(req):
        raise httpx.ConnectError("refused", request=req)

    assert run(h, record).status is Status.UNAVAILABLE


def test_redirect_to_private_address_blocked(record):
    def h(req):
        if req.url.host == "live.example-broadcaster.de":
            return httpx.Response(302, headers={"location": "http://127.0.0.1:8080/admin"})
        raise AssertionError("must never connect to the redirect target")

    r = run(h, record)
    assert r.status is Status.INVALID_STREAM and "redirect" in r.error


def test_redirect_to_private_hostname_blocked(record):
    def h(req):
        if req.url.host == "live.example-broadcaster.de":
            return httpx.Response(301, headers={"location": "https://private.example.net/x.m3u8"})
        raise AssertionError("must not fetch")

    assert run(h, record).status is Status.INVALID_STREAM


def test_redirect_loop_limited(record):
    r = run(lambda req: httpx.Response(302, headers={"location": URL}), record)
    assert r.status is Status.INVALID_STREAM


def test_good_redirect_followed_and_revalidated(record):
    def h(req):
        if req.url.host == "live.example-broadcaster.de":
            return httpx.Response(302, headers={"location": "https://cdn.example-broadcaster.de/hls/master.m3u8"})
        return happy(req)

    r = run(h, record)
    assert r.status is Status.VERIFIED_WORKING
    assert r.details["redirected_to_host"] == "cdn.example-broadcaster.de"


def test_drm_unsupported(record):
    drm = '#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="skd://x"\n#EXTINF:6,\na.ts\n'
    r = run(lambda req: httpx.Response(200, text=drm), record)
    assert r.status is Status.UNSUPPORTED


def test_segment_not_media(record):
    def h(req):
        if req.url.path.endswith(".ts"):
            return httpx.Response(200, content=b"<html>error</html>")
        return happy(req)

    assert run(h, record).status is Status.INVALID_STREAM


def test_response_size_is_bounded(record):
    big = "#EXTM3U\n#EXT-X-TARGETDURATION:6\n" + ("#EXTINF:6,\nseg.ts\n" * 200000)
    lim = Limits(timeout=2, retries=0, per_host_interval=0, manifest_bytes=64 * 1024, max_bytes=10**9)

    def h(req):
        if req.url.path.endswith(".ts"):
            return httpx.Response(206, content=TS)
        return httpx.Response(200, text=big)

    r = run(h, record, limits=lim)
    assert r.status is Status.VERIFIED_WORKING  # parsed the first 64 KiB only


def test_record_url_policy_violation_never_fetched(record):
    def h(req):
        raise AssertionError("must not fetch")

    r = run(h, record, **{"stream.url": "https://example.com/live.m3u8?token=secret"})
    assert r.status is Status.INVALID_STREAM


@pytest.mark.parametrize("status", list(Status))
def test_status_values_serialise(status):
    from nexonic.status import CheckResult

    d = CheckResult("x", status, "2026-10-17T00:00:00Z").to_dict()
    assert CheckResult.from_dict(d).status is status


def test_channel_hard_timeout(record):
    import time as _t

    def slow(req):
        _t.sleep(0.5)
        return httpx.Response(200, text=MEDIA)

    lim = Limits(timeout=5, retries=0, per_host_interval=0, channel_timeout=0.2)
    assert run(slow, record, limits=lim).status is Status.TIMEOUT


def test_run_budget_marks_not_tested(record):
    lim = Limits(timeout=2, retries=0, per_host_interval=0, run_budget=-1)
    r = run(happy, record, limits=lim)
    assert r.status is Status.NOT_TESTED and "budget" in r.error


def test_channels_on_one_host_do_not_time_out_while_queued(record):
    """Waiting for a busy host must not count against a channel's own time limit."""
    chans = [
        Channel.model_validate(
            record(id=f"example-news-{i}", name=f"Example News {i}", **{"stream.url": URL.replace("news", f"n{i}")})
        )
        for i in range(4)
    ]
    lim = Limits(timeout=2, retries=0, per_host_interval=0.15, channel_timeout=0.9, concurrency=4)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(happy), follow_redirects=False) as client:
            return await check_all(chans, lim, client=client, resolver=resolver)

    results = asyncio.run(go())
    assert [r.status for r in results] == [Status.VERIFIED_WORKING] * 4


def test_malformed_url_is_invalid_stream_not_a_batch_failure(record):
    def h(req):
        raise AssertionError("must not fetch")

    r = run(h, record, **{"stream.url": "https://[broken/live.m3u8"})
    assert r.status is Status.INVALID_STREAM


def test_shared_cdn_gate_waits_do_not_count_against_channel_timeout(record):
    """Distinct origins that redirect to one CDN queue on the CDN's gate; that wait must not cause TIMEOUT."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.startswith("origin"):
            n = request.url.host.split(".")[0]
            return httpx.Response(302, headers={"location": f"https://cdn.example-cdn.net/{n}/master.m3u8"})
        return happy(request)

    chans = [
        Channel.model_validate(
            record(
                id=f"example-news-{i}",
                name=f"Example News {i}",
                **{"stream.url": f"https://origin{i}.example.de/m.m3u8"},
            )
        )
        for i in range(6)
    ]
    lim = Limits(timeout=2, retries=0, per_host_interval=0.15, channel_timeout=0.9, concurrency=6)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
            return await check_all(chans, lim, client=client, resolver=resolver)

    results = asyncio.run(go())
    assert [r.status for r in results] == [Status.VERIFIED_WORKING] * 6
