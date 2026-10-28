"""Third-party M3U sources: configuration, download (mocked network), cross-source dedup, unchanged admission rules."""

import json
from pathlib import Path

import httpx
import pytest
import yaml
from conftest import load_script

from nexonic import fetch
from nexonic.config import ConfigError, DiscoveryConfig, _check_extra_m3u, load_pipeline

ec = load_script("expand_catalog")

OPEN_LICENCES = {"MIT", "Unlicense", "CC0-1.0", "Apache-2.0", "BSD-3-Clause", "ISC", "MPL-2.0"}


def entry(**kw):
    base = {"name": "demo", "repo": "owner/repo", "ref": "main", "paths": ["lists/de.m3u"], "licence": "MIT"}
    return {**base, **kw}


def cfg_with(*entries, **kw):
    return DiscoveryConfig(extra_m3u=list(entries), retries=1, backoff_base=1.0, **kw)


def client_for(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------------------------------- configuration
def test_shipped_config_lists_only_licensed_plain_m3u_sources():
    extras = load_pipeline().discovery.extra_m3u
    assert extras, "the repository ships a list of extra sources"
    names = [e["name"] for e in extras]
    assert len(names) == len(set(names))
    for e in extras:
        assert e["licence"] in OPEN_LICENCES, e
        assert all(p.lower().endswith((".m3u", ".m3u8")) for p in e["paths"])


def test_extra_m3u_defaults_match_the_shipped_file_and_parse_from_toml(tmp_path):
    assert load_pipeline(tmp_path / "missing.toml").discovery.extra_m3u == load_pipeline().discovery.extra_m3u
    f = tmp_path / "p.toml"
    f.write_text(
        '[[discovery.extra_m3u]]\nname = "demo"\nrepo = "owner/repo"\nref = "main"\n'
        'paths = ["a/b.m3u"]\nlicence = "MIT"\n',
        encoding="utf-8",
    )
    assert load_pipeline(f).discovery.extra_m3u == [entry(paths=["a/b.m3u"])]


@pytest.mark.parametrize(
    "bad",
    [
        {"licence": ""},
        {"licence": "  "},
        {"paths": []},
        {"paths": ["../etc/passwd.m3u"]},
        {"paths": ["/abs.m3u"]},
        {"paths": ["a//b.m3u"]},
        {"paths": ["list.txt"]},
        {"paths": ["a.m3u?token=1"]},
        {"paths": ["a.m3u#x"]},
        {"repo": "not-a-repo"},
        {"repo": "https://github.com/a/b"},
        {"ref": "../x"},
        {"name": "Bad Name"},
    ],
)
def test_bad_extra_entries_are_rejected(bad):
    with pytest.raises(ConfigError):
        _check_extra_m3u([entry(**bad)])


def test_missing_keys_unknown_keys_and_duplicate_names_are_rejected():
    good = entry()
    with pytest.raises(ConfigError):
        _check_extra_m3u([{k: v for k, v in good.items() if k != "licence"}])
    with pytest.raises(ConfigError):
        _check_extra_m3u([{**good, "headers": {"x": "y"}}])
    with pytest.raises(ConfigError):
        _check_extra_m3u([good, entry(repo="other/repo")])
    _check_extra_m3u([good, entry(name="second")])


# ---------------------------------------------------------------------------------------------------------- download
def test_download_uses_raw_https_urls_records_the_exact_file_and_retries(tmp_path):
    seen, sleeps = [], []

    def handler(req):
        seen.append(str(req.url))
        if len(seen) == 1:
            return httpx.Response(503)
        return httpx.Response(200, content=b"#EXTM3U\n")

    cfg = cfg_with(entry(paths=["lists/de.m3u", "x y/it.m3u8"], ref="release/1"))
    got = fetch.fetch_extra_m3u(cfg, tmp_path, client_for(handler), sleeps.append)
    assert seen[0] == "https://raw.githubusercontent.com/owner/repo/release/1/lists/de.m3u"
    assert seen[2] == "https://raw.githubusercontent.com/owner/repo/release/1/x%20y/it.m3u8"
    assert sleeps == [1.0]  # one retry with the configured backoff
    assert [g.reference_url for g in got] == [
        "https://github.com/owner/repo/blob/release/1/lists/de.m3u",
        "https://github.com/owner/repo/blob/release/1/x%20y/it.m3u8",
    ]
    assert all(g.licence == "MIT" and g.path.read_bytes() == b"#EXTM3U\n" for g in got)


def test_download_enforces_the_size_cap_and_the_host_allow_list(tmp_path):
    big = lambda req: httpx.Response(200, content=b"x" * (1024 * 1024 + 1))  # noqa: E731
    with pytest.raises(fetch.FetchError, match="larger than 1 MB"):
        fetch.fetch_extra_m3u(cfg_with(entry(), max_playlist_mb=1), tmp_path, client_for(big), lambda s: None)

    calls = []

    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(302, headers={"location": "https://evil.example.com/a.m3u"})

    with pytest.raises(fetch.FetchError, match="refusing to fetch"):
        fetch.fetch_extra_m3u(cfg_with(entry()), tmp_path, client_for(handler), lambda s: None)
    assert len(calls) == 1  # the redirect target was never requested

    with pytest.raises(fetch.FetchError, match="refusing to fetch"):
        fetch.fetch_extra_m3u(
            cfg_with(entry(), allowed_hosts=["github.com"]), tmp_path, client_for(handler), lambda s: None
        )


def test_a_missing_file_is_skipped_but_any_other_failure_aborts(tmp_path):
    def handler(req):
        return httpx.Response(404 if req.url.path.endswith("gone.m3u") else 200, content=b"#EXTM3U\n")

    missing: list[str] = []
    cfg = cfg_with(entry(paths=["gone.m3u", "here.m3u"]))
    got = fetch.fetch_extra_m3u(cfg, tmp_path, client_for(handler), lambda s: None, missing)
    assert missing == ["demo:gone.m3u"] and [g.label for g in got] == ["demo:here.m3u"]

    with pytest.raises(fetch.FetchError, match="HTTP 403"):
        fetch.fetch_extra_m3u(cfg, tmp_path, client_for(lambda r: httpx.Response(403)), lambda s: None)
    with pytest.raises(fetch.FetchError, match="giving up"):
        fetch.fetch_extra_m3u(cfg, tmp_path, client_for(lambda r: httpx.Response(500)), lambda s: None)


# ------------------------------------------------------------------------------------------------- discovery pipeline
CHANNELS = (
    "id,name,alt_names,network,owners,country,categories,is_nsfw,launched,closed,replaced_by,website\n"
    "DemoNews.de,Demo News,,,Demo Media,DE,news,FALSE,,,,https://www.demonews.de\n"
    "OtherTV.de,Other TV,,,Other Media,DE,general,FALSE,,,,https://www.othertv.de\n"
    "Kids.de,Kids Zone,,,Kids Media,DE,kids,FALSE,,,,https://www.kidszone.de\n"
    "Spicy.de,Spicy Channel,,,Spicy Media,DE,general,TRUE,,,,https://www.spicy.de\n"
    "Gone.de,Gone TV,,,Gone Media,DE,general,FALSE,,2020-01-01,,https://www.gone.de\n"
    "Buy.de,Buy Now,,,Buy Media,DE,shop,FALSE,,,,https://www.buynow.de\n"
    "Pray.de,Pray Net,,,Pray Media,DE,religious,FALSE,,,,https://www.praynet.de\n"
    "Blocked.de,Blocked TV,,,Blocked Media,DE,general,FALSE,,,,https://www.blockedtv.de\n"
    "Tok.de,Token TV,,,Token Media,DE,general,FALSE,,,,https://www.tokentv.de\n"
    "Ref.de,Referrer TV,,,Ref Media,DE,general,FALSE,,,,https://www.referrertv.de\n"
    "Drm.de,Drm TV,,,Drm Media,DE,general,FALSE,,,,https://www.drmtv.de\n"
    "Pipe.de,Pipe TV,,,Pipe Media,DE,general,FALSE,,,,https://www.pipetv.de\n"
    "Ip.de,Ip TV,,,Ip Media,DE,general,FALSE,,,,https://www.iptvde.de\n"
    "Third.de,Third TV,,,Third Media,DE,general,FALSE,,,,https://www.thirdtv.de\n"
)
FEEDS = "channel,id,name,is_main,broadcast_area,timezones,languages,format\n" + "".join(
    f"{c}.de,SD,SD,TRUE,c/DE,,deu,576i\n"
    for c in (
        "DemoNews",
        "OtherTV",
        "Kids",
        "Spicy",
        "Gone",
        "Buy",
        "Pray",
        "Blocked",
        "Tok",
        "Ref",
        "Drm",
        "Pipe",
        "Ip",
        "Third",
    )
)
BLOCK = "channel,reason,ref\nBlocked.de,dmca,x\n"
# iptv-org lists Demo News on its own host and Other TV on a restream host.
ORG = (
    "#EXTM3U\n"
    '#EXTINF:-1 tvg-id="DemoNews.de@SD",Demo News (1080p)\nhttps://live.demonews.de/org/master.m3u8\n'
    '#EXTINF:-1 tvg-id="OtherTV.de@SD",Other TV\nhttps://cdn.thirdparty-restream.com/other.m3u8\n'
)
# The extra list repeats Demo News (different URL), offers Other TV on its own host, and contains one entry per rule.
EXTRA = (
    "#EXTM3U\n"
    '#EXTINF:-1 tvg-id="DemoNews.de@SD",Demo News\nhttps://live.demonews.de/extra/master.m3u8\n'
    '#EXTINF:-1 tvg-id="OtherTV.de@SD",Other TV\nhttps://stream.othertv.de/live.m3u8\n'
    '#EXTINF:-1 tvg-id="Kids.de@SD",Kids Zone\nhttps://cdn.example-cdn.net/kids.m3u8\n'
    '#EXTINF:-1 tvg-id="Spicy.de@SD",Spicy\nhttps://live.spicy.de/x.m3u8\n'
    '#EXTINF:-1 tvg-id="Gone.de@SD",Gone\nhttps://live.gone.de/x.m3u8\n'
    '#EXTINF:-1 tvg-id="Buy.de@SD",Buy\nhttps://live.buynow.de/x.m3u8\n'
    '#EXTINF:-1 tvg-id="Pray.de@SD",Pray\nhttps://live.praynet.de/x.m3u8\n'
    '#EXTINF:-1 tvg-id="Blocked.de@SD",Blocked\nhttps://live.blockedtv.de/x.m3u8\n'
    '#EXTINF:-1 tvg-id="Tok.de@SD",Token\nhttps://live.tokentv.de/x.m3u8?token=abc\n'
    '#EXTINF:-1 tvg-id="Ref.de@SD" http-referrer="https://x.example",Ref\nhttps://live.referrertv.de/x.m3u8\n'
    '#EXTINF:-1 tvg-id="Drm.de@SD",Drm\n#KODIPROP:inputstream.adaptive.license_key=a:b\nhttps://live.drmtv.de/x.mpd\n'
    '#EXTINF:-1 tvg-id="Pipe.de@SD",Pipe\nhttps://live.pipetv.de/x.m3u8|User-Agent=Foo\n'
    '#EXTINF:-1 tvg-id="Ip.de@SD",Ip\nhttp://203.0.113.7/live.m3u8\n'
    '#EXTINF:-1 tvg-id="Unknown.de@SD",Unknown\nhttps://live.unknown.de/x.m3u8\n'
    '#EXTINF:-1 tvg-id="Third.de@SD",Third\nhttps://live.thirdtv.de/x.m3u8\n'
)
EXTRA_B = (
    "#EXTM3U\n"
    # same stream URL as the first extra list uses for Third TV, offered again under another channel id
    '#EXTINF:-1 tvg-id="Third.de@SD",Third TV\nhttps://live.thirdtv.de/x.m3u8\n'
    '#EXTINF:-1 tvg-id="Kids.de@SD",Kids Zone\nhttps://stream.kidszone.de/live.m3u8\n'
)


def playlists(tmp_path, monkeypatch, org=ORG, extra=EXTRA, extra_b=EXTRA_B):
    data, state = tmp_path / "data", tmp_path / "state"
    (data / "approved").mkdir(parents=True, exist_ok=True)
    (data / "pending").mkdir(exist_ok=True)
    monkeypatch.setattr(ec, "DATA", data)
    monkeypatch.setattr(ec, "STATE", state)
    streams, db, dl = tmp_path / "streams", tmp_path / "db", tmp_path / "dl"
    for d in (streams, db, dl):
        d.mkdir(exist_ok=True)
    (db / "channels.csv").write_text(CHANNELS, encoding="utf-8")
    (db / "feeds.csv").write_text(FEEDS, encoding="utf-8")
    (db / "blocklist.csv").write_text(BLOCK, encoding="utf-8")
    (streams / "de.m3u").write_text(org, encoding="utf-8")
    (dl / "a.m3u").write_text(extra, encoding="utf-8")
    (dl / "b.m3u").write_text(extra_b, encoding="utf-8")
    extras = [
        fetch.ExtraPlaylist("lista", "MIT", dl / "a.m3u", "https://github.com/o/lista/blob/main/a.m3u", "lista:a.m3u"),
        fetch.ExtraPlaylist(
            "listb", "CC0-1.0", dl / "b.m3u", "https://github.com/o/listb/blob/main/b.m3u", "listb:b.m3u"
        ),
    ]
    seen = {}

    def fake_org(cfg, dest, need=(), **kw):
        seen["org"] = need
        return {"streams": streams, "database": db}

    def fake_extra(cfg, dest, client=None, sleep=None, missing=None):
        seen["extra"] = True
        return extras

    monkeypatch.setattr(ec, "fetch_iptv_org", fake_org)
    monkeypatch.setattr(ec, "fetch_extra_m3u", fake_extra)
    return seen


def records(tmp_path):
    out = {}
    for f in (tmp_path / "data/approved/auto").glob("*.yaml"):
        for r in yaml.safe_load(f.read_text())["channels"]:
            out[r["epg_id"]] = r
    return out


def summary(tmp_path):
    return json.loads((tmp_path / "state/discovery.json").read_text())


def test_no_arguments_downloads_the_extra_sources_and_applies_every_rule(tmp_path, monkeypatch):
    seen = playlists(tmp_path, monkeypatch)
    assert ec.main(["--date", "2026-01-01"]) == 0
    assert seen["extra"] is True
    recs = records(tmp_path)
    # Only the four streams that pass every rule are admitted; every other entry of the extra list is refused.
    assert sorted(recs) == ["DemoNews.de@SD", "Kids.de@SD", "OtherTV.de@SD", "Third.de@SD"]
    st = summary(tmp_path)
    s = st["sources"]["lista"]
    assert s["streams"] == 15
    assert s["nsfw-or-blocklisted"] == 2  # NSFW flag and blocklist
    assert s["closed"] == 1 and s["excluded-category"] == 2  # shopping, religious
    assert s["needs-special-headers"] == 3  # referrer attribute, KODIPROP, pipe suffix
    assert s["url-policy"] == 2  # token query, IP literal
    assert s["no-database-entry"] == 1
    assert s["host-not-owned-by-broadcaster"] == 1  # Kids Zone on a generic CDN
    assert st["stats"]["admitted"] == 4


def test_first_seen_source_wins_and_provenance_points_at_the_file(tmp_path, monkeypatch):
    playlists(tmp_path, monkeypatch)
    ec.main(["--date", "2026-01-01"])
    recs = records(tmp_path)
    demo = recs["DemoNews.de@SD"]
    assert demo["stream"]["url"] == "https://live.demonews.de/org/master.m3u8"  # iptv-org is read first
    assert demo["source"]["reference_url"] == "https://github.com/iptv-org/iptv/blob/master/streams/de.m3u"
    other = recs["OtherTV.de@SD"]  # iptv-org only had a restream host, so the extra list supplies it
    assert other["stream"]["url"] == "https://stream.othertv.de/live.m3u8"
    assert other["source"]["reference_url"] == "https://github.com/o/lista/blob/main/a.m3u"
    assert other["source"]["method"] == "automated-domain-match"
    assert other["review"]["authorization_basis"] == "official-broadcaster-stream"
    # lista precedes listb: it wins Third TV, and listb's identical entry is a cross-source duplicate
    assert recs["Third.de@SD"]["source"]["reference_url"].endswith("lista/blob/main/a.m3u")
    assert recs["Kids.de@SD"]["source"]["reference_url"].endswith("listb/blob/main/b.m3u")
    st = summary(tmp_path)["sources"]
    assert st["lista"]["duplicate-channel-in-other-source"] == 1  # Demo News (iptv-org wins)
    assert st["listb"]["duplicate-channel-in-other-source"] == 1  # Third TV (lista wins)
    assert st["iptv-org"]["admitted"] == 1 and st["lista"]["admitted"] == 2 and st["listb"]["admitted"] == 1


def test_duplicate_stream_urls_are_admitted_once(tmp_path, monkeypatch):
    # Two different channel ids point at one stream: only the first (by channel id) is admitted.
    extra = EXTRA + '#EXTINF:-1 tvg-id="Kids.de@SD",Kids\nhttps://live.demonews.de/org/master.m3u8\n'
    playlists(tmp_path, monkeypatch, extra=extra)
    ec.main(["--date", "2026-01-01"])
    urls = [r["stream"]["url"] for r in records(tmp_path).values()]
    assert len(urls) == len(set(urls))


def test_rerun_with_unchanged_sources_changes_nothing(tmp_path, monkeypatch):
    playlists(tmp_path, monkeypatch)
    ec.main(["--date", "2026-01-01"])
    before = {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in sorted(tmp_path.rglob("*.y*")) + [tmp_path / "state/discovery.json"]
    }
    ec.main(["--date", "2026-06-06"])
    after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before}
    assert after == before


def test_offline_inputs_and_the_opt_out_flag_never_download_extras(tmp_path, monkeypatch):
    seen = playlists(tmp_path, monkeypatch)
    assert ec.main(["--streams", str(tmp_path / "streams"), "--database", str(tmp_path / "db")]) == 0
    assert "extra" not in seen
    assert ec.main(["--no-extra-sources", "--date", "2026-01-01"]) == 0
    assert "extra" not in seen
    assert sorted(records(tmp_path)) == ["DemoNews.de@SD"]  # iptv-org alone: the restream host stays rejected


def test_failed_extra_download_exits_nonzero_and_leaves_data_alone(tmp_path, monkeypatch, capsys):
    playlists(tmp_path, monkeypatch)

    def boom(*a, **k):
        raise fetch.FetchError("offline")

    monkeypatch.setattr(ec, "fetch_extra_m3u", boom)
    assert ec.main([]) == 1
    assert "offline" in capsys.readouterr().err
    assert not (tmp_path / "data/approved/auto").exists()


def test_rule_set_is_unchanged_by_the_extra_sources():
    # The module-level rule tables are the ones documented in SOURCE_POLICY.md section 2a.
    assert ec.EXCLUDED_CATEGORIES == {"xxx", "shop", "religious", "interactive"}
    assert ec.SANCTIONED_COUNTRIES == {"kp", "sy"}
    assert set(ec.SPECIAL_OPTION_PREFIXES) >= {"#EXTVLCOPT"}
    assert ec.owner_match("cdn-7.pishow.tv", "https://www.aljazeera.com") is None
    assert ec.owner_match("live.france24.com", "https://www.france24.com/en/") is not None
    assert not ec.check_url_policy("https://live.example.com/a.m3u8?hdnts=1").ok
    assert not ec.check_url_policy("http://203.0.113.7/a.m3u8").ok


def test_the_source_policy_and_automation_docs_describe_the_extra_sources():
    root = Path(__file__).resolve().parent.parent
    assert "extra_m3u" in (root / "docs/AUTOMATION.md").read_text(encoding="utf-8")
    assert "extra_m3u" in (root / "docs/SOURCE_POLICY.md").read_text(encoding="utf-8")
