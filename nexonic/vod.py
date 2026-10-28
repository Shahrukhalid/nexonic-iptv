"""Free VOD tier: public-domain and openly licensed films and TV from the Internet Archive.

Everything here uses the Archive's free public interfaces (advanced search and the item metadata documents; no key,
no account, no paid service). An item is kept only when its metadata records a public-domain statement or an open
Creative Commons licence; the licence is stored with the item and written into every playlist entry. Files are never
downloaded or copied: a playlist entry is a direct link to the Archive's own copy (``https://archive.org/download/...``).

Storage under ``state/vod/``: ``items.json`` (accepted items, one compact row each, refreshed in daily slices) and
``progress.json`` (search cursors and counters). The generator reads only these files, so playlists are a pure
function of the cached items and ``data/community-exclusions.yaml`` (key ``vod``, Internet Archive identifiers).
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

import httpx

from . import m3u
from .community import Exclusions
from .config import DiscoveryConfig, VodConfig, playlist_url
from .fetch import FetchError, fetch_json
from .moderation import Decision, Subject, screen_subject
from .records import ROOT
from .timeutil import iso, parse_iso, utc_now

STATE_DIR = ROOT / "state" / "vod"
ITEMS_FILE = STATE_DIR / "items.json"
PROGRESS_FILE = STATE_DIR / "progress.json"
SCHEMA = 1
COLUMNS = ["id", "t", "y", "d", "lc", "ll", "co", "k", "g", "sr", "f", "sz"]
SEARCH_URL = "https://archive.org/advancedsearch.php"
METADATA_URL = "https://archive.org/metadata/"
DOWNLOAD_URL = "https://archive.org/download/"
THUMB_URL = "https://archive.org/services/img/"
NO_FILE = "-"  # the item has no playable file (cached so it is not read again)

# Search views per collection: a server-side narrowing to items that carry licence information. The decision is always
# taken again on the returned fields, so a view that matches too much only costs requests, never accuracy.
VIEWS = {
    "cc": "licenseurl:(*creativecommons.org*)",
    "rights": 'rights:("public domain")',
}
SEARCH_FIELDS = ("identifier", "title", "licenseurl", "rights", "year", "date", "runtime", "subject", "mediatype")

GENRE_KEYWORDS = {
    "comedy": ("comedy", "comedies", "sitcom", "slapstick"),
    "drama": ("drama",),
    "horror": ("horror",),
    "scifi": ("science fiction", "sci-fi", "scifi"),
    "noir": ("film noir", "noir"),
    "western": ("western",),
    "animation": ("animation", "animated", "cartoon"),
    "musical": ("musical",),
    "mystery": ("mystery", "detective"),
    "romance": ("romance",),
    "adventure": ("adventure",),
    "crime": ("crime", "gangster"),
    "war": ("world war", "war film"),
    "documentary": ("documentary",),
    "family": ("family",),
}
GENRE_LABELS = {
    "comedy": "Comedy",
    "drama": "Drama",
    "horror": "Horror",
    "scifi": "Science fiction",
    "scifi-horror": "Science fiction and horror",
    "noir": "Film noir",
    "western": "Western",
    "animation": "Animation",
    "musical": "Musical",
    "mystery": "Mystery",
    "romance": "Romance",
    "adventure": "Adventure",
    "crime": "Crime",
    "war": "War",
    "documentary": "Documentary",
    "family": "Family",
}
# Formats a player can open, best first: H.264 MP4 derivatives, other MPEG-4, the small 512Kb derivative.
FORMAT_RANK = {"h.264": 0, "h.264 hd": 0, "h.264 ia": 0, "mpeg4": 1, "512kb mpeg4": 2}
SERIES_RE = re.compile(
    r"^(?P<series>.+?)\s*(?:[-–:|,]\s*|\s+)(?:S\d{1,2}\s*E\d{1,3}|Season\s+\d+|Episode\s+\d+|Ep\.?\s*\d+|\d{1,2}x\d{2})\b",
    re.IGNORECASE,
)
_NOT_PD = re.compile(
    r"\bnot\s+(?:in\s+)?(?:the\s+)?public\s+domain|\bnon[- ]public\s+domain|\bnot\s+pd\b", re.IGNORECASE
)
_CC_LICENCE = re.compile(r"^/licenses/(by|by-sa|by-nc|by-nc-sa|by-nd|by-nc-nd)/(\d\.\d)(?:/|$)")


# ------------------------------------------------------------------------------------------------ licences
def _first(value) -> str:
    if isinstance(value, list):
        value = next((v for v in value if isinstance(v, str) and v.strip()), "")
    return value.strip() if isinstance(value, str) else ""


def licence_of(licenseurl, rights, allowed: list[str]) -> tuple[str, str] | None:
    """``(code, label)`` when the metadata records public domain or an allowed Creative Commons licence, else None.

    ``code`` is ``publicdomain`` or the CC licence type (``by``, ``by-sa`` ...). A licence URL decides first; the
    ``rights`` text is accepted only when it states public domain and does not negate it.
    """
    url = _first(licenseurl)
    if url:
        try:
            parts = urlsplit(url)
        except ValueError:
            return None
        host = (parts.hostname or "").lower()
        if parts.scheme in ("http", "https") and (
            host == "creativecommons.org" or host.endswith(".creativecommons.org")
        ):
            path = parts.path if parts.path.endswith("/") else parts.path + "/"
            if path.startswith("/publicdomain/zero/1.0"):
                found = ("publicdomain", "CC0 1.0")
            elif path.startswith("/publicdomain/mark/1.0"):
                found = ("publicdomain", "Public Domain Mark 1.0")
            elif path.startswith("/publicdomain/"):
                found = ("publicdomain", "Public domain (Creative Commons)")
            else:
                m = _CC_LICENCE.match(path)
                found = (m.group(1), f"CC {m.group(1).upper()} {m.group(2)}") if m else None
            if found:
                return found if found[0] in allowed else None
        return None  # some other licence URL: not a licence this tier accepts
    text = _first(rights)
    if text and re.search(r"public\s+domain", text, re.IGNORECASE) and not _NOT_PD.search(text):
        return ("publicdomain", "Public domain (rights statement)") if "publicdomain" in allowed else None
    return None


# ------------------------------------------------------------------------------------------------ parsing helpers
def parse_duration(value) -> int:
    """Seconds from ``5432.12``, ``1:30:12``, ``90 min`` or ``01:30`` (0 when unknown)."""
    text = _first(value)
    if not text:
        return 0
    m = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:\.\d+)?", text)
    if m:
        h, mi, se = (int(x or 0) for x in m.groups())
        return h * 3600 + mi * 60 + se
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:min(?:ute)?s?)", text, re.IGNORECASE)
    if m:
        return int(float(m.group(1)) * 60)
    try:
        return max(0, int(float(text)))
    except ValueError:
        return 0


def year_of(*values) -> int:
    for v in values:
        m = re.search(r"\b(1[89]\d\d|20\d\d)\b", _first(v))
        if m:
            return int(m.group(1))
    return 0


def series_of(title: str) -> str:
    m = SERIES_RE.match(title.strip())
    return m.group("series").strip(" -–:|,") if m else ""


def genres_of(collection_genre: str, subjects) -> list[str]:
    out = [collection_genre] if collection_genre else []
    subs = subjects if isinstance(subjects, list) else [subjects] if isinstance(subjects, str) else []
    text = " ; ".join(s.lower() for s in subs if isinstance(s, str))
    for slug, words in GENRE_KEYWORDS.items():
        if slug not in out and any(re.search(rf"\b{re.escape(w)}\b", text) for w in words):
            out.append(slug)
    return out


def pick_file(files: list[dict]) -> tuple[str, int, int] | None:
    """``(name, size, seconds)`` of the best playable file: H.264 MP4 first, then other MPEG-4, then the small
    derivative; within a format the longest file (the feature, not a trailer or an extra)."""
    best: tuple | None = None
    for f in files:
        name, fmt = f.get("name") or "", (f.get("format") or "").lower()
        if fmt not in FORMAT_RANK or not name.lower().endswith((".mp4", ".m4v")) or "/" in name:
            continue
        seconds = parse_duration(f.get("length"))
        try:
            size = int(f.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        key = (FORMAT_RANK[fmt], -seconds, -size, name)
        if best is None or key < best[0]:
            best = (key, name, size, seconds)
    return (best[1], best[2], best[3]) if best else None


def download_url(identifier: str, name: str) -> str:
    return f"{DOWNLOAD_URL}{quote(identifier, safe='')}/{quote(name, safe='/')}"


def moderation_ok(identifier: str, title: str, subjects, url: str, allow_weak: bool) -> bool:
    """Nexonic's adult-content screening on the title and subjects. Classic titles often contain words such as
    "love" or "night", which the lexicon sends to manual review; ``allow_weak`` lets those through (never a strong
    term, a denylist hit or an NSFW-listed name)."""
    subs = [s for s in (subjects if isinstance(subjects, list) else [subjects]) if isinstance(s, str)]
    verdict = screen_subject(
        Subject(id=identifier, name=title, stream_url=url, categories=[s[:40] for s in subs[:12]], epg_id=None)
    )
    if verdict.decision is Decision.PASS:
        return True
    weak_only = all("ambiguous term" in r for r in verdict.reasons)
    return allow_weak and verdict.decision is Decision.QUARANTINE and weak_only


# ------------------------------------------------------------------------------------------------ state files
def items_text(items: list[list]) -> str:
    head = {"schema": SCHEMA, "columns": COLUMNS}
    rows = ",\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in items)
    return json.dumps(head, separators=(",", ":"))[:-1] + f',"items":[\n{rows}\n]}}\n'


def save_items(items: list[list], path: Path | None = None) -> None:
    path = path or ITEMS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(items_text(sorted(items, key=lambda r: r[0])), encoding="utf-8")
    tmp.replace(path)


def load_items(path: Path | None = None) -> list[list]:
    path = path or ITEMS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if data.get("schema") != SCHEMA or data.get("columns") != COLUMNS or not isinstance(data.get("items"), list):
        return []
    return data["items"]


def load_progress(path: Path | None = None) -> dict:
    path = path or PROGRESS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": SCHEMA, "views": {}, "last_run": None}
    return (
        data
        if data.get("schema") == SCHEMA and isinstance(data.get("views"), dict)
        else {"schema": SCHEMA, "views": {}, "last_run": None}
    )


def save_progress(progress: dict, path: Path | None = None) -> None:
    path = path or PROGRESS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(progress, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


# ------------------------------------------------------------------------------------------------ refresh
def search_url(collection: str, view: str, page: int, rows: int) -> str:
    q = f"collection:({collection}) AND mediatype:(movies) AND {VIEWS[view]}"
    params = [("q", q), *[("fl[]", f) for f in SEARCH_FIELDS], ("rows", rows), ("page", page), ("output", "json")]
    params.append(("sort[]", "downloads desc"))
    return f"{SEARCH_URL}?{urlencode(params)}"


def _disc(cfg: VodConfig) -> DiscoveryConfig:
    return DiscoveryConfig(
        timeout=cfg.timeout, retries=cfg.retries, backoff_base=cfg.backoff_base, allowed_hosts=list(cfg.allowed_hosts)
    )


@dataclass
class Refresh:
    searched_pages: int = 0
    seen: int = 0
    accepted: int = 0
    rejected: Counter = field(default_factory=Counter)
    metadata_read: int = 0
    errors: list = field(default_factory=list)


def refresh(
    cfg: VodConfig,
    exclusions: Exclusions,
    *,
    now: dt.datetime | None = None,
    budget_seconds: float | None = None,
    items_path: Path | None = None,
    progress_path: Path | None = None,
    log: Callable[[str], None] = print,
    fetcher: Callable = fetch_json,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    client: httpx.Client | None = None,
    allow_weak_terms: bool | None = None,
    force: bool = False,
) -> dict:
    """One daily slice: a few search pages, then the metadata of some accepted items. Never raises for network errors."""
    now = now or utc_now()
    budget = cfg.run_budget_seconds if budget_seconds is None else budget_seconds
    out = Refresh()
    if not cfg.enabled:
        return {"enabled": False}
    allow_weak_terms = cfg.allow_weak_terms if allow_weak_terms is None else allow_weak_terms
    progress = load_progress(progress_path)
    last = progress.get("last_run")
    if last and (now - parse_iso(last)).total_seconds() < cfg.refresh_max_age_hours * 3600 and not force:
        log("vod: refreshed recently; skipping this slice")
        return {"enabled": True, "skipped": True}
    if budget < 20:
        log(f"vod: no time budget left ({budget:.0f}s); skipping")
        return {"enabled": True, "skipped": True}
    started = monotonic()
    disc = _disc(cfg)
    items = {r[0]: r for r in load_items(items_path)}
    before = len(items)
    allowed = list(cfg.allowed_licences)
    kinds = {c["id"]: c for c in cfg.collections}

    def time_left() -> bool:
        return monotonic() - started < budget

    def get(url: str):
        sleep(cfg.request_interval)
        return fetcher(url, disc, client=client, sleep=sleep)

    # 1. search slice (resume where the previous run stopped)
    views = [(c["id"], v) for c in cfg.collections for v in VIEWS]
    states = progress["views"]
    for key in [f"{c}|{v}" for c, v in views]:
        st = states.setdefault(key, {"page": 1, "done": False, "found": 0, "seen": 0, "rejected": {}})
        if st["done"] and st.get("done_at") and (now - parse_iso(st["done_at"])).days >= cfg.rescan_days:
            states[key] = {"page": 1, "done": False, "found": 0, "seen": 0, "rejected": {}}
    pages_left = cfg.search_pages_per_run
    todo = [(c, v) for c, v in views if not states[f"{c}|{v}"]["done"]]
    while pages_left > 0 and todo and time_left() and len(items) < cfg.max_items:
        collection, view = todo.pop(0)
        st = states[f"{collection}|{view}"]
        try:
            data = get(search_url(collection, view, st["page"], cfg.rows_per_page))
            resp = data["response"]
            docs = resp["docs"]
            found = int(resp.get("numFound", 0))
        except (FetchError, KeyError, TypeError, ValueError) as exc:
            out.errors.append(f"search {collection}/{view}: {exc}")
            log(f"vod: search of {collection} ({view}) failed ({exc}); will resume next run")
            continue
        pages_left -= 1
        out.searched_pages += 1
        st["found"] = found
        for doc in docs:
            if len(items) >= cfg.max_items:
                break
            out.seen += 1
            st["seen"] = st.get("seen", 0) + 1
            reason = _accept(doc, collection, kinds[collection], allowed, exclusions, allow_weak_terms, items)
            if reason:
                out.rejected[reason] += 1
                st["rejected"][reason] = st["rejected"].get(reason, 0) + 1
        if not docs or st["page"] * cfg.rows_per_page >= found:
            st["done"], st["done_at"] = True, iso(now)
        else:
            st["page"] += 1
            todo.append((collection, view))
    out.accepted = len(items) - before

    # 2. metadata slice: resolve the playable file of accepted items that do not have one yet
    pending = [r for r in sorted(items.values(), key=lambda r: r[0]) if r[10] == ""]
    for row in pending[: cfg.metadata_per_run]:
        if not time_left():
            break
        try:
            doc = get(f"{METADATA_URL}{quote(row[0], safe='')}")
        except (FetchError, ValueError) as exc:
            out.errors.append(f"metadata {row[0]}: {exc}")
            continue
        out.metadata_read += 1
        _apply_metadata(row, doc, allowed, exclusions, allow_weak_terms)
    for rid in [rid for rid, r in items.items() if r[10] == "-DROP-"]:
        del items[rid]

    progress["last_run"] = iso(now)
    progress["counters"] = {
        "searched_pages": out.searched_pages,
        "seen": out.seen,
        "rejected": dict(sorted(out.rejected.items())),
        "metadata_read": out.metadata_read,
    }
    save_items(list(items.values()), items_path)
    save_progress(progress, progress_path)
    log(
        f"vod: {out.searched_pages} search page(s), {out.seen} entries read, {out.metadata_read} metadata document(s); "
        f"{len(items)} item(s) cached, {sum(1 for r in items.values() if r[10] not in ('', NO_FILE))} playable"
    )
    return {
        "enabled": True,
        "searched_pages": out.searched_pages,
        "seen": out.seen,
        "accepted": out.accepted,
        "rejected": dict(out.rejected),
        "metadata_read": out.metadata_read,
        "items": len(items),
        "errors": out.errors,
    }


def _accept(doc, collection, ccfg, allowed, exclusions, allow_weak, items) -> str | None:
    """Add a search result to ``items`` when it passes every rule; return the rejection reason otherwise."""
    ident = _first(doc.get("identifier"))
    title = _first(doc.get("title"))
    if not ident or not title or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,200}", ident):
        return "bad-identifier-or-title"
    if _first(doc.get("mediatype")) not in ("", "movies"):
        return "not-a-movie"
    if ident.lower() in exclusions.vod:
        return "takedown-list"
    lic = licence_of(doc.get("licenseurl"), doc.get("rights"), allowed)
    if not lic:
        return "no-open-licence"
    if not moderation_ok(ident, title, doc.get("subject"), f"{DOWNLOAD_URL}{ident}", allow_weak):
        return "adult-screening"
    if ident in items:
        return None
    kind = ccfg["kind"]
    items[ident] = [
        ident,
        title[:150],
        year_of(doc.get("year"), doc.get("date")),
        parse_duration(doc.get("runtime")),
        lic[0],
        lic[1],
        collection,
        kind,
        genres_of(ccfg.get("genre", ""), doc.get("subject")),
        series_of(title) if kind == "series" else "",
        "",
        0,
    ]
    return None


def _apply_metadata(row: list, doc: dict, allowed, exclusions, allow_weak) -> None:
    """Fill the file of an item from its metadata document, or mark the item for removal / as having no file."""
    meta = doc.get("metadata") or {}
    flags = " ".join(str(meta.get(k, "")).lower() for k in ("access-restricted-item", "noindex"))
    if doc.get("is_dark") or "true" in flags:
        row[10] = "-DROP-"
        return
    lic = licence_of(meta.get("licenseurl"), meta.get("rights"), allowed)
    if not lic or row[0].lower() in exclusions.vod:
        row[10] = "-DROP-"  # the item's own metadata no longer carries an accepted licence
        return
    row[4], row[5] = lic
    picked = pick_file(doc.get("files") or [])
    if not picked:
        row[10] = NO_FILE
        return
    name, size, seconds = picked
    row[10], row[11] = name, size
    row[3] = seconds or row[3]


# ------------------------------------------------------------------------------------------------ playlists
@dataclass
class VodPlan:
    files: dict = field(default_factory=dict)
    index: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _entry(row: list) -> m3u.Entry:
    ident, title, year, seconds, _lc, label, _co, kind, genres, series, fname, _sz = row
    if kind == "series":
        group = series or "Classic TV"
    else:
        group = GENRE_LABELS.get(genres[0], "Movies") if genres else "Movies"
    attrs = {
        "tvg-name": title,
        "tvg-logo": f"{THUMB_URL}{quote(ident, safe='')}",
        "group-title": group,
        "x-tier": "free-vod",
        "x-type": kind,
        "x-licence": label,
        "x-year": str(year) if year else "",
        "x-source": f"https://archive.org/details/{quote(ident, safe='')}",
    }
    return m3u.Entry(
        title=f"{title} ({year})" if year else title,
        url=download_url(ident, fname),
        attrs=attrs,
        duration=str(seconds) if seconds else "-1",
    )


def plan_vod(items: list[list], exclusions: Exclusions, cfg: VodConfig, progress: dict | None = None) -> VodPlan:
    plan = VodPlan()
    if not cfg.enabled or not items:
        return plan
    allowed = set(cfg.allowed_licences)
    usable = []
    dropped: Counter = Counter()
    for r in sorted(items, key=lambda r: (r[1].casefold(), r[0])):
        if r[10] in ("", NO_FILE):
            dropped["no-playable-file-yet" if r[10] == "" else "no-playable-file"] += 1
        elif r[0].lower() in exclusions.vod:
            dropped["takedown-list"] += 1
        elif r[4] not in allowed:
            dropped["licence-not-allowed"] += 1
        elif not moderation_ok(r[0], r[1], r[8], download_url(r[0], r[10]), cfg.allow_weak_terms):
            dropped["adult-screening"] += 1
        else:
            usable.append(r)
    movies = [r for r in usable if r[7] == "movie"]
    series = [r for r in usable if r[7] == "series"]

    def add(rel: str, kind: str, key: str, name: str, rows: list[list]) -> None:
        if not rows:
            return
        plan.files[rel] = m3u.render(
            [_entry(r) for r in rows], {"x-nexonic-playlist": name, "x-nexonic-tier": "free-vod"}
        )
        plan.index.append(
            {
                "path": rel,
                "kind": kind,
                "key": key,
                "name": name,
                "count": len(rows),
                "url": playlist_url(rel),
                "tier": "vod",
            }
        )

    add("playlists/vod/movies.m3u", "vod-movies", "movies", "Free VOD: movies", movies)
    add(
        "playlists/vod/series.m3u",
        "vod-series",
        "series",
        "Free VOD: series",
        sorted(series, key=lambda r: ((r[9] or "~").casefold(), r[1].casefold(), r[0])),
    )
    by_genre: dict[str, list[list]] = defaultdict(list)
    by_decade: dict[str, list[list]] = defaultdict(list)
    for r in usable:
        for g in r[8]:
            by_genre[g].append(r)
        if r[2]:
            by_decade[f"{r[2] // 10 * 10}s"].append(r)
    for g in sorted(by_genre):
        add(f"playlists/vod/genres/{g}.m3u", "vod-genre", g, f"Free VOD: {GENRE_LABELS.get(g, g)}", by_genre[g])
    for d in sorted(by_decade):
        add(f"playlists/vod/decades/{d}.m3u", "vod-decade", d, f"Free VOD: {d}", by_decade[d])
    plan.stats = {
        "items": len(usable),
        "movies": len(movies),
        "series_items": len(series),
        "cached_items": len(items),
        "not_published": dict(sorted(dropped.items())),
        "by_licence": dict(sorted(Counter(r[5] for r in usable).items())),
        "by_collection": dict(sorted(Counter(r[6] for r in usable).items())),
        "playlist_files": len(plan.files),
        "search": (progress or {}).get("counters"),
        "last_run": (progress or {}).get("last_run"),
    }
    return plan
