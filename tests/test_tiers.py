"""Quality playlists, tier statistics, tier clashes, raw fetch fallback and failure isolation of the extra tiers."""

from pathlib import Path

import httpx
import pytest

from nexonic import fetch, generate, m3u, quality, reports
from nexonic.config import DiscoveryConfig
from nexonic.records import load_records
from nexonic.status import CheckResult, Status
from tests.test_generate import chans

ROOT = Path(__file__).resolve().parent.parent


def ok(cid, when, **details):
    return CheckResult(
        cid, Status.VERIFIED_WORKING, when, level=5, latency_ms=300, media_readable=True, details=dict(details)
    )


@pytest.mark.parametrize(
    ("height", "bucket"),
    [(0, None), (-5, None), (360, "sd"), (719, "sd"), (720, "720p"), (1079, "720p"), (1080, "1080p"), (2160, "4k")],
)
def test_quality_bucket_edges(height, bucket):
    assert quality.quality_bucket(height) == bucket


@pytest.mark.parametrize(
    ("label", "height"), [("720p", 720), ("1080i", 1080), ("1920x1080", 1080), ("", 0), (None, 0), ("hd", 0), ("50", 0)]
)
def test_height_of(label, height):
    assert quality.height_of(label) == height


def test_measured_height_prefers_variants_and_ignores_failures():
    master = ok("a", "2026-10-17T03:00:00Z", max_resolution="1920x1080", variants=3, ffprobe_height="360")
    single = ok("a", "2026-10-16T03:00:00Z", ffprobe_height="720")
    failed = CheckResult("a", Status.UNAVAILABLE, "2026-10-18T03:00:00Z", details={"max_resolution": "3840x2160"})
    assert quality.measured_height([master, single, failed]) == 1080
    assert quality.measured_height([single]) == 720
    assert quality.measured_height([failed]) == 0
    # ffprobe reads the lowest variant of a master playlist, so it is not trusted there
    assert quality.measured_height([ok("a", "2026-10-17T03:00:00Z", variants=2, ffprobe_height="360")]) == 0


def test_official_quality_playlists_use_measured_resolution_only(dataset, record):
    res = load_records(dataset(chans(record)))
    history = {
        "de-news": [ok("de-news", "2026-10-17T03:00:00Z", max_resolution="3840x2160")],
        "de-kids": [ok("de-kids", "2026-10-17T03:00:00Z", max_resolution="1280x720")],
        "fr-news": [ok("fr-news", "2026-10-17T03:00:00Z", max_resolution="640x360")],
        "es-sport": [ok("es-sport", "2026-10-17T03:00:00Z")],  # working but never measured
    }
    p = generate.plan(res, history)
    assert [e.title for e in m3u.parse(p.files["playlists/quality/4k.m3u"])] == ["DE News"]
    assert [e.title for e in m3u.parse(p.files["playlists/quality/720p.m3u"])] == ["DE Kids"]
    assert [e.title for e in m3u.parse(p.files["playlists/quality/sd.m3u"])] == ['FR "Info", Direct']
    assert "playlists/quality/1080p.m3u" not in p.files
    assert "es-sport" not in p.quality
    stats = reports.tier_statistics(p)
    assert stats["official"]["with_measured_quality"] == 3
    assert stats["official"]["per_quality"] == {"4k": 1, "720p": 1, "sd": 1}
    assert stats["community"] is None and stats["vod"] is None


def test_extend_adds_a_tier_and_refuses_clashes(dataset, record):
    p = generate.plan(load_records(dataset(chans(record))), {})
    before = dict(p.files)
    generate.extend(p, "community", {"playlists/community/verified.m3u": "#EXTM3U\n"}, [{"id": "x"}], {"verified": 1})
    assert p.tiers["community"] == {"verified": 1} and {"id": "x"} in p.index
    assert all(p.files[k] == v for k, v in before.items())
    with pytest.raises(ValueError, match="overwrite"):
        generate.extend(p, "vod", {"playlists/all.m3u": "x"}, [], {})
    assert p.files["playlists/all.m3u"] == before["playlists/all.m3u"]


def test_readme_tier_rows_state_untested_honestly(dataset, record):
    p = generate.plan(load_records(dataset(chans(record))), {})
    assert any("not built yet" in line for line in generate.tier_rows(p))
    p.tiers["community"] = {"verified": 2, "untested": 5}
    p.tiers["vod"] = {"items": 7}
    rows = "\n".join(generate.tier_rows(p))
    assert "| Community live streams | 7 | 2 | 5 (untested) |" in rows
    assert "| 7 |" in rows
    total = len(p.published) + 7 + 7
    assert f"| **All tiers** | **{total}** | **{len(p.verified_ids) + 2}** | |" in rows


def raw_cfg():
    return DiscoveryConfig(
        retries=0,
        sources=[
            {"name": "iptv", "repo": "iptv-org/iptv", "ref": "master", "licence": "Unlicense", "kind": "m3u_dir"},
            {"name": "database", "repo": "iptv-org/database", "ref": "master", "licence": "ODbL", "kind": "database"},
        ],
    )


def test_fetch_iptv_org_raw_skips_missing_files_and_fails_on_required_ones(tmp_path):
    seen = []

    def handler(req):
        seen.append(req.url.path)
        if req.url.path.endswith("logos.csv") or req.url.path.endswith("/streams/int.m3u"):
            return httpx.Response(404)
        return httpx.Response(200, content=b"id\n1\n")

    got = fetch.fetch_iptv_org_raw(raw_cfg(), tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert got and any(p.endswith("/data/channels.csv") for p in seen)
    assert not (tmp_path / "database" / "logos.csv").exists()
    assert not (tmp_path / "streams" / "int.m3u").exists()
    assert (tmp_path / "database" / "channels.csv").exists()

    def broken(req):
        return httpx.Response(404) if req.url.path.endswith("blocklist.csv") else httpx.Response(200, content=b"x\n")

    with pytest.raises(fetch.FetchError):
        fetch.fetch_iptv_org_raw(
            raw_cfg(), tmp_path / "b", client=httpx.Client(transport=httpx.MockTransport(broken)), sleep=lambda s: None
        )


def test_extra_tiers_never_raise(monkeypatch, capsys):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import verify

    class Cfg:
        class vod:  # noqa: N801
            total_deadline_minutes = 1
            run_budget_seconds = 1

    def boom(*a, **k):
        raise RuntimeError("network down")

    class Args:
        community_budget_seconds = None

    monkeypatch.setattr(verify.community, "load_exclusions", lambda: object())
    monkeypatch.setattr(verify.community, "official_context", lambda r: object())
    monkeypatch.setattr(verify.community, "run_daily", boom)
    monkeypatch.setattr(verify.vod, "refresh", boom)
    Cfg.discovery = Cfg.community = None
    verify.extra_tiers(Cfg, None, Args, 0.0)
    err = capsys.readouterr().err
    assert "community tier failed" in err and "free VOD refresh failed" in err

    monkeypatch.setattr(verify.community, "load_exclusions", boom)
    verify.extra_tiers(Cfg, None, Args, 0.0)
    assert "community tier skipped" in capsys.readouterr().err
