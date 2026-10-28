"""Free VOD tier: licence filtering, file choice, incremental refresh (fake fetcher, no network) and playlist output.

archive.org is not contacted: the fixtures below have the shape of the Internet Archive's advanced-search and item
metadata JSON documents."""

import datetime as dt
import json
import re
from urllib.parse import parse_qs, urlsplit

import pytest

from nexonic import community, m3u, vod
from nexonic.config import CommunityConfig, ConfigError, DiscoveryConfig, VodConfig, load_pipeline
from nexonic.fetch import FetchError, fetch_json

NOW = dt.datetime(2026, 10, 28, 4, 0, 0, tzinfo=dt.UTC)
ALLOWED = list(VodConfig().allowed_licences)
PDM = "https://creativecommons.org/publicdomain/mark/1.0/"


def doc(ident, title="A Film", lic=PDM, **kw):
    d = {"identifier": ident, "title": title, "mediatype": "movies", "year": "1944", "subject": ["drama"]}
    if lic is not None:
        d["licenseurl"] = lic
    d.update(kw)
    return d


def meta(files, lic=PDM, **kw):
    m = {"licenseurl": lic, "mediatype": "movies"}
    m.update(kw)
    return {"metadata": m, "files": files, "server": "ia800000.us.archive.org"}


def mp4(name, fmt="h.264", length="5400.5", size="700000000"):
    return {"name": name, "format": fmt, "length": length, "size": size, "source": "derivative"}


# ------------------------------------------------------------------------------------------------------- licences
@pytest.mark.parametrize(
    ("licenseurl", "rights", "expected"),
    [
        ("https://creativecommons.org/publicdomain/zero/1.0/", None, ("publicdomain", "CC0 1.0")),
        (PDM, None, ("publicdomain", "Public Domain Mark 1.0")),
        ("http://creativecommons.org/publicdomain/mark/1.0", None, ("publicdomain", "Public Domain Mark 1.0")),
        ("https://creativecommons.org/licenses/by/4.0/", None, ("by", "CC BY 4.0")),
        ("http://creativecommons.org/licenses/by-sa/3.0/us/", None, ("by-sa", "CC BY-SA 3.0")),
        ("https://creativecommons.org/licenses/by-nc-nd/2.5/", None, ("by-nc-nd", "CC BY-NC-ND 2.5")),
        (["https://creativecommons.org/licenses/by/4.0/", "x"], None, ("by", "CC BY 4.0")),
        (None, "Public Domain", ("publicdomain", "Public domain (rights statement)")),
        (None, ["Public domain in the USA"], ("publicdomain", "Public domain (rights statement)")),
        (None, "Not in the public domain", None),
        (None, "Not public domain in Europe", None),
        (None, "All rights reserved", None),
        (None, None, None),
        ("https://example.com/my-own-licence", None, None),
        ("https://creativecommons.org.evil.test/licenses/by/4.0/", None, None),
        ("https://evilcreativecommons.org/licenses/by/4.0/", None, None),
        ("ftp://creativecommons.org/licenses/by/4.0/", None, None),
        ("https://creativecommons.org/licenses/zzz/4.0/", None, None),
        # a licence URL decides: a non-open URL is not rescued by a rights statement
        ("https://example.com/licence", "Public domain", None),
    ],
)
def test_licence_filter(licenseurl, rights, expected):
    assert vod.licence_of(licenseurl, rights, ALLOWED) == expected


def test_licence_filter_honours_the_allowed_list():
    assert vod.licence_of("https://creativecommons.org/licenses/by-nc/4.0/", None, ["publicdomain", "by"]) is None
    assert vod.licence_of(None, "Public domain", ["by"]) is None
    assert vod.licence_of(PDM, None, ["publicdomain"]) is not None


# ------------------------------------------------------------------------------------------------------- helpers
def test_file_choice_prefers_h264_mp4_then_other_mpeg4_then_the_small_derivative():
    files = [
        mp4("a.ogv", "Ogg Video"),
        mp4("a_512kb.mp4", "512Kb MPEG4", length="5400"),
        mp4("a.mpeg4.mp4", "MPEG4"),
        mp4("a.mp4", "h.264", length="5400.1"),
        mp4("trailer.mp4", "h.264", length="60"),
        mp4("sub/dir.mp4", "h.264", length="9999"),  # not a top-level file
        {"name": "a.mp3", "format": "VBR MP3"},
    ]
    assert vod.pick_file(files) == ("a.mp4", 700000000, 5400)
    assert vod.pick_file(files[:3])[0] == "a.mpeg4.mp4"
    assert vod.pick_file(files[:2])[0] == "a_512kb.mp4"
    assert vod.pick_file([mp4("a.ogv", "Ogg Video")]) is None and vod.pick_file([]) is None


@pytest.mark.parametrize(
    ("value", "seconds"),
    [
        ("5432.12", 5432),
        ("1:30:12", 5412),
        ("01:30", 90),
        ("90 min", 5400),
        ("1.5 minutes", 90),
        ("", 0),
        ("n/a", 0),
        (None, 0),
        (["120"], 120),
    ],
)
def test_duration_parsing(value, seconds):
    assert vod.parse_duration(value) == seconds


def test_year_series_and_genres():
    assert vod.year_of("1944") == 1944 and vod.year_of(None, "1951-03-02") == 1951 and vod.year_of("n/a") == 0
    assert vod.series_of("The Lone Ranger - S01E02 The Masked Rider") == "The Lone Ranger"
    assert vod.series_of("Dragnet Episode 12") == "Dragnet"
    assert vod.series_of("Captain Video 1x04") == "Captain Video"
    assert vod.series_of("A Standalone Title") == ""
    assert vod.genres_of("noir", ["Mystery films", "film noir"]) == ["noir", "mystery"]
    assert vod.genres_of("", "Science fiction") == ["scifi"] and vod.genres_of("", None) == []


def test_download_url_is_quoted():
    assert (
        vod.download_url("id_1", "My File (1944).mp4") == "https://archive.org/download/id_1/My%20File%20%281944%29.mp4"
    )


# ------------------------------------------------------------------------------------------------------- refresh
class FakeArchive:
    """Serves search pages and metadata documents; records every URL requested."""

    def __init__(self, pages, metadata, fail=()):
        self.pages, self.metadata, self.fail, self.urls = pages, metadata, tuple(fail), []

    def __call__(self, url, cfg, client=None, sleep=None, limit_mb=20):
        self.urls.append(url)
        assert url.startswith("https://archive.org/") and cfg.allowed_hosts == ["archive.org"]
        if any(f in url for f in self.fail):
            raise FetchError(f"{url}: HTTP 503")
        if "advancedsearch" in url:
            query = parse_qs(urlsplit(url).query)
            q = query["q"][0]
            collection = re.search(r"collection:\((\w+)\)", q).group(1)
            view = "cc" if "licenseurl" in q else "rights"
            entry = self.pages.get((collection, view, int(query["page"][0])))
            docs, found = entry if entry else ([], 0)
            return {"response": {"numFound": found, "start": 0, "docs": docs}}
        ident = url.rsplit("/", 1)[1]
        if ident not in self.metadata:
            raise FetchError(f"{url}: HTTP 404")
        return self.metadata[ident]


def small_cfg(**kw):
    base = {
        "collections": [
            {"id": "feature_films", "kind": "movie"},
            {"id": "classic_tv", "kind": "series", "genre": "comedy"},
        ],
        "request_interval": 0,
        "search_pages_per_run": 10,
        "metadata_per_run": 10,
        "rows_per_page": 2,
    }
    base.update(kw)
    return VodConfig(**base)


def run_refresh(tmp_path, cfg, archive, exclusions=None, **kw):
    return vod.refresh(
        cfg,
        exclusions or community.Exclusions(),
        now=kw.pop("now", NOW),
        items_path=tmp_path / "items.json",
        progress_path=tmp_path / "progress.json",
        log=lambda *_: None,
        fetcher=archive,
        sleep=lambda s: None,
        force=True,
        **kw,
    )


def test_refresh_keeps_only_openly_licensed_items_and_records_the_licence(tmp_path):
    good = doc("good_film", "Good Film", subject=["comedy", "drama"])
    pages = {
        ("feature_films", "cc", 1): (
            [
                good,
                doc("no_licence", lic=None),
                doc("closed_licence", lic="https://example.com/licence"),
                doc("pd_by_rights", lic=None, rights="Public Domain"),
                doc("takedown_me"),
                doc("sexy_film", "Hot Sex Movie"),
                doc("not_a_movie", mediatype="audio"),
                doc("bad id with spaces"),
            ],
            8,
        )
    }
    metadata = {
        "good_film": meta([mp4("good_film.mp4"), mp4("good_film_512kb.mp4", "512Kb MPEG4")]),
        "pd_by_rights": meta([mp4("pd.mp4")], lic=None, rights="Public Domain"),
    }
    summary = run_refresh(
        tmp_path, small_cfg(), FakeArchive(pages, metadata), community.Exclusions(vod={"takedown_me"})
    )
    assert summary["rejected"] == {
        "no-open-licence": 2,
        "takedown-list": 1,
        "adult-screening": 1,
        "not-a-movie": 1,
        "bad-identifier-or-title": 1,
    }
    items = {r[0]: r for r in vod.load_items(tmp_path / "items.json")}
    assert set(items) == {"good_film", "pd_by_rights"}
    g = dict(zip(vod.COLUMNS, items["good_film"], strict=True))
    assert g["lc"] == "publicdomain" and g["ll"] == "Public Domain Mark 1.0" and g["f"] == "good_film.mp4"
    assert g["d"] == 5400 and g["y"] == 1944 and g["g"] == ["comedy", "drama"] and g["k"] == "movie"
    assert items["pd_by_rights"][5] == "Public domain (rights statement)"


def test_refresh_is_incremental_across_runs(tmp_path):
    def page(n):
        return [doc(f"film_{n}_{i}", f"Film {n} {i}") for i in range(2)]

    pages = {
        ("feature_films", "cc", 1): (page(1), 6),
        ("feature_films", "cc", 2): (page(2), 6),
        ("feature_films", "cc", 3): (page(3), 6),
    }
    metadata = {d["identifier"]: meta([mp4(d["identifier"] + ".mp4")]) for n in (1, 2, 3) for d in page(n)}
    cfg = small_cfg(search_pages_per_run=1, metadata_per_run=3)
    archive = FakeArchive(pages, metadata)
    seen = []
    for day in range(3):
        run_refresh(tmp_path, cfg, archive, now=NOW + dt.timedelta(days=day))
        rows = vod.load_items(tmp_path / "items.json")
        seen.append((len(rows), sum(1 for r in rows if r[10] not in ("", "-"))))
    assert seen == [(2, 2), (4, 4), (6, 6)]  # one search page and the metadata of what it found, every run
    progress = vod.load_progress(tmp_path / "progress.json")
    assert progress["views"]["feature_films|cc"]["done"] is True
    # a finished search is left alone until the rescan interval has passed
    before = len(archive.urls)
    run_refresh(tmp_path, cfg, archive, now=NOW + dt.timedelta(days=4))
    queries = [parse_qs(urlsplit(u).query)["q"][0] for u in archive.urls[before:] if "advancedsearch" in u]
    assert queries and not any("feature_films" in q and "licenseurl" in q for q in queries)


def test_metadata_slice_is_bounded_and_resumes(tmp_path):
    docs = [doc(f"f{i}", f"Film {i}") for i in range(5)]
    pages = {("feature_films", "cc", 1): (docs[:2], 2), ("feature_films", "cc", 2): (docs[2:4], 4)}
    pages[("feature_films", "cc", 1)] = (docs[:2], 5)
    pages[("feature_films", "cc", 2)] = (docs[2:4], 5)
    pages[("feature_films", "cc", 3)] = (docs[4:], 5)
    metadata = {d["identifier"]: meta([mp4(d["identifier"] + ".mp4")]) for d in docs}
    archive = FakeArchive(pages, metadata)
    cfg = small_cfg(metadata_per_run=2)
    s1 = run_refresh(tmp_path, cfg, archive)
    assert s1["metadata_read"] == 2 and s1["items"] == 5
    s2 = run_refresh(tmp_path, cfg, archive)
    assert s2["metadata_read"] == 2
    ready = [r for r in vod.load_items(tmp_path / "items.json") if r[10] not in ("", "-")]
    assert len(ready) == 4


def test_items_whose_own_metadata_disagrees_are_dropped_or_marked(tmp_path):
    docs = [doc("restricted"), doc("relicensed"), doc("nofile"), doc("fine")]
    pages = {("feature_films", "cc", 1): (docs[:2], 4), ("feature_films", "cc", 2): (docs[2:], 4)}
    metadata = {
        "restricted": meta([mp4("r.mp4")], **{"access-restricted-item": "true"}),
        "relicensed": meta([mp4("x.mp4")], lic="https://example.com/all-rights-reserved"),
        "nofile": meta([mp4("n.ogv", "Ogg Video")]),
        "fine": meta([mp4("f.mp4")]),
    }
    run_refresh(tmp_path, small_cfg(), FakeArchive(pages, metadata))
    items = {r[0]: r for r in vod.load_items(tmp_path / "items.json")}
    assert set(items) == {"nofile", "fine"}
    assert items["nofile"][10] == "-" and items["fine"][10] == "f.mp4"
    # the item without a playable file is remembered, so it is not read again
    archive2 = FakeArchive(pages, metadata)
    run_refresh(tmp_path, small_cfg(), archive2)
    assert not any("/metadata/nofile" in u for u in archive2.urls)


def test_network_errors_never_raise_and_are_retried_next_run(tmp_path):
    pages = {("feature_films", "cc", 1): ([doc("a_film")], 1)}
    metadata = {"a_film": meta([mp4("a.mp4")])}
    down = FakeArchive(pages, metadata, fail=["advancedsearch"])
    summary = run_refresh(tmp_path, small_cfg(), down)
    assert summary["errors"] and summary["items"] == 0
    up = FakeArchive(pages, metadata, fail=["/metadata/"])
    summary = run_refresh(tmp_path, small_cfg(), up)
    assert summary["items"] == 1 and summary["metadata_read"] == 0 and summary["errors"]
    summary = run_refresh(tmp_path, small_cfg(), FakeArchive(pages, metadata))
    assert summary["metadata_read"] == 1
    assert vod.load_items(tmp_path / "items.json")[0][10] == "a.mp4"


def test_budget_stops_new_requests(tmp_path):
    archive = FakeArchive({}, {})
    ticks = iter(range(0, 100_000, 100))  # every clock reading is 100 s later than the previous one
    s = vod.refresh(
        small_cfg(),
        community.Exclusions(),
        now=NOW,
        budget_seconds=250,
        items_path=tmp_path / "i.json",
        progress_path=tmp_path / "p.json",
        log=lambda *_: None,
        fetcher=archive,
        sleep=lambda x: None,
        monotonic=lambda: next(ticks),
        force=True,
    )
    assert 0 < s["searched_pages"] < 4  # four searches were due; the budget ended the slice


def test_tiny_budget_and_recent_run_skip_the_slice(tmp_path):
    kw = {"items_path": tmp_path / "items.json", "progress_path": tmp_path / "progress.json", "log": lambda *_: None}
    assert vod.refresh(small_cfg(), community.Exclusions(), budget_seconds=5, **kw)["skipped"]
    archive = FakeArchive({}, {})
    run_refresh(tmp_path, small_cfg(), archive)  # forced run records last_run
    again = vod.refresh(
        small_cfg(),
        community.Exclusions(),
        now=NOW + dt.timedelta(hours=1),
        budget_seconds=100,
        fetcher=archive,
        sleep=lambda x: None,
        **kw,
    )
    assert again["skipped"] is True
    later = vod.refresh(
        small_cfg(),
        community.Exclusions(),
        now=NOW + dt.timedelta(hours=30),
        budget_seconds=100,
        fetcher=archive,
        sleep=lambda x: None,
        **kw,
    )
    assert "skipped" not in later


def test_item_cap(tmp_path):
    pages = {("feature_films", "cc", 1): ([doc("a1"), doc("a2"), doc("a3")], 3)}
    capped = run_refresh(tmp_path, small_cfg(max_items=2), FakeArchive(pages, {}))
    assert capped["items"] == 2


def test_fetch_json_checks_hosts_and_decodes(tmp_path):
    import httpx

    def handler(request):
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    cfg = DiscoveryConfig(allowed_hosts=["archive.org"], retries=0)
    assert fetch_json("https://archive.org/metadata/x", cfg, client=client) == {"ok": True}
    with pytest.raises(FetchError):
        fetch_json("https://evil.example/metadata/x", cfg, client=client)
    with pytest.raises(FetchError):
        fetch_json("http://archive.org/metadata/x", cfg, client=client)
    bad = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>")))
    with pytest.raises(FetchError):
        fetch_json("https://archive.org/metadata/x", cfg, client=bad)


# ------------------------------------------------------------------------------------------------------- playlists
def row(
    ident,
    title,
    year=1944,
    seconds=5400,
    lc="publicdomain",
    label="Public Domain Mark 1.0",
    co="feature_films",
    kind="movie",
    genres=(),
    series="",
    fname=None,
):
    return [
        ident,
        title,
        year,
        seconds,
        lc,
        label,
        co,
        kind,
        list(genres),
        series,
        fname if fname is not None else f"{ident}.mp4",
        1000,
    ]


def plan(items, exclusions=None, cfg=None):
    return vod.plan_vod(items, exclusions or community.Exclusions(), cfg or VodConfig())


def test_playlists_split_movies_series_genres_and_decades():
    items = [
        row("m1", "Zebra Film", 1944, 5400, genres=["comedy", "drama"]),
        row("m2", "Alpha Film", 1951, 0, genres=["noir"]),
        row("m3", "No Year Film", 0),
        row(
            "s1",
            "Lone Ranger - S01E02",
            1953,
            1500,
            co="classic_tv",
            kind="series",
            series="Lone Ranger",
            lc="by",
            label="CC BY 4.0",
        ),
        row("s2", "Lone Ranger - S01E01", 1953, 1500, co="classic_tv", kind="series", series="Lone Ranger"),
        row("s3", "Odd Show", 1960, 600, co="classic_tv", kind="series"),
    ]
    p = plan(items)
    movies = m3u.parse(p.files["playlists/vod/movies.m3u"])
    assert [e.title for e in movies] == ["Alpha Film (1951)", "No Year Film", "Zebra Film (1944)"]
    assert [e.duration for e in movies] == ["-1", "5400", "5400"]
    assert movies[0].attrs["x-tier"] == "free-vod" and movies[0].attrs["x-licence"] == "Public Domain Mark 1.0"
    assert movies[0].url == "https://archive.org/download/m2/m2.mp4"
    assert movies[0].attrs["x-source"] == "https://archive.org/details/m2"
    series = m3u.parse(p.files["playlists/vod/series.m3u"])
    assert [e.attrs["group-title"] for e in series] == ["Lone Ranger", "Lone Ranger", "Classic TV"]
    assert (
        series[0].attrs["x-licence"] in ("CC BY 4.0", "Public Domain Mark 1.0")
        and series[0].attrs["x-type"] == "series"
    )
    assert {
        "playlists/vod/genres/comedy.m3u",
        "playlists/vod/genres/noir.m3u",
        "playlists/vod/decades/1940s.m3u",
        "playlists/vod/decades/1950s.m3u",
        "playlists/vod/decades/1960s.m3u",
    } <= set(p.files)
    assert "playlists/vod/decades/0s.m3u" not in p.files
    assert len(m3u.parse(p.files["playlists/vod/decades/1950s.m3u"])) == 3
    index = {i["path"]: i for i in p.index}
    assert index["playlists/vod/movies.m3u"]["count"] == 3 and index["playlists/vod/movies.m3u"]["tier"] == "vod"
    assert index["playlists/vod/series.m3u"]["kind"] == "vod-series"
    assert p.stats["items"] == 6 and p.stats["movies"] == 3 and p.stats["by_licence"]["CC BY 4.0"] == 1
    for text in p.files.values():
        assert 'x-nexonic-tier="free-vod"' in text.splitlines()[0]


def test_playlist_generation_filters_again_and_is_deterministic():
    items = [
        row("ok", "Fine Film"),
        row("pending", "Pending Film", fname=""),
        row("nofile", "No File Film", fname="-"),
        row("excluded", "Excluded Film"),
        row("nc", "Licensed Film", lc="by-nc", label="CC BY-NC 4.0"),
        row("adult", "Hot Sex Film"),
    ]
    cfg = VodConfig(allowed_licences=["publicdomain"])
    p = plan(items, community.Exclusions(vod={"excluded"}), cfg)
    assert [e.title for e in m3u.parse(p.files["playlists/vod/movies.m3u"])] == ["Fine Film (1944)"]
    assert p.stats["not_published"] == {
        "adult-screening": 1,
        "licence-not-allowed": 1,
        "no-playable-file": 1,
        "no-playable-file-yet": 1,
        "takedown-list": 1,
    }
    again = plan(list(reversed(items)), community.Exclusions(vod={"excluded"}), cfg)
    assert again.files == p.files and again.index == p.index


def test_no_files_without_items_or_when_disabled():
    assert plan([]).files == {} and plan([row("a", "A")], cfg=VodConfig(enabled=False)).files == {}
    assert plan([row("a", "A", fname="")]).files == {}


def test_weak_term_titles_wait_for_review_unless_allowed():
    items = [row("n", "Night of the Living")]
    assert plan(items).files == {}
    assert "playlists/vod/movies.m3u" in plan(items, cfg=VodConfig(allow_weak_terms=True)).files
    assert plan([row("s", "Hot Sex Film")], cfg=VodConfig(allow_weak_terms=True)).files == {}


def test_urls_with_special_characters_stay_valid_m3u():
    p = plan([row("id.1", 'Film "Quoted", With, Commas', fname="My Film (1944) [HD].mp4")])
    entry = m3u.parse(p.files["playlists/vod/movies.m3u"])[0]
    assert " " not in entry.url and entry.url.endswith("My%20Film%20%281944%29%20%5BHD%5D.mp4")


# ------------------------------------------------------------------------------------------------------- config
def test_vod_and_community_defaults_match_the_shipped_file():
    shipped = load_pipeline()
    assert shipped.vod == VodConfig() and shipped.community == CommunityConfig()
    assert [c["id"] for c in shipped.vod.collections] == [
        "feature_films",
        "film_noir",
        "SciFi_Horror",
        "comedy_films",
        "classic_cartoons",
        "classic_tv",
    ]


@pytest.mark.parametrize(
    "toml",
    [
        '[vod]\nallowed_licences = ["gpl"]\n',
        "[vod]\nallowed_licences = []\n",
        '[[vod.collections]]\nid = "x"\nkind = "documentary"\n',
        '[[vod.collections]]\nid = "x"\n',
        '[[vod.collections]]\nid = "x y"\nkind = "movie"\n',
        '[[vod.collections]]\nid = "x"\nkind = "movie"\ngenre = "Not A Slug"\n',
        '[[vod.collections]]\nid = "x"\nkind = "movie"\n[[vod.collections]]\nid = "x"\nkind = "movie"\n',
        "[vod]\nmetadata_per_run = 0\n",
        "[vod]\nsurprise = 1\n",
        "[community]\nstreams_per_channel = 6\n",
        "[community]\nmin_catalog_ratio = 0\n",
        "[community]\nmax_checks_per_run = -5\n",
        "[community]\nretry_failed_days = -1\n",
        '[community]\nenabled = "yes"\n',
    ],
)
def test_invalid_tier_settings_are_rejected(tmp_path, toml):
    f = tmp_path / "p.toml"
    f.write_text(toml, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_pipeline(f)


def test_state_files_round_trip_and_ignore_garbage(tmp_path):
    items = [row("b", "B"), row("a", "A")]
    vod.save_items(items, tmp_path / "items.json")
    assert [r[0] for r in vod.load_items(tmp_path / "items.json")] == ["a", "b"]
    assert len(json.loads((tmp_path / "items.json").read_text())["items"]) == 2
    (tmp_path / "items.json").write_text("{not json", encoding="utf-8")
    assert vod.load_items(tmp_path / "items.json") == []
    assert vod.load_progress(tmp_path / "missing.json")["views"] == {}
