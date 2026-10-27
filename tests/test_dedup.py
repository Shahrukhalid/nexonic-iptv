from nexonic import generate
from nexonic.dedup import find_duplicates, fold_name, identity_key, stream_key
from nexonic.models import Channel
from nexonic.records import load_records


def ch(record, **kw) -> Channel:
    return Channel.model_validate(record(**kw))


def test_stream_key_ignores_scheme_default_port_case_fragment_and_trailing_slash():
    base = stream_key("https://Live.Example.de/hls/a.m3u8")
    assert stream_key("http://live.example.de/hls/a.m3u8") == base
    assert stream_key("https://live.example.de:443/hls/a.m3u8#x") == base
    assert stream_key("https://live.example.de/hls/a.m3u8/") == base
    assert stream_key("https://live.example.de:8443/hls/a.m3u8") != base
    assert stream_key("https://live.example.de/hls/b.m3u8") != base
    assert stream_key("https://live.example.de/hls/a.m3u8?x=1") != base


def test_name_folding_keeps_distinct_channels_distinct():
    assert fold_name("Das Erste") == fold_name("das  erste")
    assert fold_name("Café TV") == fold_name("Cafe TV")
    assert len({fold_name(n) for n in ("ETV", "ETV 2", "ETV+")}) == 3


def test_identity_is_epg_feed_aware(record):
    en = ch(record, id="dw-en", name="DW English", epg_id="DW.de@English")
    es = ch(
        record,
        id="dw-es",
        name="DW Espanol",
        epg_id="DW.de@Espanol",
        **{"stream.url": "https://x.example-broadcaster.de/es.m3u8"},
    )
    assert identity_key(en) != identity_key(es)  # same broadcaster, different feeds: both kept
    again = ch(
        record,
        id="dw-en-2",
        name="DW (English)",
        epg_id="dw.de@english",
        **{"stream.url": "https://x.example-broadcaster.de/en2.m3u8"},
    )
    assert identity_key(en) == identity_key(again)


def test_find_duplicates_by_stream_and_identity(record):
    a = ch(record, id="a-news", name="A News", epg_id="A.de")
    b = ch(
        record,
        id="b-copy",
        name="Other name",
        epg_id="B.de",
        **{"stream.url": "http://live.example-broadcaster.de/hls/news/master.m3u8"},
    )
    c = ch(record, id="c-same", name="C", epg_id="a.de", **{"stream.url": "https://cdn.example-broadcaster.de/c.m3u8"})
    d = ch(record, id="d-other", name="D", epg_id="D.de", **{"stream.url": "https://cdn.example-broadcaster.de/d.m3u8"})
    assert find_duplicates([d, c, b, a]) == {"b-copy": "a-news", "c-same": "a-news"}


def test_regional_variants_in_one_country_stay_distinct(record):
    chans = [
        record(
            id="reg-nord",
            name="Regional Nord",
            epg_id="RegNord.de",
            **{"stream.url": "https://a.example-broadcaster.de/n.m3u8"},
        ),
        record(
            id="reg-sued",
            name="Regional Sued",
            epg_id="RegSued.de",
            **{"stream.url": "https://a.example-broadcaster.de/s.m3u8"},
        ),
        record(
            id="reg-ost", name="Regional Ost", epg_id=None, **{"stream.url": "https://a.example-broadcaster.de/o.m3u8"}
        ),
    ]
    assert find_duplicates([Channel.model_validate(c) for c in chans]) == {}


def test_same_name_in_different_countries_is_not_a_duplicate(record):
    de = ch(
        record, id="tv-de", name="TV One", country="de", epg_id=None, **{"stream.url": "https://a.example.de/1.m3u8"}
    )
    at = ch(
        record, id="tv-at", name="TV One", country="at", epg_id=None, **{"stream.url": "https://a.example.at/1.m3u8"}
    )
    assert find_duplicates([de, at]) == {}


def test_generator_excludes_scheme_variants_and_prefers_curated(dataset, record):
    auto = record(
        id="a-auto",
        name="Auto Copy",
        epg_id="Auto.de",
        **{
            "stream.url": "http://live.example-broadcaster.de/hls/news/master.m3u8",
            "source.method": "automated-domain-match",
        },
    )
    auto["source"]["notes"] = ""
    curated = record(id="z-curated", name="Z Curated", epg_id="Z.de")
    res = load_records(dataset([auto, curated]))
    from nexonic.status import CheckResult, Status

    hist = {"a-auto": [CheckResult("a-auto", Status.VERIFIED_WORKING, "2026-10-20T03:00:00Z")]}
    p = generate.plan(res, hist)
    assert [c.id for c in p.published] == ["z-curated"]
    assert p.excluded[0]["id"] == "a-auto" and p.excluded[0]["reasons"] == ["duplicate stream URL of z-curated"]


def test_generator_excludes_same_identity_with_different_url(dataset, record):
    a = record(id="a-one", name="One", epg_id="One.de", **{"stream.url": "https://a.example-broadcaster.de/1.m3u8"})
    b = record(id="b-one", name="One HD", epg_id="One.de", **{"stream.url": "https://a.example-broadcaster.de/2.m3u8"})
    p = generate.plan(load_records(dataset([a, b])), {})
    assert [c.id for c in p.published] == ["a-one"]
    assert p.excluded[0]["reasons"] == ["duplicate channel identity of a-one"]
