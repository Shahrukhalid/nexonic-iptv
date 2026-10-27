import io
import tarfile

import httpx
import pytest

from nexonic import fetch
from nexonic.config import DiscoveryConfig

CFG = DiscoveryConfig(retries=3, backoff_base=2.0, max_archive_mb=1)


def make_tar(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def client_for(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_retries_with_exponential_backoff_then_succeeds(tmp_path):
    calls, sleeps = [], []

    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, content=b"ok")

    with (tmp_path / "f").open("wb") as fh:
        fetch.download(
            "https://github.com/x/y/archive/refs/heads/master.tar.gz", fh, CFG, client_for(handler), sleeps.append
        )
    assert (tmp_path / "f").read_bytes() == b"ok"
    assert len(calls) == 3 and sleeps == [2.0, 4.0]


def test_transport_errors_are_retried_and_give_up(tmp_path):
    sleeps = []

    def handler(req):
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(fetch.FetchError, match="giving up after 4 attempts"), (tmp_path / "f").open("wb") as fh:
        fetch.download("https://github.com/a", fh, CFG, client_for(handler), sleeps.append)
    assert sleeps == [2.0, 4.0, 8.0]


def test_retry_after_is_honoured_and_capped(tmp_path):
    sleeps = []
    n = []

    def handler(req):
        n.append(1)
        return httpx.Response(429, headers={"retry-after": "30"}) if len(n) == 1 else httpx.Response(200, content=b"x")

    with (tmp_path / "f").open("wb") as fh:
        fetch.download("https://github.com/a", fh, CFG, client_for(handler), sleeps.append)
    assert sleeps == [30.0]
    assert fetch.backoff_delay(0, 1.0, "9999") == 60.0


def test_client_errors_are_not_retried(tmp_path):
    n = []

    def handler(req):
        n.append(1)
        return httpx.Response(404)

    with pytest.raises(fetch.FetchError, match="HTTP 404"), (tmp_path / "f").open("wb") as fh:
        fetch.download("https://github.com/a", fh, CFG, client_for(handler), lambda s: None)
    assert len(n) == 1


def test_only_allowed_https_hosts(tmp_path):
    def handler(req):
        return httpx.Response(200, content=b"x")

    for url in ("http://github.com/a", "https://evil.example.com/a", "https://192.0.2.1/a"):
        with pytest.raises(fetch.FetchError, match="refusing"), (tmp_path / "f").open("wb") as fh:
            fetch.download(url, fh, CFG, client_for(handler), lambda s: None)


def test_redirects_are_followed_within_the_allow_list_only(tmp_path):
    def handler(req):
        if req.url.host == "github.com":
            return httpx.Response(302, headers={"location": "https://codeload.github.com/x/tar.gz/master"})
        return httpx.Response(200, content=b"data")

    with (tmp_path / "f").open("wb") as fh:
        fetch.download("https://github.com/x", fh, CFG, client_for(handler), lambda s: None)
    assert (tmp_path / "f").read_bytes() == b"data"

    def evil(req):
        return httpx.Response(302, headers={"location": "https://evil.example.com/x"})

    with pytest.raises(fetch.FetchError, match="refusing"), (tmp_path / "g").open("wb") as fh:
        fetch.download("https://github.com/x", fh, CFG, client_for(evil), lambda s: None)


def test_size_limit(tmp_path):
    def handler(req):
        return httpx.Response(200, content=b"x" * (2 * 1024 * 1024))

    with pytest.raises(fetch.FetchError, match="larger than 1 MB"), (tmp_path / "f").open("wb") as fh:
        fetch.download("https://github.com/a", fh, CFG, client_for(handler), lambda s: None)


def test_fetch_iptv_org_extracts_only_expected_files(tmp_path):
    iptv = make_tar(
        {
            "iptv-master/streams/de.m3u": "#EXTM3U\n",
            "iptv-master/streams/sub/x.m3u": "nested",
            "iptv-master/README.md": "no",
            "iptv-master/../../escape.m3u": "never",
        }
    )
    database = make_tar(
        {
            "database-master/data/channels.csv": "id\n",
            "database-master/data/feeds.csv": "channel\n",
            "database-master/data/blocklist.csv": "channel\n",
            "database-master/data/other.csv": "ignored",
        }
    )
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return httpx.Response(200, content=iptv if "/iptv-org/iptv/" in req.url.path else database)

    out = fetch.fetch_iptv_org(CFG, tmp_path / "w", client=client_for(handler), sleep=lambda s: None)
    assert seen == [
        "https://github.com/iptv-org/iptv/archive/refs/heads/master.tar.gz",
        "https://github.com/iptv-org/database/archive/refs/heads/master.tar.gz",
    ]
    assert sorted(p.name for p in out["streams"].iterdir()) == ["de.m3u"]
    assert sorted(p.name for p in out["database"].iterdir()) == ["blocklist.csv", "channels.csv", "feeds.csv"]
    assert not (tmp_path / "escape.m3u").exists()
    assert not list((tmp_path / "w").glob("*.tar.gz"))


def test_fetch_only_what_is_needed(tmp_path):
    seen = []

    def handler(req):
        seen.append(req.url.path)
        return httpx.Response(
            200,
            content=make_tar({"d/data/channels.csv": "id\n", "d/data/blocklist.csv": "c\n", "d/data/feeds.csv": "c\n"}),
        )

    fetch.fetch_iptv_org(CFG, tmp_path, ("database",), client_for(handler), lambda s: None)
    assert seen == ["/iptv-org/database/archive/refs/heads/master.tar.gz"]


def test_empty_archive_is_an_error(tmp_path):
    def handler(req):
        return httpx.Response(200, content=make_tar({"x/README.md": "hi"}))

    with pytest.raises(fetch.FetchError, match="no streams"):
        fetch.fetch_iptv_org(CFG, tmp_path, ("iptv",), client_for(handler), lambda s: None)
