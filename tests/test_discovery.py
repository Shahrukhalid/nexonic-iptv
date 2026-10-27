import json
from pathlib import Path

import pytest
import yaml
from conftest import load_script

from nexonic import fetch

discover = load_script("discover")
ec = load_script("expand_catalog")
moderate = load_script("moderate")

CHANNELS = (
    "id,name,alt_names,network,owners,country,categories,is_nsfw,launched,closed,replaced_by,website\n"
    "DemoNews.de,Demo News,,,Demo Media,DE,news,FALSE,,,,https://www.demonews.de\n"
    "OtherTV.de,Other TV,,,Other Media,DE,general,FALSE,,,,https://www.othertv.de\n"
    "Spicy.de,Spicy Channel,,,Spicy Media,DE,general,TRUE,,,,https://www.spicy.de\n"
    "Kids.de,Kids Zone,,,Kids Media,DE,kids,FALSE,,,,https://www.kidszone.de\n"
)
FEEDS = (
    "channel,id,name,is_main,broadcast_area,timezones,languages,format\n"
    "DemoNews.de,SD,SD,TRUE,c/DE,,deu,576i\n"
    "OtherTV.de,SD,SD,TRUE,c/DE,,deu,576i\n"
    "Spicy.de,SD,SD,TRUE,c/DE,,deu,576i\n"
    "Kids.de,SD,SD,TRUE,c/DE,,deu,576i\n"
)
BLOCK = "channel,reason,ref\nBlocked.de,nsfw,x\n"
M3U = (
    "#EXTM3U\n"
    '#EXTINF:-1 tvg-id="DemoNews.de@SD",Demo News (1080p)\nhttps://live.demonews.de/hls/master.m3u8\n'
    '#EXTINF:-1 tvg-id="OtherTV.de@SD",Other TV\nhttps://cdn.thirdparty-restream.com/other.m3u8\n'
    '#EXTINF:-1 tvg-id="Spicy.de@SD",Spicy Channel\nhttps://live.spicy.de/x.m3u8\n'
)
M3U_PLUS = M3U + '#EXTINF:-1 tvg-id="Kids.de@SD",Kids Zone\nhttps://stream.kidszone.de/live.m3u8\n'


@pytest.fixture
def env(tmp_path, monkeypatch):
    data, state = tmp_path / "data", tmp_path / "state"
    (data / "approved").mkdir(parents=True)
    (data / "pending").mkdir()
    monkeypatch.setattr(ec, "DATA", data)
    monkeypatch.setattr(ec, "STATE", state)
    streams, db = tmp_path / "streams", tmp_path / "db"
    streams.mkdir()
    db.mkdir()
    (db / "channels.csv").write_text(CHANNELS, encoding="utf-8")
    (db / "feeds.csv").write_text(FEEDS, encoding="utf-8")
    (db / "blocklist.csv").write_text(BLOCK, encoding="utf-8")
    (streams / "de.m3u").write_text(M3U, encoding="utf-8")
    return tmp_path


def snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.parts[-2] in ("auto", "state", "pending")
    }


def run(env, date):
    return ec.main(["--streams", str(env / "streams"), "--database", str(env / "db"), "--date", date])


def test_admission_rules_are_unchanged(env):
    assert run(env, "2026-01-01") == 0
    recs = yaml.safe_load((env / "data/approved/auto/de.yaml").read_text())["channels"]
    assert [r["id"] for r in recs] == ["demo-news-de"]  # restream host and NSFW channel are not admitted
    assert recs[0]["source"]["method"] == "automated-domain-match"
    assert recs[0]["stream"]["url"] == "https://live.demonews.de/hls/master.m3u8"
    stats = json.loads((env / "state/discovery.json").read_text())["stats"]
    assert stats["admitted"] == 1
    assert stats["host-not-owned-by-broadcaster"] == 1 and stats["nsfw-or-blocklisted"] == 1


def test_rerun_with_unchanged_input_changes_nothing(env):
    run(env, "2026-01-01")
    before = snapshot(env)
    assert before
    run(env, "2026-02-02")  # a later date must not rewrite dates or files
    assert snapshot(env) == before
    rec = yaml.safe_load((env / "data/approved/auto/de.yaml").read_text())["channels"][0]
    assert str(rec["first_discovered"]) == "2026-01-01" and str(rec["review"]["reviewed_at"]) == "2026-01-01"


def test_new_channel_gets_the_new_date_and_old_records_keep_theirs(env):
    run(env, "2026-01-01")
    (env / "streams/de.m3u").write_text(M3U_PLUS, encoding="utf-8")
    run(env, "2026-03-03")
    recs = {r["id"]: r for r in yaml.safe_load((env / "data/approved/auto/de.yaml").read_text())["channels"]}
    assert set(recs) == {"demo-news-de", "kids-zone-de"}
    assert str(recs["demo-news-de"]["first_discovered"]) == "2026-01-01"
    assert str(recs["kids-zone-de"]["first_discovered"]) == "2026-03-03"


def test_changed_stream_url_refreshes_review_date_but_keeps_first_discovered(env):
    run(env, "2026-01-01")
    (env / "streams/de.m3u").write_text(M3U.replace("/hls/master.m3u8", "/hls/new.m3u8"), encoding="utf-8")
    run(env, "2026-04-04")
    rec = yaml.safe_load((env / "data/approved/auto/de.yaml").read_text())["channels"][0]
    assert rec["stream"]["url"].endswith("/hls/new.m3u8")
    assert str(rec["first_discovered"]) == "2026-01-01" and str(rec["review"]["reviewed_at"]) == "2026-04-04"


def test_removed_source_removes_the_record_file(env):
    run(env, "2026-01-01")
    (env / "streams/de.m3u").write_text("#EXTM3U\n", encoding="utf-8")
    run(env, "2026-01-02")
    assert not (env / "data/approved/auto/de.yaml").exists()


def test_without_paths_the_data_is_downloaded(env, monkeypatch):
    asked = {}

    def fake(cfg, dest, need=("iptv", "database"), **kw):
        asked["need"] = need
        return {"streams": env / "streams", "database": env / "db"}

    monkeypatch.setattr(ec, "fetch_iptv_org", fake)
    assert ec.main(["--date", "2026-01-01"]) == 0
    assert asked["need"] == ("iptv", "database")
    assert (env / "data/approved/auto/de.yaml").exists()
    # only the missing half is downloaded when one directory is given
    assert ec.main(["--streams", str(env / "streams"), "--date", "2026-01-01"]) == 0
    assert asked["need"] == ("database",)


def test_download_failure_exits_nonzero_without_touching_data(env, monkeypatch, capsys):
    def boom(*a, **k):
        raise fetch.FetchError("offline")

    monkeypatch.setattr(ec, "fetch_iptv_org", boom)
    assert ec.main([]) == 1
    assert "offline" in capsys.readouterr().err
    assert not (env / "data/approved/auto").exists()


def test_discover_candidates_file_ignores_date_only_changes(tmp_path, monkeypatch):
    src = tmp_path / "s.m3u"
    src.write_text('#EXTM3U\n#EXTINF:-1 tvg-id="A.de",A\nhttps://live.example.de/a.m3u8\n', encoding="utf-8")
    out = tmp_path / "c.yaml"
    monkeypatch.setattr(discover, "load_records", lambda: type("R", (), {"all": lambda self: []})())
    assert discover.main([str(src), "--country", "de", "--out", str(out)]) == 0
    first = out.read_text()
    out.write_text(first.replace(first.split("generated_on: ")[1].split("\n")[0], "'2020-01-01'"))
    stamp = out.stat().st_mtime_ns
    discover.main([str(src), "--country", "de", "--out", str(out)])
    assert out.stat().st_mtime_ns == stamp  # same candidates: file left alone
    src.write_text(src.read_text() + '#EXTINF:-1 tvg-id="B.de",B\nhttps://live.example.de/b.m3u8\n', encoding="utf-8")
    discover.main([str(src), "--country", "de", "--out", str(out)])
    assert "b.m3u8" in out.read_text()


def test_nsfw_blocklist_refresh_refuses_a_truncated_download(tmp_path, monkeypatch):
    monkeypatch.setattr(moderate, "MODERATION_DIR", tmp_path)
    (tmp_path / "iptv-org-nsfw-blocklist.txt").write_text("# h\n" + "\n".join(f"c{i}" for i in range(100)) + "\n")
    bl = tmp_path / "bl.csv"
    bl.write_text("channel,reason,ref\nc1,nsfw,x\n")
    with pytest.raises(SystemExit, match="partial download"):
        moderate.refresh(bl, None)
    assert len((tmp_path / "iptv-org-nsfw-blocklist.txt").read_text().splitlines()) == 101
