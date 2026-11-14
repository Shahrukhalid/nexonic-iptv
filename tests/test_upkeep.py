"""Daily upkeep stays inside its time budget and never publishes the same address twice."""

import datetime as dt

import httpx

from nexonic import finder, radio
from nexonic.extras_config import RadioConfig


def test_source_finder_stops_at_the_rate_limit(monkeypatch):
    calls = []

    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(403, headers={"x-ratelimit-remaining": "0"})

    real = httpx.Client

    def client(*a, **k):
        k["transport"] = httpx.MockTransport(handler)
        return real(*a, **k)

    monkeypatch.setattr(finder.httpx, "Client", client)
    got = finder.find(pause=0)
    assert got == {"candidates": [], "skipped": []}
    assert len(calls) == 1  # stopped at once instead of waiting out the limit


def test_radio_drops_addresses_that_only_differ_in_case_or_port(tmp_path):
    base = {"name": "Station One", "countrycode": "DE", "lastcheckok": 1, "tags": ""}
    rows = [
        {**base, "stationuuid": "1", "url_resolved": "http://Radio.example.org/live"},
        {**base, "stationuuid": "2", "url_resolved": "http://radio.example.org:80/live"},
        {**base, "stationuuid": "3", "url_resolved": "http://radio.example.org:99999/live"},
    ]
    got = radio.refresh(
        RadioConfig(),
        now=dt.datetime(2026, 11, 14, tzinfo=dt.UTC),
        path=tmp_path / "s.json",
        fetcher=lambda *a, **k: rows,
        log=lambda _m: None,
    )
    assert got["stations"] == 1 and got["dropped"] == {"bad-url": 1, "duplicate": 1}


def test_radio_never_publishes_keys_or_tokens(tmp_path):
    base = {"name": "Station One", "countrycode": "DE", "lastcheckok": 1, "tags": ""}
    rows = [
        {**base, "stationuuid": "1", "url_resolved": "https://a.example.org/live?token=abc"},
        {
            **base,
            "stationuuid": "2",
            "url_resolved": "https://b.example.org/live",
            "favicon": "https://img.example.org/logo.png?auth=xyz",
        },
    ]
    path = tmp_path / "s.json"
    got = radio.refresh(
        RadioConfig(),
        now=dt.datetime(2026, 11, 14, tzinfo=dt.UTC),
        path=path,
        fetcher=lambda *a, **k: rows,
        log=lambda _m: None,
    )
    assert got["stations"] == 1 and got["dropped"] == {"credential-in-url": 1}
    assert radio.load(path)["rows"][0][6] == ""  # the keyed logo is left out, the station stays
