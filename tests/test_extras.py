"""Free radio, open media and TV guide tiers."""

import datetime as dt
import gzip
import importlib.util
import sys
from pathlib import Path

from nexonic import guide, m3u, openmedia, radio
from nexonic.extras_config import ExtrasConfig, GuideConfig, MediaConfig, RadioConfig, load_extras

NOW = dt.datetime(2026, 11, 14, 12, tzinfo=dt.UTC)


def station(i, **kw):
    s = {
        "stationuuid": f"id-{i}",
        "name": f"Station {i}",
        "url_resolved": f"https://radio{i}.example.org/live",
        "countrycode": "GB" if i % 2 else "DE",
        "language": "english",
        "tags": "news,talk",
        "favicon": "https://radio.example.org/logo.png",
        "codec": "MP3",
        "bitrate": 128,
        "clickcount": 100 - i,
        "votes": 1,
        "lastcheckok": 1,
    }
    s.update(kw)
    return s


def test_radio_refresh_filters_and_plans(tmp_path):
    rows = [station(i) for i in range(6)]
    rows.append(station(9, lastcheckok=0))
    rows.append(station(10, url_resolved="https://u:p@x.example.org/a"))
    rows.append(station(11, url_resolved=rows[0]["url_resolved"]))
    rows.append(station(12, stationuuid="GONE"))
    path = tmp_path / "s.json"
    got = radio.refresh(RadioConfig(), {"gone"}, now=NOW, path=path, fetcher=lambda *a, **k: rows, log=lambda _m: None)
    assert got["stations"] == 6
    assert got["dropped"] == {"bad-url": 1, "duplicate": 1, "not-working": 1, "takedown-list": 1}
    plan = radio.plan_radio(radio.load(path), RadioConfig(), country_names={"GB": "United Kingdom"})
    assert set(plan.files) == {
        "playlists/radio/all.m3u",
        "playlists/radio/countries/gb.m3u",
        "playlists/radio/countries/de.m3u",
    }
    entries = m3u.parse(plan.files["playlists/radio/countries/gb.m3u"])
    assert entries[0].attrs["group-title"] == "Radio · United Kingdom" and entries[0].attrs["x-tier"] == "radio"
    # recently refreshed: skipped
    assert radio.refresh(RadioConfig(), now=NOW, path=path, fetcher=lambda *a, **k: [], log=lambda _m: None)["skipped"]


def page(n, licence="cc-by-sa-4.0", duration=600, mediatype="VIDEO"):
    return {
        "title": f"File:Film {n}.webm",
        "imageinfo": [
            {
                "mediatype": mediatype,
                "url": f"https://upload.wikimedia.org/wikipedia/commons/a/ab/Film_{n}.webm",
                "duration": duration,
                "size": 50_000_000,
                "thumburl": "https://upload.wikimedia.org/thumb.jpg",
                "extmetadata": {
                    "License": {"value": licence},
                    "LicenseShortName": {"value": "CC BY-SA 4.0"},
                    "Artist": {"value": "<a href='x'>Jane Doe</a>"},
                    "DateTimeOriginal": {"value": "1927"},
                },
            }
        ],
    }


def test_open_media_accepts_only_free_long_videos(tmp_path):
    pages = {
        str(i): p
        for i, p in enumerate(
            [
                page(1),
                page(2, licence="cc-by-nc-4.0"),
                page(3, duration=30),
                page(4, mediatype="AUDIO"),
                page(5, licence="pd"),
            ]
        )
    }
    cfg = MediaConfig(searches=[{"q": "x", "genre": "documentary"}])
    path = tmp_path / "m.json"
    got = openmedia.refresh(
        cfg,
        now=NOW,
        path=path,
        fetcher=lambda *a, **k: {"query": {"pages": pages}},
        sleep=lambda _s: None,
        log=lambda _m: None,
    )
    assert got["items"] == 2
    assert got["rejected"] == {"licence-not-allowed": 1, "not-video": 1, "too-short": 1}
    data = openmedia.load(path)
    assert data["progress"]["x"]["done"]
    plan = openmedia.plan_media(data, cfg)
    e = m3u.parse(plan.files["playlists/media/documentary.m3u"])[0]
    assert e.title == "Film 1 (1927)" and e.attrs["x-author"] == "Jane Doe" and e.attrs["x-licence"] == "CC BY-SA 4.0"


XML_A = b"""<?xml version="1.0"?><tv>
<channel id="BBCOne.uk"><display-name>BBC One</display-name></channel>
<channel id="Other.xx"><display-name>Other</display-name></channel>
<programme channel="BBCOne.uk" start="20261114130000 +0000" stop="20261114140000 +0000"><title>News</title></programme>
<programme channel="BBCOne.uk" start="20261120130000 +0000" stop="20261120140000 +0000"><title>Too late</title></programme>
<programme channel="Other.xx" start="20261114130000 +0000" stop="20261114140000 +0000"><title>Not ours</title></programme>
</tv>"""
XML_B = b"""<tv><channel id="bbcone.uk"/><programme channel="BBCOne.uk" start="20261114150000 +0100" stop="20261114160000 +0100"><title>Dup</title></programme>
<channel id="DW.de"/><programme channel="DW.de" start="20261114120000 +0000"><title>DW</title></programme></tv>"""


def test_guide_merges_trims_and_keeps_first_owner(tmp_path):
    out = tmp_path / "guide.xml.gz"
    feeds = {"https://a/x.xml.gz": gzip.compress(XML_A), "https://b/y.xml": XML_B}
    cfg = GuideConfig(feeds=list(feeds), allowed_hosts=["a", "b"])
    got = guide.build(cfg, {"BBCOne.uk", "DW.de"}, now=NOW, out=out, fetch=feeds.__getitem__, log=lambda _m: None)
    assert got["programmes"] == 2 and got["channels"] == 2
    text = gzip.decompress(out.read_bytes()).decode()
    assert "News" in text and "DW" in text and "Too late" not in text and "Not ours" not in text and "Dup" not in text


def test_guide_without_feeds_does_nothing(tmp_path):
    assert guide.build(GuideConfig(), {"a"}, out=tmp_path / "g.gz")["programmes"] == 0
    assert not (tmp_path / "g.gz").exists()


def test_source_finder_screen():
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    spec = importlib.util.spec_from_file_location("fs", Path(__file__).parent.parent / "scripts" / "find_sources.py")
    fs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fs)
    good = "#EXTM3U\n" + "#EXTINF:-1,News\nhttps://a.example/x.m3u8\n" * 25
    assert fs.screen(good) == (25, [])
    assert fs.screen(good + "http://x/get.php?username=a&password=b\n")[1]
    assert fs.screen(good.replace("News", "VIP Sports"))[1]


def test_shipped_extras_file_equals_the_defaults():
    assert load_extras() == ExtrasConfig()
