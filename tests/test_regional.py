import json

import pytest
from conftest import load_script

from nexonic import generate, m3u, regional, reports
from nexonic.config import QuarantineConfig
from nexonic.records import load_records
from nexonic.status import CheckResult, Status

verify = load_script("verify")

LATEST = "2026-10-17T03:17:00Z"


def res(cid, status, when=LATEST, location="unknown"):
    return CheckResult(cid, status, when, level=5 if status is Status.VERIFIED_WORKING else 0, location=location)


def records(record):
    return [
        record(
            id="pk-news",
            epg_id="PKNews.pk",
            name="PK News",
            country="de",
            **{"stream.url": "https://live.pk-broadcaster.de/a.m3u8"},
        ),
        record(
            id="pk-kids",
            epg_id="PKKids.pk",
            name="PK Kids",
            country="de",
            **{"stream.url": "https://live.pk-broadcaster.de/b.m3u8"},
        ),
        record(
            id="us-news",
            epg_id="USNews.us",
            name="US News",
            country="fr",
            **{"stream.url": "https://live.us-broadcaster.fr/c.m3u8"},
        ),
        record(
            id="pk-down",
            epg_id="PKDown.pk",
            name="PK Down",
            country="es",
            **{"stream.url": "https://live.pk-broadcaster.es/d.m3u8"},
        ),
    ]


def primary():
    return {
        "pk-news": [res("pk-news", Status.GEO_RESTRICTED)],
        "pk-kids": [res("pk-kids", Status.GEO_RESTRICTED)],
        "us-news": [res("us-news", Status.VERIFIED_WORKING)],
        "pk-down": [res("pk-down", Status.UNAVAILABLE)],
    }


def test_selectors():
    assert regional.parse_selectors(["GEO_RESTRICTED,UNKNOWN", "restricted"]) == (
        {"GEO_RESTRICTED", "UNKNOWN"},
        {"restricted"},
        False,
    )
    assert regional.parse_selectors(["timeout", "ALL"]) == ({"TIMEOUT"}, set(), True)
    with pytest.raises(regional.RegionalError):
        regional.parse_selectors(["bogus"])
    with pytest.raises(regional.RegionalError):
        regional.parse_selectors([" , "])


@pytest.mark.parametrize("label", ["", "A", "x", "Asia_PK", "-pk", "../etc", "a" * 40])
def test_bad_labels(label):
    with pytest.raises(regional.RegionalError):
        regional.check_label(label)


def test_select_channels_by_status_and_lifecycle(dataset, record):
    chans = load_records(dataset(records(record))).approved
    q = QuarantineConfig()
    got = regional.select_channels(chans, primary(), ["GEO_RESTRICTED"], q)
    assert {c.id for c in got} == {"pk-news", "pk-kids"}
    got = regional.select_channels(chans, primary(), ["restricted", "TIMEOUT"], q)
    assert {c.id for c in got} == {"pk-news", "pk-kids"}
    got = regional.select_channels(chans, primary(), ["UNAVAILABLE"], q)
    assert [c.id for c in got] == ["pk-down"]
    assert len(regional.select_channels(chans, primary(), ["all"], q)) == 4


def test_save_load_and_bounded_history(tmp_path):
    hist = {
        "pk-news": [res("pk-news", Status.VERIFIED_WORKING, f"2026-09-{d:02d}T04:47:00Z") for d in range(1, 29)] * 2
    }
    path = regional.save_location("asia-pk", hist, tmp_path)
    data = json.loads(path.read_text())
    assert len(data["channels"]["pk-news"]) == regional.REGIONAL_HISTORY_LIMIT
    assert regional.load_all(tmp_path)["asia-pk"]["pk-news"][-1].checked_at == "2026-09-28T04:47:00Z"
    # deterministic bytes
    before = path.read_bytes()
    regional.save_location("asia-pk", regional.load_location(path), tmp_path)
    assert path.read_bytes() == before


def test_merge_drops_unknown_ids():
    merged = regional.merge({"gone": [res("gone", Status.VERIFIED_WORKING)]}, [res("a", Status.TIMEOUT)], {"a"})
    assert set(merged) == {"a"}


def test_corrupt_regional_file_is_an_error(tmp_path):
    (tmp_path / "asia-pk.json").write_text("{nope")
    with pytest.raises(regional.RegionalError):
        regional.load_all(tmp_path)


def plan_with(dataset, record, regional_results):
    res_ = load_records(dataset(records(record)))
    return generate.plan(res_, primary(), regional=regional_results), res_


def test_works_in_and_region_playlist(dataset, record):
    reg = {
        "asia-pk": {
            "pk-news": [res("pk-news", Status.VERIFIED_WORKING, "2026-10-17T04:47:00Z", "regional:asia-pk")],
            "pk-kids": [res("pk-kids", Status.GEO_RESTRICTED, "2026-10-17T04:47:00Z", "regional:asia-pk")],
            "pk-down": [res("pk-down", Status.VERIFIED_WORKING, "2026-10-17T04:47:00Z", "regional:asia-pk")],
        }
    }
    p, _ = plan_with(dataset, record, reg)
    export = {e["id"]: e for e in generate.channel_export(p)}
    assert export["pk-news"]["works_in"] == ["asia-pk"]
    assert export["pk-news"]["lifecycle"] == "restricted"
    assert export["pk-news"]["in_verified_playlist"] is False
    assert "works_in" not in export["pk-kids"]  # still restricted there
    assert "works_in" not in export["pk-down"]  # not restricted from the primary location
    # the global verified playlist is unchanged by regional data
    verified = {e.title for e in m3u.parse(p.files["playlists/verified.m3u"])}
    assert verified == {"US News"}
    region = {e.title for e in m3u.parse(p.files["playlists/regions/asia-pk.m3u"])}
    assert region == {"PK News", "PK Down"}
    assert p.works_in == {"pk-news": ["asia-pk"]}


def test_stale_regional_result_is_ignored(dataset, record):
    reg = {"asia-pk": {"pk-news": [res("pk-news", Status.VERIFIED_WORKING, "2026-10-10T04:47:00Z")]}}
    p, _ = plan_with(dataset, record, reg)
    assert p.works_in == {}
    assert "playlists/regions/asia-pk.m3u" not in p.files  # only written when data exists


def test_no_regional_data_changes_nothing(dataset, record):
    base, res_ = plan_with(dataset, record, None)
    assert not any(k.startswith("playlists/regions/") for k in base.files)
    assert all("works_in" not in e for e in generate.channel_export(base))
    stats = reports.statistics(res_, base, primary())
    assert "regional" not in stats


def test_counts_in_statistics(dataset, record):
    reg = {"asia-pk": {"pk-news": [res("pk-news", Status.VERIFIED_WORKING, "2026-10-17T04:47:00Z")]}}
    p, res_ = plan_with(dataset, record, reg)
    stats = reports.statistics(res_, p, primary())
    assert stats["regional"]["restricted_confirmed_elsewhere"] == 1
    assert stats["regional"]["locations"]["asia-pk"]["verified_working"] == 1
    assert any(i["path"] == "playlists/regions/asia-pk.m3u" and i["count"] == 1 for i in p.index)


def test_verify_regional_never_touches_primary_history(tmp_path, monkeypatch):
    monkeypatch.setattr(regional, "REGIONAL_DIR", tmp_path)

    def boom(*a, **k):
        raise AssertionError("primary history must not be written")

    monkeypatch.setattr(verify, "save_history", boom)
    monkeypatch.setattr(verify, "write_json", boom)
    seen = []

    async def fake_check_all(channels, limits):
        seen.extend(c.id for c in channels)
        return [res(c.id, Status.VERIFIED_WORKING, "2026-10-17T04:47:00Z") for c in channels]

    monkeypatch.setattr(verify, "check_all", fake_check_all)
    first = load_records().approved[0].id  # independent of what the committed history currently contains
    monkeypatch.setattr(verify, "load_history", lambda: {first: [res(first, Status.GEO_RESTRICTED)]})
    rc = verify.main(["--location-label", "asia-pk", "--only", "GEO_RESTRICTED"])
    assert rc == 0 and seen == [first]
    data = regional.load_location(tmp_path / "asia-pk.json")
    assert set(data) == {first}
    assert all(r.location == "regional:asia-pk" for rs in data.values() for r in rs)
    assert all(r.details["run_id"].endswith("-asia-pk") for rs in data.values() for r in rs)
    # a second run appends to the same file
    verify.main(["--location-label", "asia-pk", "--only", "GEO_RESTRICTED"])
    assert all(len(rs) == 2 for rs in regional.load_location(tmp_path / "asia-pk.json").values())


def test_verify_only_requires_label(capsys):
    with pytest.raises(SystemExit):
        verify.main(["--only", "GEO_RESTRICTED"])
    with pytest.raises(SystemExit):
        verify.main(["--location-label", "Bad Label"])
    with pytest.raises(SystemExit):
        verify.main(["--location-label", "asia-pk", "--only", "nonsense"])


def test_verify_nothing_matches(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(regional, "REGIONAL_DIR", tmp_path)
    monkeypatch.setattr(verify, "load_history", lambda: {})

    async def fail(*a, **k):
        raise AssertionError("no checks expected")

    monkeypatch.setattr(verify, "check_all", fail)
    assert verify.main(["--location-label", "asia-pk", "--only", "GEO_RESTRICTED"]) == 0
    assert "nothing to check" in capsys.readouterr().out
    assert not list(tmp_path.iterdir())
