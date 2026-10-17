import asyncio

import pytest

from nexonic.safety import SafeNetworkBackend, UnsafeURLError, check_url_policy, is_public_ip, resolve_public


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/a.m3u8",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "https://user:pass@example.com/live.m3u8",
        "https://localhost/live.m3u8",
        "https://printer.local/live.m3u8",
        "https://intranet/live.m3u8",
        "https://127.0.0.1/live.m3u8",
        "https://10.0.0.5/live.m3u8",
        "https://[::1]/live.m3u8",
        "https://169.254.169.254/latest/meta-data",
        "https://8.8.8.8/live.m3u8",  # public, but IP literals are not accepted as record URLs
        "https://example.com:22/live.m3u8",
        "https://example.com/live.m3u8?token=abc",
        "https://example.com/live.m3u8?hdnts=exp=1~acl=*",
        "https://example.com/live.m3u8?wmsAuthSign=xyz",
        "https://cdn-7.pishow.tv/live/1/master.m3u8",
        "https://c.mjh.nz/abc.m3u8",
        "https://raw.githubusercontent.com/x/y/main/a.m3u8",
        "https://exa mple.com/a.m3u8",
        "https://example.com/a\n.m3u8",
    ],
)
def test_policy_rejects(url):
    assert not check_url_policy(url).ok


@pytest.mark.parametrize(
    "url",
    [
        "https://live.france24.com/hls/live/2037218/F24_EN_HI_HLS/master.m3u8",
        "http://amdlive-ch01.ctnd.com.edgesuite.net/arirang_1ch/smil:arirang_1ch.smil/playlist.m3u8",
        "https://streaming-live.rtp.pt/livetvhlsDVR/rtpnHDdvr.smil/playlist.m3u8?DVR=",
    ],
)
def test_policy_accepts(url):
    assert check_url_policy(url).ok


def test_server_issued_tokens_allowed_for_derived_urls():
    assert check_url_policy("https://cdn.example.com/seg.ts?token=1", check_tokens=False).ok


@pytest.mark.parametrize(
    "ip,public",
    [
        ("8.8.8.8", True),
        ("1.1.1.1", True),
        ("127.0.0.1", False),
        ("10.1.2.3", False),
        ("172.16.0.1", False),
        ("192.168.1.1", False),
        ("169.254.169.254", False),
        ("100.64.0.1", False),
        ("0.0.0.0", False),
        ("224.0.0.1", False),
        ("::1", False),
        ("fe80::1", False),
        ("fc00::1", False),
        ("::ffff:127.0.0.1", False),
        ("2001:4860:4860::8888", True),
        ("not-an-ip", False),
    ],
)
def test_is_public_ip(ip, public):
    assert is_public_ip(ip) is public


def test_resolve_public_blocks_private(monkeypatch):
    import socket

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("10.0.0.7", 443))])
    with pytest.raises(UnsafeURLError):
        resolve_public("rebind.example.com", 443)


def test_resolve_public_blocks_mixed_answers(monkeypatch):
    import socket

    answers = [(2, 1, 6, "", ("93.184.216.34", 443)), (2, 1, 6, "", ("127.0.0.1", 443))]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: answers)
    with pytest.raises(UnsafeURLError):
        resolve_public("mixed.example.com", 443)


def test_safe_backend_pins_validated_ip():
    calls = []

    class Inner:
        async def connect_tcp(self, host, port, **kw):
            calls.append((host, port))
            return "stream"

    backend = SafeNetworkBackend(resolver=lambda h, p: ["93.184.216.34"])
    backend._inner = Inner()
    assert asyncio.run(backend.connect_tcp("example.com", 443)) == "stream"
    assert calls == [("93.184.216.34", 443)]


def test_safe_backend_refuses_private_resolution():
    def resolver(host, port):
        raise UnsafeURLError("private")

    backend = SafeNetworkBackend(resolver=resolver)
    with pytest.raises(UnsafeURLError):
        asyncio.run(backend.connect_tcp("evil.example.com", 443))


def test_safe_backend_allows_configured_proxy_only():
    calls = []

    class Inner:
        async def connect_tcp(self, host, port, **kw):
            calls.append(host)
            return "s"

    backend = SafeNetworkBackend(
        allowed_proxies={("127.0.0.1", 3128)}, resolver=lambda h, p: (_ for _ in ()).throw(UnsafeURLError("no"))
    )
    backend._inner = Inner()
    asyncio.run(backend.connect_tcp("127.0.0.1", 3128))
    assert calls == ["127.0.0.1"]
    with pytest.raises(UnsafeURLError):
        asyncio.run(backend.connect_tcp("127.0.0.1", 8080))
