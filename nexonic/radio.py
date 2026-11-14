"""Free radio tier: internet radio stations from an open station directory whose data is public domain.

Only stations the directory's own regular checks report as working are kept; each run drops the ones that stopped.
Nexonic's adult-content screening runs on every name and tag, and the takedown list (key ``radio``, station ids)
applies. Playlist entries are the stations' own stream addresses; nothing is copied or relayed.

    state/radio/stations.json   compact rows, refreshed daily by scripts/verify.py
    playlists/radio/all.m3u     every station, most listened first
    playlists/radio/countries/<cc>.m3u
"""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from . import m3u
from .config import DiscoveryConfig, playlist_url
from .extras_config import RadioConfig
from .fetch import FetchError, fetch_json
from .moderation import Decision, Subject, screen_subject
from .records import ROOT, normalise_url
from .timeutil import iso, parse_iso, utc_now

STATE_DIR = ROOT / "state" / "radio"
STATIONS_FILE = STATE_DIR / "stations.json"
SCHEMA = 1
COLUMNS = ["id", "name", "url", "cc", "lang", "tags", "logo", "codec", "kbps", "votes"]
PAGE = 10000


def _disc(cfg: RadioConfig, host: str) -> DiscoveryConfig:
    return DiscoveryConfig(
        timeout=cfg.timeout, retries=cfg.retries, backoff_base=cfg.backoff_base, allowed_hosts=[host]
    )


def station_ok(s: dict, cfg: RadioConfig) -> str | None:
    """Reason a directory entry is left out, or None when it is kept."""
    url = (s.get("url_resolved") or s.get("url") or "").strip()
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        return "bad-url"
    if cfg.https_only and parts.scheme != "https":
        return "not-https"
    if " " in url or parts.username or parts.password:
        return "bad-url"
    try:
        parts.port  # noqa: B018 - raises ValueError for a malformed port
    except ValueError:
        return "bad-url"
    if str(s.get("lastcheckok", 1)) not in ("1", "True", "true"):
        return "not-working"
    if cfg.min_bitrate and int(s.get("bitrate") or 0) and int(s.get("bitrate") or 0) < cfg.min_bitrate:
        return "low-bitrate"
    name = (s.get("name") or "").strip()
    if not name:
        return "no-name"
    tags = [t.strip()[:40] for t in (s.get("tags") or "").split(",") if t.strip()][:12]
    v = screen_subject(Subject(id=s.get("stationuuid", ""), name=name, stream_url=url, categories=tags, epg_id=None))
    if v.decision is not Decision.PASS:
        return "adult-screening"
    return None


def row_of(s: dict) -> list:
    tags = [t.strip() for t in (s.get("tags") or "").split(",") if t.strip()][:6]
    lang = (s.get("language") or "").split(",")[0].strip()
    return [
        s.get("stationuuid", ""),
        " ".join((s.get("name") or "").split())[:120],
        (s.get("url_resolved") or s.get("url") or "").strip(),
        (s.get("countrycode") or "").upper()[:2],
        lang[:40],
        tags,
        (s.get("favicon") or "").strip() if (s.get("favicon") or "").startswith("https://") else "",
        (s.get("codec") or "")[:12],
        int(s.get("bitrate") or 0),
        int(s.get("clickcount") or 0) + int(s.get("votes") or 0),
    ]


def load(path: Path | None = None) -> dict:
    path = path or STATIONS_FILE
    if not path.exists():
        return {"schema": SCHEMA, "last_run": None, "rows": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if data.get("schema") == SCHEMA else {"schema": SCHEMA, "last_run": None, "rows": []}


def save(data: dict, path: Path | None = None) -> None:
    path = path or STATIONS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = "".join(
        ("\n " if i else "\n ") + json.dumps(r, ensure_ascii=False) + "," for i, r in enumerate(data["rows"])
    )
    body = f'{{"schema": {SCHEMA}, "last_run": {json.dumps(data["last_run"])}, "columns": {json.dumps(COLUMNS)},\n"rows": [{rows.rstrip(",")}\n]}}\n'
    path.write_text(body, encoding="utf-8")


def refresh(
    cfg: RadioConfig,
    excluded: set[str] | frozenset[str] = frozenset(),
    *,
    now: dt.datetime | None = None,
    path: Path | None = None,
    fetcher: Callable = fetch_json,
    log: Callable[[str], None] = print,
    force: bool = False,
) -> dict:
    """Read the directory (first host that answers) and replace the cached stations. Never raises for network errors."""
    if not cfg.enabled:
        return {"enabled": False}
    now = now or utc_now()
    data = load(path)
    if (
        data["last_run"]
        and not force
        and (now - parse_iso(data["last_run"])).total_seconds() < cfg.refresh_max_age_hours * 3600
    ):
        log("radio: refreshed recently; skipping")
        return {"enabled": True, "skipped": True}
    stations: list[dict] | None = None
    for host in cfg.api_hosts:
        got: list[dict] = []
        try:
            for offset in range(0, cfg.max_stations * 2, PAGE):
                q = urlencode(
                    {"hidebroken": "true", "order": "clickcount", "reverse": "true", "limit": PAGE, "offset": offset}
                )
                page = fetcher(f"https://{host}/json/stations/search?{q}", _disc(cfg, host), limit_mb=60)
                if not isinstance(page, list):
                    raise FetchError("unexpected answer")
                got.extend(p for p in page if isinstance(p, dict))
                if len(page) < PAGE:
                    break
            stations = got
            break
        except FetchError as exc:
            log(f"radio: {host} failed ({exc}); trying the next host")
    if stations is None:
        return {"enabled": True, "error": "no directory host answered"}
    rows, seen, dropped = [], set(), Counter()
    for s in stations:
        why = station_ok(s, cfg)
        r = row_of(s)
        if not why and r[0].lower() in excluded:
            why = "takedown-list"
        key = normalise_url(r[2]) if not why else ""
        if not why and key in seen:
            why = "duplicate"
        if why:
            dropped[why] += 1
            continue
        seen.add(key)
        rows.append(r)
        if len(rows) >= cfg.max_stations:
            break
    old = len(data["rows"])
    if old >= 500 and len(rows) < old // 2:
        log(f"radio: directory returned {len(rows)} stations (had {old}); keeping the old list")
        return {"enabled": True, "error": "answer too small"}
    save({"schema": SCHEMA, "last_run": iso(now), "rows": rows}, path)
    summary = {"enabled": True, "stations": len(rows), "dropped": dict(sorted(dropped.items()))}
    log(f"radio: {summary}")
    return summary


@dataclass
class RadioPlan:
    files: dict = field(default_factory=dict)
    index: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def entry(r: list, country_names: dict[str, str]) -> m3u.Entry:
    sid, name, url, cc, lang, tags, logo, codec, kbps, _v = r
    group = country_names.get(cc, cc or "International")
    attrs = {
        "tvg-id": f"radio-{sid}",
        "tvg-logo": logo,
        "tvg-country": cc,
        "tvg-language": lang,
        "group-title": f"Radio · {group}",
        "radio": "true",
        "x-tier": "radio",
        "x-genre": ", ".join(tags[:3]),
        "x-codec": f"{codec} {kbps} kbps".strip() if kbps else codec,
    }
    return m3u.Entry(title=name, url=url, attrs=attrs)


def plan_radio(data: dict, cfg: RadioConfig, excluded=frozenset(), country_names: dict | None = None) -> RadioPlan:
    plan = RadioPlan()
    if not cfg.enabled:
        return plan
    names = country_names or {}
    rows = [r for r in data.get("rows", []) if r[0].lower() not in excluded]
    if not rows:
        return plan

    def add(rel: str, kind: str, key: str, title: str, chosen: list[list]) -> None:
        plan.files[rel] = m3u.render(
            [entry(r, names) for r in chosen], {"x-nexonic-playlist": title, "x-nexonic-tier": "radio"}
        )
        plan.index.append(
            {
                "path": rel,
                "kind": kind,
                "key": key,
                "name": title,
                "count": len(chosen),
                "url": playlist_url(rel),
                "tier": "radio",
            }
        )

    add("playlists/radio/all.m3u", "radio-all", "all", "Free radio: all stations", rows)
    by_cc: dict[str, list] = defaultdict(list)
    for r in rows:
        if len(r[3]) == 2 and r[3].isalpha():
            by_cc[r[3].lower()].append(r)
    for cc in sorted(by_cc):
        add(
            f"playlists/radio/countries/{cc}.m3u",
            "radio-country",
            cc,
            f"Free radio: {names.get(cc.upper(), cc.upper())}",
            by_cc[cc][: cfg.per_country],
        )
    plan.stats = {"stations": len(rows), "countries": len(by_cc), "last_run": data.get("last_run")}
    return plan
