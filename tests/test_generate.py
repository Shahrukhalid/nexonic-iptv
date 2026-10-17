import random

from nexonic import generate, m3u
from nexonic.health import NOT_ENOUGH, compute
from nexonic.records import load_records
from nexonic.status import CheckResult, Status


def chans(record):
    return [
        record(
            id="de-news",
            name="DE News",
            country="de",
            languages=["de"],
            categories=["news"],
            **{"stream.url": "https://live.de-broadcaster.de/a.m3u8"},
            epg_id="DENews.de",
        ),
        record(
            id="de-kids",
            name="DE Kids",
            country="de",
            languages=["de"],
            categories=["kids", "education"],
            **{"stream.url": "https://live.de-broadcaster.de/b.m3u8"},
            epg_id="DEKids.de",
        ),
        record(
            id="fr-news",
            name='FR "Info", Direct',
            country="fr",
            languages=["fr", "en"],
            categories=["news"],
            **{"stream.url": "https://live.fr-broadcaster.fr/c.m3u8"},
            epg_id="FRNews.fr",
        ),
        record(
            id="es-sport",
            name="ES Sport",
            country="es",
            languages=["es"],
            categories=["sports"],
            **{"stream.url": "https://live.es-broadcaster.es/d.m3u8"},
            epg_id="ESSport.es",
        ),
    ]


def ok(cid, when):
    return CheckResult(
        cid,
        Status.VERIFIED_WORKING,
        when,
        level=5,
        latency_ms=300,
        media_readable=True,
        details={"run_id": "run-" + when},
    )


def test_country_language_category_classification(dataset, record):
    res = load_records(dataset(chans(record)))
    p = generate.plan(res, {})
    files = p.files
    de = m3u.parse(files["playlists/countries/de.m3u"])
    assert {e.title for e in de} == {"DE Kids", "DE News"}
    assert "playlists/countries/it.m3u" not in files  # no empty files
    fr_lang = m3u.parse(files["playlists/languages/fr.m3u"])
    en_lang = m3u.parse(files["playlists/languages/en.m3u"])
    assert [e.attrs["tvg-id"] for e in fr_lang] == ["FRNews.fr"] == [e.attrs["tvg-id"] for e in en_lang]
    edu = m3u.parse(files["playlists/categories/education.m3u"])
    assert [e.attrs["tvg-id"] for e in edu] == ["DEKids.de"]
    assert "playlists/categories/movies.m3u" not in files
    allp = m3u.parse(files["playlists/all.m3u"])
    assert len(allp) == 4
    assert allp[0].attrs["group-title"] == "Germany"


def test_verified_playlist_absent_without_real_checks(dataset, record):
    p = generate.plan(load_records(dataset(chans(record))), {})
    assert "playlists/verified.m3u" not in p.files
    assert all(h.grade == NOT_ENOUGH for h in p.health.values())


def test_verified_playlist_contains_only_fresh_successes(dataset, record):
    res = load_records(dataset(chans(record)))
    history = {
        "de-news": [ok("de-news", "2026-10-17T03:00:00Z")],
        "fr-news": [CheckResult("fr-news", Status.UNAVAILABLE, "2026-10-17T03:00:00Z")],
        "es-sport": [ok("es-sport", "2026-10-10T03:00:00Z")],  # older than 48 h relative to latest run
    }
    p = generate.plan(res, history)
    ver = m3u.parse(p.files["playlists/verified.m3u"])
    assert [e.attrs["tvg-id"] for e in ver] == ["DENews.de"]


def test_pending_and_rejected_never_published(dataset, record):
    pend = record(id="pending-one", **{"stream.url": "https://live.pending.de/p.m3u8"})
    pend["review"].update(status="pending", authorization_basis="none")
    rej = record(id="rejected-one", **{"stream.url": "https://live.rejected.de/r.m3u8"})
    rej["review"].update(status="rejected", authorization_basis="none", rejection_reason="restream")
    res = load_records(dataset(chans(record), [pend], [rej]))
    assert not res.errors
    p = generate.plan(res, {})
    blob = "".join(p.files.values())
    assert "pending.de" not in blob and "rejected.de" not in blob
    assert "pending-one" not in {c.id for c in p.published}


def test_adult_record_in_approved_folder_still_excluded(dataset, record):
    bad = record(id="sneaky", name="Erotic Nights", **{"stream.url": "https://live.sneaky.de/x.m3u8"})
    res = load_records(dataset(chans(record) + [bad]))
    p = generate.plan(res, {})
    assert "sneaky" not in {c.id for c in p.published}
    assert any(x["id"] == "sneaky" for x in p.excluded)
    assert "sneaky.de" not in "".join(p.files.values())


def test_duplicate_detection(dataset, record):
    a = chans(record)
    dup = record(id="de-news-copy", name="DE News Copy", **{"stream.url": "https://LIVE.de-broadcaster.de/a.m3u8"})
    res = load_records(dataset(a + [dup]))
    assert any("duplicate stream URL" in e["error"] for e in res.errors)
    dup_id = record(id="de-news", name="Other", **{"stream.url": "https://live.other.de/o.m3u8"})
    res2 = load_records(dataset(a + [dup_id]))
    assert any("duplicate id" in e["error"] for e in res2.errors)


def test_no_duplicates_within_playlist(dataset, record):
    res = load_records(dataset(chans(record)))
    p = generate.plan(res, {})
    for rel, text in p.files.items():
        urls = [e.url for e in m3u.parse(text)]
        assert len(urls) == len(set(urls)), rel


def test_deterministic_output(dataset, record, tmp_path):
    items = chans(record)
    res1 = load_records(dataset(items))
    h = {"de-news": [ok("de-news", "2026-10-17T03:00:00Z")]}
    out1 = generate.plan(res1, h).files
    random.Random(7).shuffle(items)
    res2 = load_records(dataset(items))
    out2 = generate.plan(res2, h).files
    assert out1 == out2
    assert generate.plan(res2, h).files == out2  # repeated run identical


def test_escaping_in_output(dataset, record):
    p = generate.plan(load_records(dataset(chans(record))), {})
    text = p.files["playlists/countries/fr.m3u"]
    assert "tvg-name=\"FR 'Info', Direct\"" in text
    entries = m3u.parse(text)
    assert entries[0].title == 'FR "Info", Direct'


def test_stale_channels_excluded(dataset, record):
    res = load_records(dataset(chans(record)))
    fails = [
        CheckResult("es-sport", Status.UNAVAILABLE, f"2026-10-{d:02d}T03:00:00Z", details={"run_id": f"r{d}"})
        for d in (1, 5, 9, 12)
    ]
    history = {"es-sport": fails, "de-news": [ok("de-news", "2026-10-12T03:00:00Z")]}
    p = generate.plan(res, history)
    assert "es-sport" not in {c.id for c in p.published}


def test_health_score_needs_enough_data():
    h = compute([ok("x", "2026-10-17T03:00:00Z")], generate.parse_iso("2026-10-17T03:00:00Z"))
    assert h.score is None and h.grade == NOT_ENOUGH and h.display_status == "verified-recently"


def test_health_score_formula():
    results = [ok("x", f"2026-10-{d:02d}T03:00:00Z") for d in (14, 15, 16, 17)]
    h = compute(results, generate.parse_iso("2026-10-17T03:00:00Z"))
    # rate 1.0, streak 4/5, latency 300ms -> 1.0, media 1.0, fresh 1.0
    assert h.score == round(100 * (0.45 + 0.20 * 0.8 + 0.15 + 0.10 + 0.10))
    assert h.grade == "Excellent"


def test_geo_results_are_neutral():
    ref = generate.parse_iso("2026-10-17T03:00:00Z")
    geo = [CheckResult("x", Status.GEO_RESTRICTED, f"2026-10-{d:02d}T03:00:00Z") for d in (14, 15, 16, 17)]
    h = compute(geo, ref)
    assert h.display_status == "geo-restricted" and h.score is None


def test_automated_records_need_a_successful_check(dataset, record):
    auto = record(id="auto-one", name="Auto One", **{"stream.url": "https://live.auto-one.de/a.m3u8"})
    auto["source"]["method"] = "automated-domain-match"
    data = dataset(chans(record))
    (data / "approved" / "auto").mkdir()
    import yaml

    (data / "approved" / "auto" / "de.yaml").write_text(yaml.safe_dump({"channels": [auto]}), encoding="utf-8")
    res = load_records(data)
    assert not res.errors
    p = generate.plan(res, {})
    assert "auto-one" not in {c.id for c in p.published}
    geo_only = {"auto-one": [CheckResult("auto-one", Status.GEO_RESTRICTED, "2026-10-17T03:00:00Z")]}
    assert "auto-one" not in {c.id for c in generate.plan(res, geo_only).published}
    p2 = generate.plan(res, {"auto-one": [ok("auto-one", "2026-10-17T03:00:00Z")]})
    assert "auto-one" in {c.id for c in p2.published}


def test_automated_record_outside_auto_folder_is_error(dataset, record):
    auto = record(id="auto-two", name="Auto Two", **{"stream.url": "https://live.auto-two.de/a.m3u8"})
    auto["source"]["method"] = "automated-domain-match"
    res = load_records(dataset([auto]))
    assert any("approved/auto" in e["error"] for e in res.errors)
