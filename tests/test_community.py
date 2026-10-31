"""Community live tier: filters, metadata, de-duplication across tiers, exclusions, rotation, budget, lifecycle and
playlist output. All network access is mocked or replaced by local files."""

import asyncio
import csv
import dataclasses
import datetime as dt
import json
from pathlib import Path

import httpx
import pytest
from conftest import make

from nexonic import community as c
from nexonic import m3u
from nexonic.checker import check_all
from nexonic.config import CommunityConfig, DiscoveryConfig
from nexonic.fetch import ExtraPlaylist, FetchError
from nexonic.records import load_records
from nexonic.status import CheckResult, Status
from nexonic.timeutil import iso

NOW = dt.datetime(2026, 10, 28, 4, 0, 0, tzinfo=dt.UTC)

CHANNEL_COLS = "id,name,alt_names,network,owners,country,categories,is_nsfw,launched,closed,replaced_by,website"
FEED_COLS = "channel,id,name,alt_names,is_main,broadcast_area,timezones,languages,format"


def chan(cid, name, country="DE", cats="general", nsfw="FALSE", closed="", owners="", network="", website="", alt=""):
    return [
        cid,
        name,
        alt,
        network,
        owners,
        country,
        cats,
        nsfw,
        "",
        closed,
        "",
        website or f"https://{cid.lower()}.test/",
    ]


def feed(channel, fid="SD", name="SD", main="TRUE", langs="deu", fmt="720p"):
    return [channel, fid, name, "", main, "c/DE", "", langs, fmt]


def write_csv(path: Path, header: str, rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header.split(","))
        w.writerows(rows)


def extinf(tvg, title, url, opts=(), extra=""):
    lines = [f'#EXTINF:-1 tvg-id="{tvg}"{extra},{title}', *opts, url]
    return "\n".join(lines)


@pytest.fixture
def sources(tmp_path):
    """Build an iptv-org style input (streams dir + database dir) and return a helper to run the catalogue build."""
    streams, db = tmp_path / "streams", tmp_path / "db"
    streams.mkdir()
    db.mkdir()

    class Src:
        channels: list = []
        feeds: list = []
        blocked: list = []
        logos: list = []
        files: dict = {}

        def write(self):
            write_csv(db / "channels.csv", CHANNEL_COLS, self.channels)
            write_csv(db / "feeds.csv", FEED_COLS, self.feeds)
            write_csv(db / "blocklist.csv", "channel,reason,ref", self.blocked)
            write_csv(db / "logos.csv", "channel,feed,in_use,tags,width,height,format,url", self.logos)
            for name, entries in self.files.items():
                (streams / name).write_text("#EXTM3U\n" + "\n".join(entries) + "\n", encoding="utf-8")

        def build(self, **kw):
            self.write()
            kw.setdefault("cfg", CommunityConfig())
            kw.setdefault("built_at", "2026-10-28T03:00:00Z")
            return c.build_catalog(streams, db, **kw)

    s = Src()
    s.channels, s.feeds, s.blocked, s.logos, s.files = [], [], [], [], {}
    s.dir, s.db = streams, db
    return s


def names(catalog):
    return {r[3] for r in catalog["streams"]}


# --------------------------------------------------------------------------------------------------------- filters
def test_each_filter_drops_what_it_should_and_the_report_counts_them(sources):
    ch = sources.channels
    ch += [
        chan("Good.de", "Good TV"),
        chan("Adult.de", "Adult Thing", nsfw="TRUE"),
        chan("Dmca.de", "Dmca TV"),
        chan("Closed.de", "Closed TV", closed="2020-01-01"),
        chan("Ref.de", "Referrer TV"),
        chan("Opt.de", "Option TV"),
        chan("Pipe.de", "Pipe TV"),
        chan("Token.de", "Token TV"),
        chan("Ip.de", "Ip TV"),
        chan("Port.de", "Port TV"),
        chan("Rtmp.de", "Rtmp TV"),
        chan("File.de", "File TV"),
        chan("Rt.ru", "Russia Today", country="RU"),
        chan("Strong.de", "Hot Sex Channel"),
        chan("Weak.de", "Midnight Love"),
        chan("Xxx.de", "Plain TV", cats="xxx"),
        chan("Nowhere.zz", "Nowhere TV", country="ZZ"),
        chan("Takedown.de", "Takedown TV"),
    ]
    sources.feeds = [feed(r[0]) for r in ch]
    sources.blocked = [["Dmca.de", "dmca", "https://example.test/issue/1"]]
    sources.files = {
        "de.m3u": [
            extinf("Good.de@SD", "Good TV (720p)", "https://cdn.good.test/live/index.m3u8"),
            extinf("Adult.de@SD", "Adult", "https://cdn.a.test/index.m3u8"),
            extinf("Dmca.de@SD", "Dmca", "https://cdn.b.test/index.m3u8"),
            extinf("Closed.de@SD", "Closed", "https://cdn.c.test/index.m3u8"),
            extinf("Ref.de@SD", "Ref", "https://cdn.d.test/index.m3u8", extra=' http-referrer="https://x.test"'),
            extinf("Opt.de@SD", "Opt", "https://cdn.e.test/index.m3u8", opts=["#EXTVLCOPT:http-user-agent=Mozilla"]),
            extinf("Pipe.de@SD", "Pipe", "https://cdn.f.test/index.m3u8|User-Agent=x"),
            extinf("Token.de@SD", "Token", "https://cdn.g.test/index.m3u8?token=abc"),
            extinf("Ip.de@SD", "Ip", "http://93.184.216.34/index.m3u8"),
            extinf("Port.de@SD", "Port", "http://cdn.h.test:8081/index.m3u8"),
            extinf("Rtmp.de@SD", "Rtmp", "rtmp://cdn.i.test/live"),
            extinf("File.de@SD", "File", "https://cdn.j.test/movie.mp4"),
            extinf("Rt.ru@SD", "Rt", "https://cdn.k.test/index.m3u8"),
            extinf("Strong.de@SD", "Strong", "https://cdn.l.test/index.m3u8"),
            extinf("Weak.de@SD", "Weak", "https://cdn.m.test/index.m3u8"),
            extinf("Xxx.de@SD", "Xxx", "https://cdn.n.test/index.m3u8"),
            extinf("Nowhere.zz@SD", "Nowhere", "https://cdn.o.test/index.m3u8"),
            extinf("Takedown.de@SD", "Takedown", "https://cdn.p.test/index.m3u8"),
            extinf("Unknown.de@SD", "Not in the database", "https://cdn.q.test/index.m3u8"),
        ]
    }
    ex = c.Exclusions(channels={"takedown.de"})
    cat, rep = sources.build(exclusions=ex)
    assert names(cat) == {"Good TV"}
    assert rep["read"] == 19
    after = rep["after"]
    assert [after[f] for f in c.FILTERS] == sorted((after[f] for f in c.FILTERS), reverse=True)
    assert after["has-database-entry"] == 18
    assert after["not-nsfw-or-blocklisted"] == 15  # nsfw flag, dmca blocklist and xxx category
    assert after["not-closed"] == 14
    assert after["no-special-headers"] == 11
    assert after["url-policy"] == 7  # token, IP host, port 8081 and rtmp
    assert after["hls-or-dash"] == 6
    assert after["policy-exclusions"] == 5  # sanctioned broadcaster
    assert after["adult-screening-pass"] == 3  # strong term rejected, weak term quarantined
    assert after["community-exclusions"] == 1  # unknown country and the takedown entry are dropped
    d = rep["dropped"]
    assert d["no-database-entry"] == 1 and d["closed"] == 1 and d["needs-special-headers"] == 3
    assert d["url-policy-port"] == 1 and d["url-policy-ip-host"] == 1 and d["url-policy-token"] == 1
    assert d["adult-screening-reject"] == 1 and d["adult-screening-quarantine"] == 1
    assert d["community-exclusion"] == 1 and d["unknown-country"] == 1
    assert rep["catalog"] == 1


def test_adult_screening_reuses_the_moderation_module(sources):
    sources.channels = [chan("Plain.de", "Plain TV"), chan("Sexy.de", "Sexy Nights")]
    sources.feeds = [feed("Plain.de"), feed("Sexy.de")]
    sources.files = {
        "de.m3u": [
            extinf("Plain.de@SD", "Plain", "https://a.test/i.m3u8"),
            extinf("Sexy.de@SD", "S", "https://b.test/i.m3u8"),
        ]
    }
    cat, rep = sources.build()
    assert names(cat) == {"Plain TV"} and rep["dropped"]["adult-screening-reject"] == 1


def test_restream_hosts_follow_the_config_but_dynamic_dns_never_passes(sources):
    sources.channels = [chan("A.de", "A TV"), chan("B.de", "B TV"), chan("C.de", "C TV")]
    sources.feeds = [feed("A.de"), feed("B.de"), feed("C.de")]
    sources.files = {
        "de.m3u": [
            extinf("A.de@SD", "A", "https://x.pishow.tv/live/a.m3u8"),
            extinf("B.de@SD", "B", "https://b.duckdns.org/live/b.m3u8"),
            extinf("C.de@SD", "C", "https://cdn.c.test/c.m3u8"),
        ]
    }
    cat, _ = sources.build(cfg=CommunityConfig(allow_restream_hosts=True))
    assert names(cat) == {"A TV", "C TV"}
    cat, rep = sources.build(cfg=CommunityConfig(allow_restream_hosts=False))
    assert names(cat) == {"C TV"} and rep["dropped"]["url-policy-restream-or-dynamic-dns"] == 2


def test_aggregator_hosts_are_allowed_without_tokens(sources):
    sources.channels = [chan("A.de", "A TV"), chan("B.de", "B TV")]
    sources.feeds = [feed("A.de"), feed("B.de")]
    sources.files = {
        "de.m3u": [
            extinf("A.de@SD", "A", "https://a.mediatailor.us-east-1.amazonaws.com/v1/master/x/playlist.m3u8"),
            extinf("B.de@SD", "B", "https://b.mediatailor.us-east-1.amazonaws.com/v1/master/y/playlist.m3u8?token=1"),
        ]
    }
    cat, _ = sources.build()
    assert names(cat) == {"A TV"}


# --------------------------------------------------------------------------------------------------------- metadata
def test_metadata_comes_from_the_database(sources):
    sources.channels = [
        chan("Shop.de", "Shop TV", cats="shop;weird", owners="Owner Co"),
        chan("Alt.de", "Alt TV", cats="news;documentary"),
        chan("Nolang.de", "Nolang TV"),
    ]
    sources.feeds = [
        feed("Shop.de", langs="deu;eng;xxx"),
        feed("Alt.de", "HD", "Spanish feed", main="FALSE", langs="spa", fmt="1080i"),
        feed("Alt.de", "SD", "SD", main="TRUE", langs="deu"),
        feed("Nolang.de", langs="qqq"),
    ]
    sources.logos = [
        ["Shop.de", "", "TRUE", "", "1", "1", "PNG", "https://logos.test/shop.png"],
        ["Alt.de", "HD", "TRUE", "", "1", "1", "PNG", "https://logos.test/alt-hd.png"],
        ["Alt.de", "", "FALSE", "", "1", "1", "PNG", "https://logos.test/unused.png"],
        ["Nolang.de", "", "TRUE", "", "1", "1", "PNG", "http://user:pw@logos.test/bad.png"],
    ]
    sources.files = {
        "de.m3u": [
            extinf("Shop.de@SD", "Shop TV (480p) [Geo-blocked]", "https://s.test/i.m3u8"),
            extinf("Alt.de@HD", "Alt TV", "https://a.test/i.m3u8"),
            extinf("Nolang.de@SD", "Nolang", "https://n.test/i.m3u8"),
        ]
    }
    cat, _ = sources.build()
    rows = {r[1]: c.CStream(*r) for r in cat["streams"]}
    shop, alt, nolang = rows["Shop.de"], rows["Alt.de"], rows["Nolang.de"]
    assert shop.cc == "de" and shop.lg == ["de", "en"] and shop.ct == ["lifestyle"] and shop.q == 480
    assert shop.fl & c.FLAG_GEO_BLOCKED and shop.lo == "https://logos.test/shop.png"
    assert shop.epg_id == "Shop.de@SD" and shop.id.startswith("Shop.de~") and len(shop.id) == len("Shop.de~") + 8
    assert alt.name == "Alt TV (Spanish feed)" and alt.lg == ["es"] and alt.q == 1080
    assert alt.ct == ["news", "documentary"] and alt.lo == "https://logos.test/alt-hd.png"
    assert nolang.lg == [] and nolang.ct == ["general"] and nolang.lo == ""


def test_ids_are_stable_and_independent_of_input_order(sources):
    sources.channels = [chan("A.de", "A TV"), chan("B.de", "B TV")]
    sources.feeds = [feed("A.de"), feed("B.de")]
    a, b = extinf("A.de@SD", "A", "https://a.test/i.m3u8"), extinf("B.de@SD", "B", "https://b.test/i.m3u8")
    sources.files = {"de.m3u": [a, b]}
    first, _ = sources.build()
    sources.files = {"de.m3u": [b, a]}
    second, _ = sources.build()
    assert [r[0] for r in first["streams"]] == [r[0] for r in second["streams"]]
    assert c.stream_id("A.de", "http://a.test/i.m3u8/") == c.stream_id("A.de", "https://a.test/i.m3u8")


def test_catalog_round_trip_one_row_per_line(sources, tmp_path):
    sources.channels = [chan("A.de", "A TV"), chan("B.de", "B TV")]
    sources.feeds = [feed("A.de"), feed("B.de")]
    sources.files = {
        "de.m3u": [extinf("A.de@SD", "A", "https://a.test/i.m3u8"), extinf("B.de@SD", "B", "https://b.test/i.m3u8")]
    }
    cat, _ = sources.build()
    path = tmp_path / "catalog.json"
    c.save_catalog(cat, path)
    text = path.read_text(encoding="utf-8")
    assert len(text.splitlines()) < 12 and not path.with_suffix(".tmp").exists()
    assert json.loads(text)["streams"] == cat["streams"]
    assert c.load_catalog(path)["streams"] == cat["streams"]
    path.write_text('{"schema": 99}', encoding="utf-8")
    assert c.load_catalog(path) is None
    assert c.load_catalog(tmp_path / "missing.json") is None


# --------------------------------------------------------------------------------------------------------- dedup
def test_duplicates_inside_the_tier(sources):
    sources.channels = [chan("A.de", "A TV"), chan("B.de", "B TV")]
    sources.feeds = [feed("A.de"), feed("B.de")]
    sources.files = {
        "de.m3u": [
            extinf("A.de@SD", "A (480p)", "https://a.test/low.m3u8"),
            extinf("A.de@SD", "A (1080p)", "https://a.test/high.m3u8"),
            extinf("A.de@SD", "A (1080p) [Not 24/7]", "https://a.test/part.m3u8"),
            extinf("B.de@SD", "B", "https://shared.test/same.m3u8"),
            extinf("A.de@SD", "A again", "http://shared.test/same.m3u8/"),
        ]
    }
    cat, rep = sources.build()
    got = {r[1]: r[4] for r in cat["streams"]}
    assert got["A.de"] == "https://a.test/high.m3u8"  # best-ranked stream of the channel feed wins
    assert rep["deduplicated"]["duplicate-channel"] == 2 and rep["deduplicated"]["duplicate-url"] == 1
    cat2, _ = sources.build(cfg=CommunityConfig(streams_per_channel=2))
    assert sorted(r[4] for r in cat2["streams"] if r[1] == "A.de") == [
        "https://a.test/high.m3u8",
        "https://a.test/low.m3u8",
    ]


def test_official_tier_wins_across_stream_channel_name_and_maintainer_decisions(sources, dataset):
    official = [
        make(id="off-url", name="Official One", epg_id="OffUrl.de", **{"stream.url": "https://same.test/o.m3u8"}),
        make(id="off-epg", name="Official Two", epg_id="OffEpg.de@HD", **{"stream.url": "https://x.test/2.m3u8"}),
        make(id="off-name", name="Same Name", epg_id=None, **{"stream.url": "https://x.test/3.m3u8"}),
    ]
    rejected = [
        make(
            id="rej",
            name="Rejected",
            epg_id="Rej.de",
            **{"stream.url": "https://rej.test/r.m3u8", "review.status": "rejected"},
        )
    ]
    rejected[0]["review"].update(status="rejected", rejection_reason="rights holder asked")
    rejected[0]["review"]["authorization_basis"] = "none"
    ctx = c.official_context(load_records(dataset(official, rejected=rejected)))
    sources.channels = [chan(f"{n}.de", f"{n} TV") for n in ("U", "E", "N", "R", "Free")]
    sources.channels[2][1] = "Same Name"
    sources.channels[4][1] = "Free TV"
    sources.channels[1][0] = "OffEpg.de"
    sources.feeds = [feed(r[0]) for r in sources.channels]
    sources.files = {
        "de.m3u": [
            extinf("U.de@SD", "U", "https://same.test/o.m3u8"),
            extinf("OffEpg.de@SD", "E", "https://e.test/i.m3u8"),
            extinf("N.de@SD", "N", "https://n.test/i.m3u8"),
            extinf("R.de@SD", "R", "https://rej.test/r.m3u8"),
            extinf("Free.de@SD", "Free", "https://free.test/i.m3u8"),
        ]
    }
    cat, rep = sources.build(official=ctx)
    assert names(cat) == {"Free TV"}
    assert rep["deduplicated"] == {
        "official-duplicate-channel": 1,
        "official-duplicate-name": 1,
        "official-duplicate-stream": 2,
    }
    # The same rule runs at generation time, whatever the catalogue holds.
    kept, removed = c.apply_tier_rules(c.catalog_streams(cat), ctx, c.Exclusions())
    assert [s.name for s in kept] == ["Free TV"] and removed == {}
    again = c.CStream(
        "X~1", "OffEpg.de", "SD", "Other", "https://o.test/i.m3u8", "de", [], ["news"], 0, "", 0, "iptv-org"
    )
    kept, removed = c.apply_tier_rules([again], ctx, c.Exclusions())
    assert kept == [] and removed == {"official-duplicate": 1}


# --------------------------------------------------------------------------------------------------------- exclusions
def test_exclusions_file_urls_hosts_channels_and_ids(tmp_path):
    f = tmp_path / "x.yaml"
    f.write_text(
        "urls: ['https://cdn.test/a.m3u8']\nhosts: ['Blocked.Example']\nchannels: ['Chan.de']\nvod: ['Some_Item']\n",
        encoding="utf-8",
    )
    ex = c.load_exclusions(f)
    assert ex.reason("Other.de", "Other.de~1", "http://cdn.test/a.m3u8/") == "url"  # scheme and slash ignored
    assert ex.reason("Other.de", "Other.de~1", "https://a.blocked.example/x.m3u8") == "host"
    assert ex.reason("Other.de", "Other.de~1", "https://notblocked.example/x.m3u8") is None
    assert ex.reason("chan.de", "x", "https://ok.test/a.m3u8") == "channel"
    assert ex.reason("Other.de", "chan.de", "https://ok.test/a.m3u8") == "channel"
    assert "some_item" in ex.vod
    assert c.load_exclusions(tmp_path / "missing.yaml") == c.Exclusions()
    for bad in ("urls: not-a-list\n", "surprise: []\n", "- just\n- a list\n"):
        f.write_text(bad, encoding="utf-8")
        with pytest.raises(ValueError):
            c.load_exclusions(f)


def test_shipped_exclusions_file_is_valid_and_empty_by_default():
    ex = c.load_exclusions()
    assert isinstance(ex, c.Exclusions)


def test_exclusions_remove_streams_at_generation_time(sources):
    sources.channels = [chan("A.de", "A TV"), chan("B.de", "B TV")]
    sources.feeds = [feed("A.de"), feed("B.de")]
    sources.files = {
        "de.m3u": [extinf("A.de@SD", "A", "https://a.test/i.m3u8"), extinf("B.de@SD", "B", "https://b.test/i.m3u8")]
    }
    cat, _ = sources.build()
    cfg = CommunityConfig()
    plan = c.plan_community(cat, {}, c.OfficialContext(), c.Exclusions(hosts={"a.test"}), cfg)
    urls = [e.url for e in m3u.parse(plan.files["playlists/community/untested.m3u"])]
    assert urls == ["https://b.test/i.m3u8"]
    assert plan.stats["removed_at_generation"] == {"excluded-by-takedown-list": 1}


# --------------------------------------------------------------------------------------------------------- rotation
def stream(n, host="h%d.test", cc="de", **kw):
    host = host % n if "%d" in host else host
    return c.CStream(
        f"Ch{n}.{cc}~{n:08x}",
        f"Ch{n}.{cc}",
        "SD",
        f"Ch {n}",
        f"https://{host}/{n}.m3u8",
        cc,
        ["de"],
        ["news"],
        0,
        "",
        0,
        "iptv-org",
    )


def rows(*items):
    return [[iso(NOW - dt.timedelta(**when)), code, 5, 100, 0] for when, code in items]


def test_rotation_prefers_never_checked_then_oldest(monkeypatch):
    cfg = CommunityConfig(max_checks_per_run=100)
    streams = [stream(i) for i in range(6)]
    history = {
        streams[0].id: rows(({"days": 5}, "W")),
        streams[1].id: rows(({"days": 2}, "W")),
        streams[2].id: rows(({"hours": 3}, "W")),  # checked too recently: not due
        streams[3].id: rows(({"days": 9}, "W")),
    }
    chosen = c.select_for_check(streams, history, NOW, cfg)
    ids = [s.id for s in chosen]
    assert set(ids[:2]) == {streams[4].id, streams[5].id}  # never checked first
    assert ids[2:] == [streams[3].id, streams[0].id, streams[1].id]  # then oldest first
    assert streams[2].id not in ids


def test_rotation_respects_failure_waiting_times_and_quarantine():
    cfg = CommunityConfig(retry_failed_days=3, retry_quarantined_days=14, quarantine_failures=2)
    a, b, q = stream(1), stream(2), stream(3)
    history = {
        a.id: rows(({"days": 1}, "U")),  # failed yesterday: waits
        b.id: rows(({"days": 4}, "U")),  # failed 4 days ago: due again
        q.id: rows(({"days": 8}, "U"), ({"days": 5}, "T"), ({"days": 4}, "U")),  # quarantined: waits 14 days
    }
    assert [s.id for s in c.select_for_check([a, b, q], history, NOW, cfg)] == [b.id]
    history[q.id] = rows(({"days": 20}, "U"), ({"days": 18}, "T"), ({"days": 16}, "U"))
    assert {s.id for s in c.select_for_check([a, b, q], history, NOW, cfg)} == {b.id, q.id}


def test_rotation_caps_total_and_per_host():
    cfg = CommunityConfig(max_checks_per_run=5, max_per_host_per_run=2)
    streams = [stream(i, host="cdn.big.test") for i in range(10)] + [stream(100 + i) for i in range(10)]
    chosen = c.select_for_check(streams, {}, NOW, cfg)
    assert len(chosen) == 5
    assert sum(1 for s in chosen if s.host == "cdn.big.test") == 2


def test_rotation_is_deterministic_and_covers_everything_over_several_runs():
    cfg = CommunityConfig(max_checks_per_run=7, max_per_host_per_run=3)
    streams = [stream(i, host=f"h{i % 4}.test") for i in range(40)]
    assert c.select_for_check(streams, {}, NOW, cfg) == c.select_for_check(list(reversed(streams)), {}, NOW, cfg)
    history: dict = {}
    when = NOW
    seen: set = set()
    for _ in range(40):
        chosen = c.select_for_check(streams, history, when, cfg)
        for s in chosen:
            history.setdefault(s.id, []).append([iso(when), "W", 5, 1, 0])
            seen.add(s.id)
        when += dt.timedelta(days=1)
    assert seen == {s.id for s in streams}


# --------------------------------------------------------------------------------------------------------- budget / run
class FakeChecker:
    def __init__(self, status=Status.VERIFIED_WORKING):
        self.calls = []
        self.status = status

    def __call__(self, chosen, cfg, budget):
        self.calls.append((len(chosen), budget))
        return [CheckResult(s.id, self.status, iso(NOW), level=5) for s in chosen]


def seeded(tmp_path, n=5):
    cat = {"schema": 1, "built_at": iso(NOW), "columns": c.COLUMNS, "streams": [list(stream(i)) for i in range(n)]}
    path = tmp_path / "catalog.json"
    c.save_catalog(cat, path)
    return path, tmp_path / "history.json"


def run(tmp_path, checker, **kw):
    cat, hist = seeded(tmp_path) if "catalog_path" not in kw else (kw.pop("catalog_path"), tmp_path / "history.json")
    kw.setdefault("cfg", CommunityConfig())
    return c.run_daily(
        DiscoveryConfig(),
        kw.pop("cfg"),
        c.OfficialContext(),
        c.Exclusions(),
        now=NOW,
        catalog_path=cat,
        history_path=hist,
        log=lambda *_: None,
        checker=checker,
        **kw,
    ), hist


def test_run_checks_one_slice_and_records_compact_history(tmp_path):
    checker = FakeChecker()
    summary, hist = run(tmp_path, checker)
    assert summary["selected"] == 5 and summary["checked"] == 5 and checker.calls == [(5, 1500.0)]
    data = json.loads(hist.read_text(encoding="utf-8"))
    assert len(data["streams"]) == 5
    row = next(iter(data["streams"].values()))[0]
    assert row[1] == "W" and row[2] == 5  # [checked_at, status code, level, latency, height]


def test_budget_is_limited_by_the_shared_deadline(tmp_path):
    cfg = CommunityConfig(run_budget_seconds=1200, total_deadline_minutes=44)
    checker = FakeChecker()
    run(tmp_path, checker, cfg=cfg, elapsed_seconds=41 * 60)
    assert checker.calls == [(5, 180.0)]  # 44 min deadline minus 41 min already used by the official run


def test_no_check_starts_when_the_deadline_has_passed(tmp_path):
    checker = FakeChecker()
    summary, hist = run(tmp_path, checker, cfg=CommunityConfig(total_deadline_minutes=44), elapsed_seconds=44 * 60)
    assert checker.calls == [] and summary["budget_seconds"] == 0 and not hist.exists()


def test_budget_override_and_check_cap(tmp_path):
    checker = FakeChecker()
    run(tmp_path, checker, cfg=CommunityConfig(max_checks_per_run=2), budget_override=90)
    assert checker.calls == [(2, 90)]


def test_not_tested_results_are_not_recorded(tmp_path):
    class Late(FakeChecker):
        def __call__(self, chosen, cfg, budget):
            return [CheckResult(s.id, Status.NOT_TESTED, iso(NOW), error="run time budget exhausted") for s in chosen]

    summary, hist = run(tmp_path, Late())
    assert summary["checked"] == 0 and json.loads(hist.read_text(encoding="utf-8"))["streams"] == {}


def test_history_keeps_only_the_last_rows_and_drops_retired_streams():
    keep = 3
    old = {
        "gone~1": [["2026-10-01T00:00:00Z", "W", 5, 1, 0]],
        "a~1": [[f"2026-10-0{d}T00:00:00Z", "W", 5, 1, 0] for d in range(1, 4)],
    }
    new = [
        CheckResult("a~1", Status.UNAVAILABLE, "2026-10-10T00:00:00Z"),
        CheckResult("b~1", Status.TIMEOUT, "2026-10-10T00:00:00Z"),
    ]
    merged = c.merge_results(old, new, keep, {"a~1", "b~1"})
    assert "gone~1" not in merged and len(merged["a~1"]) == 3 and merged["a~1"][-1][1] == "U"
    assert merged["b~1"][0][1] == "T"


def test_a_failing_checker_or_download_never_breaks_the_caller(tmp_path):
    def broken(disc, tmp, log):
        raise FetchError("boom")

    path = tmp_path / "none.json"
    summary, _ = run(tmp_path, FakeChecker(), catalog_path=path, downloader=broken)
    assert summary["catalog"] == 0


def test_stale_catalogue_refresh_keeps_the_last_good_snapshot(tmp_path, sources):
    sources.channels = [chan(f"C{i}.de", f"Chan {i}") for i in range(4)]
    sources.feeds = [feed(r[0]) for r in sources.channels]
    sources.files = {"de.m3u": [extinf(f"C{i}.de@SD", "x", f"https://c{i}.test/i.m3u8") for i in range(4)]}
    sources.write()

    def downloader(disc, tmp, log):
        return sources.dir, sources.db, [], "archive"

    path = tmp_path / "catalog.json"
    cfg = CommunityConfig()
    good = c.refresh_catalog(
        DiscoveryConfig(),
        cfg,
        c.OfficialContext(),
        c.Exclusions(),
        now=NOW,
        path=path,
        downloader=downloader,
        log=lambda *_: None,
    )
    assert len(good["streams"]) == 4 and path.exists()

    # a download failure keeps the snapshot
    def failing(disc, tmp, log):
        raise FetchError("down")

    kept = c.refresh_catalog(
        DiscoveryConfig(),
        cfg,
        c.OfficialContext(),
        c.Exclusions(),
        now=NOW,
        path=path,
        downloader=failing,
        log=lambda *_: None,
    )
    assert kept["streams"] == good["streams"]
    # an implausibly small rebuild (here one stream out of four) is rejected
    sources.files = {"de.m3u": [extinf("C0.de@SD", "x", "https://c0.test/i.m3u8")]}
    sources.write()
    kept = c.refresh_catalog(
        DiscoveryConfig(),
        cfg,
        c.OfficialContext(),
        c.Exclusions(),
        now=NOW,
        path=path,
        downloader=downloader,
        log=lambda *_: None,
    )
    assert len(kept["streams"]) == 4 and len(c.load_catalog(path)["streams"]) == 4
    # an empty rebuild is rejected as well
    sources.files = {"de.m3u": []}
    sources.write()
    kept = c.refresh_catalog(
        DiscoveryConfig(),
        cfg,
        c.OfficialContext(),
        c.Exclusions(),
        now=NOW,
        path=path,
        downloader=downloader,
        log=lambda *_: None,
    )
    assert len(kept["streams"]) == 4


def test_catalogue_is_only_rebuilt_when_stale(tmp_path):
    path, _ = seeded(tmp_path)
    calls = []

    def downloader(disc, tmp, log):
        calls.append(1)
        raise FetchError("not needed")

    run(tmp_path, FakeChecker(), catalog_path=path, downloader=downloader)
    assert calls == []  # built an instant ago
    cfg = CommunityConfig(refresh_max_age_hours=0.0001)
    c.run_daily(
        DiscoveryConfig(),
        cfg,
        c.OfficialContext(),
        c.Exclusions(),
        now=NOW + dt.timedelta(hours=1),
        catalog_path=path,
        history_path=tmp_path / "h.json",
        log=lambda *_: None,
        downloader=downloader,
        checker=FakeChecker(),
    )
    assert calls == [1]


def test_download_sources_falls_back_to_raw_files(tmp_path):
    seen = []

    def archive(cfg, dest):
        raise FetchError("403")

    def raw(cfg, dest):
        seen.append(dest)
        return {"streams": dest / "s", "database": dest / "d"}

    def extra(cfg, dest, missing=None):
        missing.append("gone:x.m3u")
        return [ExtraPlaylist("e", "MIT", tmp_path / "e.m3u", "u", "e:x")]

    logs = []
    s, d, extras, mode = c.download_sources(
        DiscoveryConfig(), tmp_path, logs.append, fetch_archive=archive, fetch_raw=raw, fetch_extra=extra
    )
    assert mode == "raw" and s.name == "s" and len(extras) == 1
    assert any("trying raw" in m for m in logs) and any("gone:x.m3u" in m for m in logs)


# --------------------------------------------------------------------------------------------------------- checker reuse
def test_the_shared_checker_verifies_community_targets_and_applies_the_restream_setting():
    master = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=1280x720\nlo.m3u8\n"
    media = "#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6,\ns1.ts\n"
    ts = bytes([0x47] + [0] * 187) * 3

    def handler(request):
        p = request.url.path
        if p.endswith("master.m3u8"):
            return httpx.Response(200, text=master, headers={"content-type": "application/vnd.apple.mpegurl"})
        if p.endswith("lo.m3u8"):
            return httpx.Response(200, text=media, headers={"content-type": "application/vnd.apple.mpegurl"})
        return httpx.Response(206, content=ts, headers={"content-type": "video/mp2t"})

    restream = c.CStream(
        "R~1", "R.de", "SD", "R", "https://edge.pishow.tv/live/master.m3u8", "de", [], ["news"], 0, "", 0, "x"
    )
    plain = stream(1, host="live.example-host.test")
    plain = plain._replace(url="https://live.example-host.test/master.m3u8")

    def go(cfg):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)

        async def inner():
            async with client:
                targets = [c.CheckTarget.of(restream), c.CheckTarget.of(plain)]
                limits = c.limits_for(cfg, 60)
                limits.per_host_interval = 0
                return await check_all(targets, limits, client=client, resolver=lambda h, p: ["93.184.216.34"])

        return asyncio.run(inner())

    allowed = go(CommunityConfig(allow_restream_hosts=True))
    assert [r.status for r in allowed] == [Status.VERIFIED_WORKING, Status.VERIFIED_WORKING]
    assert allowed[1].details["max_resolution"] == "720p" and allowed[1].level == 5  # manifest -> variant -> segment
    refused = go(CommunityConfig(allow_restream_hosts=False))
    assert refused[0].status is Status.INVALID_STREAM and refused[1].status is Status.VERIFIED_WORKING


def test_limits_use_the_community_settings_without_ffprobe():
    cfg = CommunityConfig(concurrency=500, max_concurrency=64, timeout=5, per_host_interval=2, channel_timeout=20)
    lim = c.limits_for(cfg, 99)
    assert (lim.concurrency, lim.timeout, lim.per_host_interval, lim.channel_timeout, lim.run_budget) == (
        64,
        5,
        2,
        20,
        99,
    )
    assert lim.use_ffprobe is False and lim.retries == 0


# --------------------------------------------------------------------------------------------------------- lifecycle
def evaluate(rows_by_id, streams, cfg=None):
    cfg = cfg or CommunityConfig()
    ref = c.reference_time(rows_by_id) or NOW
    return {e.stream.id: e for e in c.evaluate_streams(streams, rows_by_id, cfg, ref)}


def test_community_lifecycle_states():
    cfg = CommunityConfig(verified_days=7, quarantine_failures=2, quarantine_distinct_days=2)
    s = [stream(i) for i in range(8)]
    history = {
        s[0].id: rows(({"days": 1}, "W")),  # worked yesterday -> verified, working
        s[1].id: rows(({"days": 10}, "W")),  # worked, but not within the window -> untested
        s[2].id: [],  # never checked -> untested
        s[3].id: rows(({"days": 3}, "W"), ({"days": 1}, "T")),  # recent success then one failure -> still verified
        s[4].id: rows(({"days": 6}, "U"), ({"days": 1}, "U")),  # two failures on two days -> quarantined
        s[5].id: rows(({"days": 1}, "G")),  # geo-restricted from the checker -> untested, restricted
        s[6].id: rows(({"days": 1}, "U")),  # one failure, never worked -> held back
        s[7].id: rows(({"days": 6}, "U"), ({"days": 1}, "U"), ({"hours": 1}, "W")),  # restored by a success
    }
    history = {k: v for k, v in history.items() if v}
    ev = evaluate(history, s, cfg)
    state = {i: ev[x.id].state for i, x in enumerate(s)}
    assert state == {
        0: "verified",
        1: "untested",
        2: "untested",
        3: "verified",
        4: "failing",
        5: "untested",
        6: "failing",
        7: "verified",
    }
    assert ev[s[0].id].lifecycle.state.value == "working"
    assert ev[s[3].id].lifecycle.state.value == "intermittent"
    assert ev[s[4].id].lifecycle.quarantined and ev[s[4].id].lifecycle.state.value == "unreachable"
    assert ev[s[5].id].lifecycle.state.value == "restricted"
    assert ev[s[7].id].lifecycle.restored_at is not None and not ev[s[7].id].lifecycle.quarantined
    assert ev[s[2].id].lifecycle.state.value == "unknown" and ev[s[2].id].last_checked is None


def test_verified_window_is_configurable():
    s = [stream(1)]
    history = {s[0].id: rows(({"days": 10}, "W"), ({"hours": 1}, "W"))}
    assert evaluate(history, s, CommunityConfig(verified_days=7))[s[0].id].state == "verified"
    old = {s[0].id: rows(({"days": 10}, "W"))}
    # the reference time is the newest check anywhere, so add another stream that was checked just now
    other = stream(2)
    old[other.id] = rows(({"hours": 1}, "W"))
    assert evaluate(old, [s[0], other], CommunityConfig(verified_days=7))[s[0].id].state == "untested"
    assert evaluate(old, [s[0], other], CommunityConfig(verified_days=14))[s[0].id].state == "verified"


# --------------------------------------------------------------------------------------------------------- playlists
def planned(streams, history, cfg=None, exclusions=None, merge=False):
    """The separate community layout unless merge=True (merge_into_main, the default in config)."""
    cat = {"schema": 1, "built_at": iso(NOW), "columns": c.COLUMNS, "streams": [list(x) for x in streams]}
    cfg = dataclasses.replace(cfg or CommunityConfig(), merge_into_main=merge)
    return c.plan_community(cat, history, c.OfficialContext(), exclusions or c.Exclusions(), cfg)


def test_merge_into_main_puts_only_verified_streams_in_the_main_playlists():
    s = [stream(0, cc="de"), stream(1, cc="de"), stream(2, cc="fr")]
    history = {s[0].id: rows(({"hours": 2}, "W")), s[2].id: rows(({"hours": 2}, "U"))}
    p = planned(s, history, merge=True)
    assert set(p.files) == {"playlists/community/untested.m3u"}
    assert {e.url for e in m3u.parse(p.files["playlists/community/untested.m3u"])} == {s[1].url}
    kind, key, _, entries = p.merge["playlists/all.m3u"]
    assert (kind, key) == ("global", "all") and [e.url for e in entries] == [s[0].url]
    assert all(e.attrs["x-tier"] == "community" and e.attrs["x-status"] == "verified" for e in entries)
    assert "playlists/countries/de.m3u" in p.merge and "playlists/countries/fr.m3u" not in p.merge
    assert p.stats["merged_into_main"] is True


def test_verified_untested_and_failing_are_kept_apart():
    s = [stream(0, cc="de"), stream(1, cc="de"), stream(2, cc="fr"), stream(3, cc="fr")]
    history = {
        s[0].id: rows(({"hours": 2}, "W")),
        s[2].id: rows(({"hours": 2}, "U")),  # failed: held back from every playlist
        s[3].id: rows(({"hours": 2}, "W")),
    }
    p = planned(s, history)
    verified = m3u.parse(p.files["playlists/community/verified.m3u"])
    untested = m3u.parse(p.files["playlists/community/untested.m3u"])
    assert {e.url for e in verified} == {s[0].url, s[3].url}
    assert {e.url for e in untested} == {s[1].url}
    assert all(e.attrs["x-status"] == "verified" for e in verified)
    assert all(e.attrs["x-status"] == "untested" and e.attrs["group-title"].startswith("Untested | ") for e in untested)
    assert "UNTESTED" in p.files["playlists/community/untested.m3u"].splitlines()[0]
    everything = {e.url for path, text in p.files.items() for e in m3u.parse(text)}
    assert s[2].url not in everything
    assert p.stats["verified"] == 2 and p.stats["untested"] == 1 and p.stats["failing_held_back"] == 1
    index = {i["path"]: i for i in p.index}
    de = index["playlists/community/countries/de.m3u"]
    assert (de["count"], de["verified"], de["untested"], de["tier"]) == (2, 1, 1, "community")
    assert index["playlists/community/verified.m3u"]["kind"] == "community-verified"


def test_dimension_playlists_label_every_entry_and_quality_prefers_measurement():
    a = stream(1)._replace(lg=["de", "en"], ct=["news", "sports"], q=480)
    b = stream(2)._replace(q=1080)
    history = {a.id: [[iso(NOW), "W", 5, 1, 1080]]}  # measured 1080p beats the source label of 480
    p = planned([a, b], history)
    assert {"playlists/community/languages/de.m3u", "playlists/community/languages/en.m3u"} <= set(p.files)
    assert {"playlists/community/categories/news.m3u", "playlists/community/categories/sports.m3u"} <= set(p.files)
    q1080 = m3u.parse(p.files["playlists/community/quality/1080p.m3u"])
    assert {e.url for e in q1080} == {a.url, b.url} and "playlists/community/quality/sd.m3u" not in p.files
    assert q1080[0].attrs["group-title"].endswith("| Verified") and q1080[1].attrs["group-title"].endswith("| Untested")
    assert q1080[0].attrs["x-quality"] == "1080p"
    for text in p.files.values():
        assert text.startswith("#EXTM3U") and 'x-nexonic-tier="community"' in text.splitlines()[0]
        for e in m3u.parse(text):
            assert e.attrs["x-tier"] == "community" and e.attrs["x-status"] in ("verified", "untested")


def test_untested_can_be_left_out_of_the_dimension_playlists():
    s = [stream(0), stream(1)]
    history = {s[0].id: rows(({"hours": 2}, "W"))}
    p = planned(s, history, CommunityConfig(untested_in_dimension_playlists=False))
    entries = m3u.parse(p.files["playlists/community/countries/de.m3u"])
    assert [e.url for e in entries] == [s[0].url]
    assert len(m3u.parse(p.files["playlists/community/untested.m3u"])) == 1


def test_plan_is_deterministic_and_never_writes_empty_files():
    s = [stream(i, cc="de" if i % 2 else "fr") for i in range(6)]
    history = {s[0].id: rows(({"hours": 2}, "W"))}
    first, second = planned(s, history), planned(list(s), dict(history))
    assert first.files == second.files and first.index == second.index
    assert all(text.count("#EXTINF") > 0 for text in first.files.values())
    assert (
        planned([], {}).files == {}
        and c.plan_community(None, {}, c.OfficialContext(), c.Exclusions(), CommunityConfig()).files == {}
    )
    assert planned(s, {}, CommunityConfig(enabled=False)).files == {}
    # no verified stream: no verified.m3u rather than an empty one
    assert "playlists/community/verified.m3u" not in first.files or first.stats["verified"] > 0
    assert "playlists/community/verified.m3u" not in planned(s, {}).files


def test_failed_streams_return_after_a_later_success():
    s = [stream(0)]
    down = {s[0].id: rows(({"days": 3}, "U"))}
    assert planned(s, down).files == {}
    up = {s[0].id: rows(({"days": 3}, "U"), ({"hours": 1}, "W"))}
    assert "playlists/community/verified.m3u" in planned(s, up).files
