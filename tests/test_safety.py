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


TOKENIZED = [
    "https://infolive.example.cn/live/a.m3u8?auth_key=1-0-0-abc",
    "https://cdn.example.com/a/index.m3u8?akes=eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdefgh",
    "https://cdn.example.com/a.m3u8?authkey=1",
    "https://cdn.example.com/a.m3u8?streamkey=abc",
    "https://cdn.example.com/a.m3u8?access_key=abc",
    "https://cdn.example.com/a.m3u8?accessKey=abc",
    "https://cdn.example.com/a.m3u8?apiKey=abc",
    "https://cdn.example.com/a.m3u8?X-Amz-Signature=0123abcd",
    "https://cdn.example.com/a.m3u8?X-Amz-Expires=300",
    "https://cdn.example.com/a.m3u8?play_token=abc",
    "https://cdn.example.com/a.m3u8?playToken=abc",
    "https://cdn.example.com/a.m3u8?sign=37881ef2e289f062ceff0dca6c24dc58",
    "https://cdn.example.com/a.m3u8?Policy=abc&Key-Pair-Id=K1",
    "https://cdn.example.com/a.m3u8?secret=x",
    "https://cdn.example.com/a.m3u8?client_secret=x",
    "https://cdn.example.com/a.m3u8?jwt=x",
    "https://cdn.example.com/a.m3u8?hmac=x",
    "https://cdn.example.com/a.m3u8?hash=x",
    "https://cdn.example.com/a.m3u8?expire=1700000000",
    "https://cdn.example.com/a.m3u8?AV_VAUTH=x",
    "https://cdn.example.com/a.m3u8?sessionid=abc",
    "https://cdn.example.com/a.m3u8?x=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig",
    "https://cdn.example.com/eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig/index.m3u8",
    "https://cdn.example.com/bitok/eyJzdGlkIjoiMzUzNGNiZTA0NWYyIn0/index.m3u8",
    "https://cdn.example.com/a.m3u8?anvack=pDKqMLyG9pVqMkSYRJHWu3XROjAlvR6z",
    "https://cdn.example.com/a.m3u8?v=0123456789abcdef0123456789abcdef",
]
BENIGN = [
    "https://cdn.example.com/hls/index.m3u8?bpkio_serviceid=6c0958d82a830a02ca0936d9cfab8311",
    "https://cdn.example.com/hls/index.m3u8?app=fcd5c66b-da9d-44ba-a410-4f34805c397d",
    "https://cdn.example.com/hls/index.m3u8?id=11&type=hls&format=m3u8",
    "https://cdn.example.com/hls/index.m3u8?DVR=&offsetSeconds=30",
    "https://cdn.example.com/hls/index.m3u8?ads.xumo_channelId=99&ads.appname=x",
    "https://cdn.example.com/hls/index.m3u8?device_profile=STB_HLS_VCAS_LIVE_HD",
    "https://cdn.example.com/hls/index.m3u8?file=OmroepAssenTV/playlist.m3u8",
    "https://cdn.example.com/hls/index.m3u8?channel_id=abc&network_id=3",
    "https://cdn.example.com/hls/ee6b000cee0629411b666ab26cb13e9b/index.m3u8",
    "https://cdn.example.com/amg26268-sportsstudio-tycsports-freelivesportsemea/playlist.m3u8",
    "https://cdn.example.com/hls/LINEAR-680-WORBAUENFAST-WHALETVPLUS.m3u8",
    "https://cdn.example.com/v1/master/ba62fe743df0fe93366eba3a257d792884136c7f/x/playlist.m3u8",
    "https://cdn.example.com/monkey/turkey/index.m3u8?monkeys=1",
    "https://cdn.example.com/live/a.m3u8?contentId=0123456789abcdef0123456789abcdef",
    "https://cdn.example.com/live/a.m3u8?ref=short&c=us",
]


@pytest.mark.parametrize("url", TOKENIZED)
def test_policy_rejects_tokenized_urls(url):
    res = check_url_policy(url, strict_tokens=True)
    assert not res.ok and res.reason.startswith("tokenized")


@pytest.mark.parametrize("url", BENIGN)
def test_policy_accepts_benign_urls(url):
    assert check_url_policy(url, strict_tokens=True).ok


@pytest.mark.parametrize("url", TOKENIZED[:3])
def test_token_rules_apply_with_restream_allowed_and_are_skipped_for_derived_urls(url):
    assert not check_url_policy(url, allow_restream=True, strict_tokens=True).ok
    assert check_url_policy(url, check_tokens=False).ok


def test_strict_tokens_is_off_by_default():
    url = "https://cdn.example.com/a.m3u8?auth_key=1-0-0-abc"
    assert check_url_policy(url).ok
    assert not check_url_policy(url, strict_tokens=True).ok
    assert not check_url_policy("https://cdn.example.com/a.m3u8?token=1", strict_tokens=True).ok
    assert not check_url_policy("https://cdn.example.com/a.m3u8?token=1").ok


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
