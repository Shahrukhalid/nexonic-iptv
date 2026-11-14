"""Open media VOD tier: films, documentaries, animation and science videos from Wikimedia Commons.

Every file on Commons carries a free licence or is in the public domain; only the licences in ``[media]
allowed_licences`` are published, and each entry names its licence and author. Entries link the original file on
Commons' own servers; nothing is copied. Each daily run reads a few result pages per search and resumes where the
previous run stopped; a finished search starts over after ``rescan_days``. The takedown list (key ``media``) applies.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from . import m3u
from .config import DiscoveryConfig, playlist_url
from .extras_config import MediaConfig
from .fetch import FetchError, fetch_json
from .moderation import Decision, Subject, screen_subject
from .records import ROOT, normalise_url
from .timeutil import iso, parse_iso, utc_now

STATE_DIR = ROOT / "state" / "media"
ITEMS_FILE = STATE_DIR / "items.json"
API = "https://commons.wikimedia.org/w/api.php"
SCHEMA = 1
COLUMNS = ["file", "title", "url", "seconds", "licence", "label", "genre", "year", "author", "thumb"]
GENRE_LABELS = {
    "films": "Films",
    "silent": "Silent films",
    "documentary": "Documentaries",
    "animation": "Animation",
    "science": "Science and space",
    "history": "History and newsreels",
}
_LIC = re.compile(r"^(cc-by-sa|cc-by|cc0|pd)(?:-\d|$)")
_TAGS = re.compile(r"<[^>]+>")


def licence_of(meta: dict) -> tuple[str, str] | None:
    raw = str((meta.get("License") or {}).get("value", "")).strip().lower()
    m = _LIC.match(raw)
    if not m:
        return None
    label = _TAGS.sub("", str((meta.get("LicenseShortName") or {}).get("value", ""))).strip() or raw
    return m.group(1), html.unescape(label)[:60]


def _text(meta: dict, key: str, limit: int = 120) -> str:
    return " ".join(html.unescape(_TAGS.sub(" ", str((meta.get(key) or {}).get("value", "")))).split())[:limit]


def year_of(meta: dict) -> int:
    m = re.search(r"\b(18[89]\d|19\d\d|20\d\d)\b", _text(meta, "DateTimeOriginal", 60))
    return int(m.group(1)) if m else 0


def title_of(file: str, meta: dict) -> str:
    name = _text(meta, "ObjectName")
    if not name:
        name = re.sub(r"\.(webm|ogv|ogg|mp4|mpg|mpeg)$", "", file.removeprefix("File:"), flags=re.I).replace("_", " ")
    return name


def accept(page: dict, genre: str, cfg: MediaConfig) -> tuple[list | None, str]:
    """A cache row for one API page, or (None, reason)."""
    file = page.get("title", "")
    info = (page.get("imageinfo") or [{}])[0]
    meta = info.get("extmetadata") or {}
    if info.get("mediatype") != "VIDEO":
        return None, "not-video"
    url = info.get("url", "")
    p = urlsplit(url)
    if p.scheme != "https" or p.hostname != "upload.wikimedia.org" or " " in url:
        return None, "bad-url"
    lic = licence_of(meta)
    if not lic or lic[0] not in cfg.allowed_licences:
        return None, "licence-not-allowed"
    seconds = int(float(info.get("duration") or 0))
    if seconds and seconds < cfg.min_seconds:
        return None, "too-short"
    if not seconds and int(info.get("size") or 0) < 20_000_000:
        return None, "too-short"
    title = title_of(file, meta)
    cats = [c for c in _text(meta, "Categories", 600).split("|") if c][:12]
    verdict = screen_subject(
        Subject(id=file, name=title, stream_url=url, categories=[c[:40] for c in cats], epg_id=None)
    )
    if verdict.decision is not Decision.PASS:
        return None, "adult-screening"
    thumb = (
        info.get("thumburl", "") if str(info.get("thumburl", "")).startswith("https://upload.wikimedia.org/") else ""
    )
    return [file, title, url, seconds, lic[0], lic[1], genre, year_of(meta), _text(meta, "Artist", 80), thumb], ""


def load(path: Path | None = None) -> dict:
    path = path or ITEMS_FILE
    empty = {"schema": SCHEMA, "last_run": None, "progress": {}, "rows": []}
    if not path.exists():
        return empty
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if data.get("schema") == SCHEMA else empty


def save(data: dict, path: Path | None = None) -> None:
    path = path or ITEMS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = ",\n ".join(json.dumps(r, ensure_ascii=False) for r in data["rows"])
    head = {k: data[k] for k in ("schema", "last_run", "progress")}
    path.write_text(
        json.dumps(head, ensure_ascii=False)[:-1] + f', "columns": {json.dumps(COLUMNS)},\n"rows": [\n {rows}\n]}}\n',
        encoding="utf-8",
    )


def search_url(q: str, offset: int) -> str:
    return (
        API
        + "?"
        + urlencode(
            {
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrnamespace": 6,
                "gsrsearch": f"{q} filetype:video",
                "gsrlimit": 50,
                "gsroffset": offset,
                "prop": "imageinfo",
                "iiprop": "url|mediatype|size|extmetadata",
                "iiurlwidth": 320,
                "iiextmetadatafilter": "License|LicenseShortName|Artist|ObjectName|DateTimeOriginal|Categories",
            }
        )
    )


def refresh(
    cfg: MediaConfig,
    excluded=frozenset(),
    *,
    now: dt.datetime | None = None,
    path: Path | None = None,
    fetcher: Callable = fetch_json,
    sleep: Callable[[float], None] | None = None,
    log: Callable[[str], None] = print,
    force: bool = False,
) -> dict:
    if not cfg.enabled:
        return {"enabled": False}
    import time

    sleep = sleep or time.sleep
    now = now or utc_now()
    data = load(path)
    if (
        data["last_run"]
        and not force
        and (now - parse_iso(data["last_run"])).total_seconds() < cfg.refresh_max_age_hours * 3600
    ):
        log("media: refreshed recently; skipping")
        return {"enabled": True, "skipped": True}
    disc = DiscoveryConfig(
        timeout=cfg.timeout, retries=cfg.retries, backoff_base=cfg.backoff_base, allowed_hosts=list(cfg.allowed_hosts)
    )
    rows = {r[0]: r for r in data["rows"]}
    urls = {normalise_url(r[2]) for r in data["rows"]}
    prog = data["progress"]
    searches = cfg.searches
    for s in searches:
        st = prog.setdefault(s["q"], {"offset": 0, "done": False})
        if st["done"] and st.get("done_at") and (now - parse_iso(st["done_at"])).days >= cfg.rescan_days:
            prog[s["q"]] = {"offset": 0, "done": False}
    pages, rejected, added, errors = cfg.pages_per_run, Counter(), 0, []
    started = time.monotonic()
    while pages > 0 and time.monotonic() - started < cfg.run_budget_seconds and len(rows) < cfg.max_items:
        todo = [s for s in searches if not prog[s["q"]]["done"]]
        if not todo:
            break
        s = todo[0]
        st = prog[s["q"]]
        sleep(cfg.request_interval)
        try:
            body = fetcher(search_url(s["q"], st["offset"]), disc)
        except FetchError as exc:
            errors.append(str(exc)[:200])
            break
        pages -= 1
        for page in ((body or {}).get("query") or {}).get("pages", {}).values():
            row, why = accept(page, s.get("genre", "films"), cfg)
            if row and row[0].lower() in excluded:
                row, why = None, "takedown-list"
            if row is None:
                rejected[why] += 1
            elif row[0] not in rows and normalise_url(row[2]) not in urls:
                urls.add(normalise_url(row[2]))
                rows[row[0]] = row
                added += 1
        nxt = ((body or {}).get("continue") or {}).get("gsroffset")
        if nxt is None:
            st.update(done=True, done_at=iso(now))
        else:
            st["offset"] = int(nxt)
    data.update(last_run=iso(now), progress=prog, rows=sorted(rows.values(), key=lambda r: (r[1].casefold(), r[0])))
    save(data, path)
    summary = {
        "enabled": True,
        "items": len(rows),
        "added": added,
        "rejected": dict(sorted(rejected.items())),
        "errors": errors,
    }
    log(f"media: {summary}")
    return summary


@dataclass
class MediaPlan:
    files: dict = field(default_factory=dict)
    index: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def entry(r: list) -> m3u.Entry:
    file, title, url, seconds, _lic, label, genre, year, author, thumb = r
    return m3u.Entry(
        title=f"{title} ({year})" if year else title,
        url=url,
        duration=str(seconds or -1),
        attrs={
            "tvg-logo": thumb,
            "group-title": f"Open media · {GENRE_LABELS.get(genre, genre.title())}",
            "x-tier": "media",
            "x-licence": label,
            "x-author": author,
            "x-source": "https://commons.wikimedia.org/wiki/" + file.replace(" ", "_"),
        },
    )


def plan_media(data: dict, cfg: MediaConfig, excluded=frozenset()) -> MediaPlan:
    plan = MediaPlan()
    if not cfg.enabled:
        return plan
    allowed = set(cfg.allowed_licences)
    rows = [r for r in data.get("rows", []) if r[4] in allowed and r[0].lower() not in excluded]
    if not rows:
        return plan

    def add(rel: str, kind: str, key: str, name: str, chosen: list) -> None:
        plan.files[rel] = m3u.render(
            [entry(r) for r in chosen], {"x-nexonic-playlist": name, "x-nexonic-tier": "media"}
        )
        plan.index.append(
            {
                "path": rel,
                "kind": kind,
                "key": key,
                "name": name,
                "count": len(chosen),
                "url": playlist_url(rel),
                "tier": "media",
            }
        )

    add("playlists/media/all.m3u", "media-all", "all", "Open media: everything", rows)
    by_genre = defaultdict(list)
    for r in rows:
        by_genre[r[6]].append(r)
    for g in sorted(by_genre):
        add(f"playlists/media/{g}.m3u", "media-genre", g, f"Open media: {GENRE_LABELS.get(g, g.title())}", by_genre[g])
    plan.stats = {
        "items": len(rows),
        "by_licence": dict(sorted(Counter(r[5] for r in rows).items())),
        "last_run": data.get("last_run"),
    }
    return plan
