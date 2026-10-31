"""Xtream Codes gateway: login, categories, streams, redirects only to playlist URLs, series and the M3U export."""

from __future__ import annotations

import json

import pytest

from nexonic.xtream import Gateway, stable_id

LIVE = """#EXTM3U
#EXTINF:-1 tvg-id="One.de@SD" tvg-logo="https://img.example/1.png" group-title="Germany",Example One
https://live.example-broadcaster.de/one/master.m3u8
#EXTINF:-1 tvg-id="News.fr@SD" group-title="France",Example News
https://live.example-broadcaster.fr/news/index.m3u8
"""
MOVIES = """#EXTM3U
#EXTINF:600 tvg-logo="https://img.example/m.png" group-title="Movies" x-year="1950",Old Film (1950)
https://files.example.org/old-film.mp4
"""
SERIES = """#EXTM3U
#EXTINF:1500 group-title="Space Show",Space Show - 1x01
https://files.example.org/space-1.mp4
#EXTINF:1500 group-title="Space Show",Space Show - 1x02
https://files.example.org/space-2.mp4
"""


@pytest.fixture
def gw(tmp_path):
    (tmp_path / "vod").mkdir()
    (tmp_path / "all.m3u").write_text(LIVE)
    (tmp_path / "vod" / "movies.m3u").write_text(MOVIES)
    (tmp_path / "vod" / "series.m3u").write_text(SERIES)
    return Gateway(tmp_path, "http://127.0.0.1:8080")


def api(gw, query):
    status, headers, body = gw.handle("/player_api.php", query)
    assert status == 200 and headers["Content-Type"].startswith("application/json")
    return json.loads(body)


def test_login(gw):
    ok = api(gw, "username=nexonic&password=free")
    assert ok["user_info"]["auth"] == 1 and ok["user_info"]["status"] == "Active"
    assert ok["server_info"]["port"] == "8080" and ok["server_info"]["server_protocol"] == "http"
    assert api(gw, "username=nexonic&password=wrong") == {"user_info": {"auth": 0}}


def test_live_categories_streams_and_redirect(gw):
    q = "username=nexonic&password=free"
    cats = api(gw, q + "&action=get_live_categories")
    assert [c["category_name"] for c in cats] == ["France", "Germany"]
    germany = next(c["category_id"] for c in cats if c["category_name"] == "Germany")
    streams = api(gw, f"{q}&action=get_live_streams&category_id={germany}")
    assert [s["name"] for s in streams] == ["Example One"]
    sid = streams[0]["stream_id"]
    assert sid == api(gw, q + "&action=get_live_streams")[0]["stream_id"]  # stable ids
    status, headers, _ = gw.handle(f"/live/nexonic/free/{sid}.m3u8", "")
    assert status == 302 and headers["Location"] == "https://live.example-broadcaster.de/one/master.m3u8"
    assert gw.handle(f"/live/nexonic/bad/{sid}.ts", "")[0] == 401
    assert gw.handle("/live/nexonic/free/12345.ts", "")[0] == 404  # only playlist URLs can be reached


def test_vod_and_series(gw):
    q = "username=nexonic&password=free"
    movies = api(gw, q + "&action=get_vod_streams")
    assert movies[0]["container_extension"] == "mp4"
    status, headers, _ = gw.handle(f"/movie/nexonic/free/{movies[0]['stream_id']}.mp4", "")
    assert status == 302 and headers["Location"].endswith("old-film.mp4")
    shows = api(gw, q + "&action=get_series")
    assert shows[0]["name"] == "Space Show" and shows[0]["series_id"] == stable_id("show:Space Show")
    info = api(gw, f"{q}&action=get_series_info&series_id={shows[0]['series_id']}")
    eps = info["episodes"]["1"]
    assert len(eps) == 2
    assert gw.handle(f"/series/nexonic/free/{eps[1]['id']}.mp4", "")[1]["Location"].endswith("space-2.mp4")
    assert api(gw, q + "&action=get_short_epg&stream_id=1") == {"epg_listings": []}


def test_m3u_export_uses_gateway_links(gw):
    status, _, body = gw.handle("/get.php", "username=nexonic&password=free&type=m3u_plus")
    text = body.decode()
    assert status == 200 and text.startswith("#EXTM3U")
    assert "http://127.0.0.1:8080/live/nexonic/free/" in text and "example-broadcaster" not in text
    assert gw.handle("/get.php", "username=x&password=y")[0] == 401


def test_reloads_when_playlists_change(gw, tmp_path):
    q = "username=nexonic&password=free&action=get_live_streams"
    assert len(api(gw, q)) == 2
    (tmp_path / "all.m3u").write_text(LIVE.split("#EXTINF")[0] + "#EXTINF" + LIVE.split("#EXTINF")[1])
    import os

    st = (tmp_path / "all.m3u").stat()
    os.utime(tmp_path / "all.m3u", ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    assert len(api(gw, q)) == 1


def test_static_export_for_the_cloud_gateway(tmp_path):
    from nexonic.xtream import BUCKETS, export_static

    src = tmp_path / "playlists"
    (src / "vod").mkdir(parents=True)
    (src / "all.m3u").write_text(LIVE)
    (src / "vod" / "movies.m3u").write_text(MOVIES)
    (src / "vod" / "series.m3u").write_text(SERIES)
    out = tmp_path / "xtream"
    meta = export_static(src, out)
    assert meta == {"live": 2, "movies": 1, "episodes": 2, "buckets": BUCKETS}
    live = json.loads((out / "live_streams.json").read_text())
    sid = live[0]["stream_id"]
    assert json.loads((out / f"s/live/{sid % BUCKETS}.json").read_text())[str(sid)].startswith("https://live.example")
    cats = json.loads((out / "live_categories.json").read_text())
    assert all((out / f"live/{c['category_id']}.json").exists() for c in cats)
    show = json.loads((out / "series.json").read_text())[0]
    assert len(json.loads((out / f"series_info/{show['series_id']}.json").read_text())["episodes"]["1"]) == 2
    m3u_text = (out / "m3u.txt").read_text()
    assert f"__BASE__/live/__USER__/__PASS__/{sid}.m3u8" in m3u_text and "example-broadcaster" not in m3u_text
