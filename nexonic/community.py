"""Community live tier: a large catalogue of publicly listed free streams, kept apart from the official tier.

Source: the streams listed in iptv-org/iptv together with the channel metadata of iptv-org/database (public domain
index of publicly available streams that honours takedown requests), plus the openly licensed lists configured under
``[[discovery.extra_m3u]]``. A stream enters the catalogue only when every filter in ``FILTERS`` holds; the official
tier's owner-domain rule is deliberately not part of them, which is why these streams are published in separate
playlists and are never labelled "official".

Storage (committed by the daily workflow, which only commits ``state/``, ``reports/`` and ``playlists/``):

* ``state/community/catalog.json``  the filtered catalogue, one compact row per stream, rebuilt by the daily run.
* ``state/community/history.json``  the last few check results per stream (compact rows).

Checking is a rotating, budgeted slice of the catalogue per run (never-checked first, then oldest-checked) using the
same multi-level checker as the official tier, without FFprobe. A stream is *verified* only when its latest check
worked within ``verified_days``; everything else is *untested* (never checked, stale or inconclusive) or, after a
failed check, held back from every playlist until a later check works. Untested streams are never called working.
"""

from __future__ import annotations

import asyncio
import csv
import datetime as dt
import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import NamedTuple
from urllib.parse import urlsplit

import yaml

from . import lifecycle, m3u
from .checker import Limits, check_all
from .config import CommunityConfig, DiscoveryConfig, QuarantineConfig, playlist_url
from .dedup import fold_name, stream_key
from .fetch import ExtraPlaylist, FetchError, fetch_extra_m3u, fetch_iptv_org, fetch_iptv_org_raw
from .iptvorg import (
    CATEGORY_MAP,
    EXCLUDED_NAME_TERMS,
    ISO3_TO_1,
    PAID_HOST_PATTERNS,
    PAID_NAME_TERMS,
    SANCTIONED_COUNTRIES,
    SANCTIONED_NAME_TERMS,
    SANCTIONED_OWNER_TERMS,
    SPECIAL_OPTION_PREFIXES,
    parse_streams,
    resolution_rank,
)
from .moderation import Decision, Subject, screen_subject
from .quality import BUCKET_LABELS, QUALITY_BUCKETS, height_of, quality_bucket
from .records import DATA, ROOT, LoadResult
from .reference import CATEGORIES, LANGUAGES, countries
from .safety import check_url_policy
from .status import FAILURES, CheckResult, Status
from .timeutil import iso, parse_iso, utc_now

STATE_DIR = ROOT / "state" / "community"
CATALOG_FILE = STATE_DIR / "catalog.json"
HISTORY_FILE = STATE_DIR / "history.json"
EXCLUSIONS_FILE = DATA / "community-exclusions.yaml"
SCHEMA = 1
COLUMNS = ["id", "ch", "fd", "name", "url", "cc", "lg", "ct", "q", "lo", "fl", "sr"]

FLAG_GEO_BLOCKED = 1  # iptv-org labels the stream "[Geo-blocked]"
FLAG_NOT_247 = 2  # iptv-org labels the stream "[Not 24/7]"

# iptv-org categories the project's category set has no entry for.
EXTRA_CATEGORY_MAP = {"shop": "lifestyle", "religious": "culture", "interactive": "entertainment"}
NON_STREAM_EXTENSIONS = (
    ".mp4",
    ".mkv",
    ".ts",
    ".mp3",
    ".aac",
    ".m4a",
    ".flv",
    ".avi",
    ".webm",
    ".ogg",
    ".wav",
    ".pls",
    ".asx",
    ".jpg",
    ".png",
    ".html",
)
GENERIC_FEED_NAMES = {"", "sd", "hd", "fhd", "uhd", "4k", "main"}

# Status codes of the compact history rows.
STATUS_CODES = {
    Status.VERIFIED_WORKING: "W",
    Status.UNAVAILABLE: "U",
    Status.GEO_RESTRICTED: "G",
    Status.AUTH_REQUIRED: "A",
    Status.RATE_LIMITED: "R",
    Status.TIMEOUT: "T",
    Status.INVALID_STREAM: "I",
    Status.UNSUPPORTED: "S",
    Status.UNKNOWN: "K",
}
CODE_STATUS = {v: k for k, v in STATUS_CODES.items()}

# Filters in the order they are applied; the catalogue report lists how many streams remain after each of them.
FILTERS = (
    "has-database-entry",
    "not-nsfw-or-blocklisted",
    "not-closed",
    "no-special-headers",
    "url-policy",
    "hls-or-dash",
    "policy-exclusions",
    "adult-screening-pass",
    "community-exclusions",
)


# ------------------------------------------------------------------------------------------------ data layout
class CStream(NamedTuple):
    id: str  # stable: iptv-org channel id + hash of the normalised stream URL
    ch: str  # iptv-org channel id
    fd: str  # iptv-org feed id ("" = main feed)
    name: str
    url: str
    cc: str  # ISO 3166-1 alpha-2, lower case
    lg: list  # ISO 639-1 codes (may be empty when the database lists none the project supports)
    ct: list  # project categories
    q: int  # source quality label as a height (720, 1080 ...) or 0
    lo: str  # logo URL from iptv-org/database, or ""
    fl: int  # FLAG_* bits
    sr: str  # source list the stream was read from

    @property
    def epg_id(self) -> str:
        return f"{self.ch}@{self.fd}" if self.fd else self.ch

    @property
    def host(self) -> str:
        try:
            return (urlsplit(self.url).hostname or "").lower()
        except ValueError:
            return ""

    @property
    def protocol(self) -> str:
        return protocol_of(self.url) or "hls"


def protocol_of(url: str) -> str | None:
    """``hls`` or ``dash`` for streams the checker can verify, None for direct media files and other formats."""
    try:
        path = urlsplit(url).path.lower()
    except ValueError:
        return None
    if path.endswith(".mpd"):
        return "dash"
    if path.endswith(NON_STREAM_EXTENSIONS):
        return None
    return "hls"


def stream_id(channel: str, url: str) -> str:
    return f"{channel}~{hashlib.sha1(stream_key(url).encode()).hexdigest()[:8]}"  # noqa: S324 - identifier only


# ------------------------------------------------------------------------------------------------ exclusions
@dataclass
class Exclusions:
    """Takedown list (``data/community-exclusions.yaml``). Applied at catalogue build and at every generation."""

    urls: set = field(default_factory=set)  # stream_key values
    hosts: set = field(default_factory=set)
    channels: set = field(default_factory=set)  # lower-case iptv-org channel ids and community stream ids
    vod: set = field(default_factory=set)  # lower-case Internet Archive identifiers

    def reason(self, ch: str, sid: str, url: str) -> str | None:
        if ch.lower() in self.channels or sid.lower() in self.channels:
            return "channel"
        if stream_key(url) in self.urls:
            return "url"
        try:
            host = (urlsplit(url).hostname or "").lower().rstrip(".")
        except ValueError:
            return None
        if host and any(host == h or host.endswith("." + h) for h in self.hosts):
            return "host"
        return None


def _as_list(raw, key: str) -> list[str]:
    value = raw.get(key) or []
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ValueError(f"{key} in the exclusions file must be a list of strings")
    return [x.strip() for x in value if x.strip()]


def load_exclusions(path: Path | None = None) -> Exclusions:
    path = path or EXCLUSIONS_FILE
    if not path.exists():
        return Exclusions()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("the exclusions file must be a mapping")
    unknown = set(raw) - {"urls", "hosts", "channels", "vod"}
    if unknown:
        raise ValueError(f"unknown key(s) in the exclusions file: {', '.join(sorted(unknown))}")
    return Exclusions(
        urls={stream_key(u) for u in _as_list(raw, "urls")},
        hosts={h.lower().strip(".") for h in _as_list(raw, "hosts")},
        channels={c.lower() for c in _as_list(raw, "channels")},
        vod={v.lower() for v in _as_list(raw, "vod")},
    )


# ------------------------------------------------------------------------------------------------ official overlap
@dataclass
class OfficialContext:
    """What the official tier (and maintainer decisions) already cover; the community tier never repeats it."""

    stream_keys: set = field(default_factory=set)
    epg_bases: set = field(default_factory=set)  # lower-case iptv-org channel ids (the part before "@")
    names: set = field(default_factory=set)  # (country, folded name) of approved records

    def overlap(self, ch: str, cc: str, name: str, url: str) -> str | None:
        if stream_key(url) in self.stream_keys:
            return "stream"
        if ch.lower() in self.epg_bases:
            return "channel"
        if (cc, fold_name(name)) in self.names:
            return "name"
        return None


def official_context(records: LoadResult) -> OfficialContext:
    """Approved records are official; pending and rejected ones were not accepted, so the community tier does not
    list their streams or channels either (a maintainer decision wins over a public list)."""
    ctx = OfficialContext()
    for status, group in records.channels.items():
        for ch in group:
            ctx.stream_keys.add(stream_key(ch.stream.url))
            if ch.epg_id:
                ctx.epg_bases.add(ch.epg_id.split("@")[0].lower())
            if status == "approved":
                ctx.names.add((ch.country, fold_name(ch.name)))
    return ctx


# ------------------------------------------------------------------------------------------------ catalogue build
def _read_csv(path: Path, keep: Callable[[dict], bool] | None = None) -> Iterable[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if keep is None or keep(row):
                yield row


def _safe_logo(url: str) -> str:
    url = (url or "").strip()
    if not url or len(url) > 300 or any(c.isspace() or ord(c) < 32 or c == '"' for c in url):
        return ""
    return url if check_url_policy(url, check_tokens=False).ok else ""


def _languages(code_field: str) -> list[str]:
    out: list[str] = []
    for code in (code_field or "").split(";"):
        two = code if code in LANGUAGES else ISO3_TO_1.get(code)
        if two and two in LANGUAGES and two not in out:
            out.append(two)
    return out


def _categories(raw: str) -> list[str]:
    out: list[str] = []
    for c in (raw or "").split(";"):
        mapped = CATEGORY_MAP.get(c) or EXTRA_CATEGORY_MAP.get(c)
        if mapped and mapped in CATEGORIES and mapped not in out:
            out.append(mapped)
    return out or ["general"]


def _rank(s: CStream, priority: int) -> tuple:
    return (
        not s.fl & FLAG_GEO_BLOCKED,
        not s.fl & FLAG_NOT_247,
        s.url.startswith("https"),
        s.q,
        -priority,  # an earlier source wins a tie
        s.url,
    )


def build_catalog(
    streams_dir: Path,
    database_dir: Path,
    extras: Iterable[ExtraPlaylist] = (),
    *,
    official: OfficialContext | None = None,
    exclusions: Exclusions | None = None,
    cfg: CommunityConfig | None = None,
    built_at: str | None = None,
    mode: str = "archive",
) -> tuple[dict, dict]:
    """Apply every filter to the iptv-org streams (and extra lists) and return ``(catalogue, report)``.

    The report counts the entries read, the entries remaining after each filter in ``FILTERS`` and what the
    de-duplication removed. Nothing is written here; ``save_catalog`` does that.
    """
    cfg = cfg or CommunityConfig()
    official = official or OfficialContext()
    exclusions = exclusions or Exclusions()
    cn = countries()

    sources: list[tuple[Path, str, int]] = [(p, "iptv-org", 0) for p in sorted(streams_dir.glob("*.m3u"))]
    order: dict[str, int] = {}
    for ex in extras:
        order.setdefault(ex.source, len(order) + 1)
        sources.append((ex.path, ex.source, order[ex.source]))

    # Pass 1: read the entries (stream data only) to learn which channels the database lookups are needed for.
    entries: list[tuple[dict, str, str, list[str], str, int]] = []
    for path, name, priority in sources:
        for attrs, title, url, opts in parse_streams(path):
            entries.append((attrs, title, url, opts, name, priority))
    need = {a.get("tvg-id", "").partition("@")[0] for a, *_ in entries}
    channels = {r["id"]: r for r in _read_csv(database_dir / "channels.csv", lambda r: r["id"] in need)}
    feeds: dict[tuple[str, str], dict] = {}
    main_feed: dict[str, str] = {}
    for r in _read_csv(database_dir / "feeds.csv", lambda r: r["channel"] in channels):
        feeds[(r["channel"], r["id"])] = r
        if r["is_main"] == "TRUE":
            main_feed[r["channel"]] = r["id"]
    blocked = {r["channel"] for r in _read_csv(database_dir / "blocklist.csv")}
    channel_logo: dict[str, str] = {}
    feed_logo: dict[str, str] = {}
    logo_path = database_dir / "logos.csv"
    if logo_path.exists():
        for r in _read_csv(logo_path, lambda r: r["channel"] in channels and r["in_use"] == "TRUE"):
            url = _safe_logo(r["url"])
            if url:
                (feed_logo if r["feed"] else channel_logo).setdefault(r["channel"], url)
    logos = {cid: channel_logo.get(cid) or feed_logo.get(cid, "") for cid in channels}

    report: dict = {"read": len(entries), "after": {}, "dropped": Counter(), "sources": Counter()}
    passed = Counter()
    candidates: list[tuple[CStream, int]] = []

    for attrs, title, url, opts, source, priority in entries:
        report["sources"][source] += 1
        tvg = attrs.get("tvg-id", "")
        cid, _, feed = tvg.partition("@")
        ch = channels.get(cid)
        if not ch:
            report["dropped"]["no-database-entry"] += 1
            continue
        passed["has-database-entry"] += 1
        if ch["is_nsfw"] == "TRUE" or cid in blocked or "xxx" in ch["categories"].split(";"):
            report["dropped"]["nsfw-or-blocklisted"] += 1
            continue
        passed["not-nsfw-or-blocklisted"] += 1
        if ch["closed"]:
            report["dropped"]["closed"] += 1
            continue
        passed["not-closed"] += 1
        if (
            any(k in attrs for k in ("http-referrer", "http-user-agent"))
            or any(o.startswith(SPECIAL_OPTION_PREFIXES) for o in opts)
            or "|" in url
        ):
            report["dropped"]["needs-special-headers"] += 1
            continue
        passed["no-special-headers"] += 1
        pol = check_url_policy(url, allow_restream=cfg.allow_restream_hosts, strict_tokens=True)
        if not pol.ok:
            report["dropped"][_policy_key(pol.reason)] += 1
            continue
        passed["url-policy"] += 1
        if protocol_of(url) is None:
            report["dropped"]["not-hls-or-dash"] += 1
            continue
        passed["hls-or-dash"] += 1
        owners = f"{ch['owners']} {ch['network']}".lower()
        lname = ch["name"].lower()
        host = (urlsplit(url).hostname or "").lower()
        if (
            ch["country"].lower() in SANCTIONED_COUNTRIES
            or any(t in owners for t in SANCTIONED_OWNER_TERMS)
            or any(_word(t, lname) for t in SANCTIONED_NAME_TERMS)
            or any(t in lname for t in EXCLUDED_NAME_TERMS)
            or any(t in lname for t in PAID_NAME_TERMS)
            or PAID_HOST_PATTERNS.search(host)
        ):
            report["dropped"]["policy-exclusion"] += 1
            continue
        passed["policy-exclusions"] += 1
        alt = [a for a in ch["alt_names"].split(";") if a][:5]
        verdict = screen_subject(
            Subject(
                id=cid,
                name=ch["name"],
                stream_url=url,
                alt_names=alt,
                broadcaster=(ch["owners"].split(";")[0] or ch["network"] or ch["name"]).strip(),
                website=ch["website"],
                categories=[c for c in ch["categories"].split(";") if c],
                epg_id=tvg,
            )
        )
        if verdict.decision is not Decision.PASS:
            report["dropped"][f"adult-screening-{verdict.decision.value}"] += 1
            continue
        passed["adult-screening-pass"] += 1
        country = ch["country"].lower()
        if country not in cn:
            report["dropped"]["unknown-country"] += 1
            continue
        sid = stream_id(cid, url)
        if exclusions.reason(cid, sid, url):
            report["dropped"]["community-exclusion"] += 1
            continue
        passed["community-exclusions"] += 1

        f = feeds.get((cid, feed)) or feeds.get((cid, main_feed.get(cid, ""))) or {}
        feed_id = feed
        display = ch["name"]
        if (
            feed_id
            and feed_id != main_feed.get(cid)
            and (f.get("name") or "").strip().casefold() not in GENERIC_FEED_NAMES
        ):
            display = f"{ch['name']} ({f['name'].strip()})"
        row = CStream(
            id=sid,
            ch=cid,
            fd=feed_id,
            name=display,
            url=url,
            cc=country,
            lg=_languages(f.get("languages", "")),
            ct=_categories(ch["categories"]),
            q=resolution_rank(title) or height_of(f.get("format")),
            lo=logos.get(cid, ""),
            fl=(FLAG_GEO_BLOCKED if "Geo-blocked" in title else 0) | (FLAG_NOT_247 if "Not 24/7" in title else 0),
            sr=source,
        )
        candidates.append((row, priority))

    # De-duplication: official tier first, then the same URL, then the same channel feed (best-ranked streams win).
    dedup: Counter = Counter()
    kept: list[tuple[CStream, int]] = []
    for row, priority in candidates:
        why = official.overlap(row.ch, row.cc, row.name, row.url)
        if why:
            dedup[f"official-duplicate-{why}"] += 1
            continue
        kept.append((row, priority))
    by_url: dict[str, tuple[CStream, int]] = {}
    for row, priority in kept:
        key = stream_key(row.url)
        other = by_url.get(key)
        if other is not None:
            dedup["duplicate-url"] += 1
            if _rank(row, priority) <= _rank(*other):
                continue
        by_url[key] = (row, priority)
    by_identity: dict[tuple[str, str], list[tuple[CStream, int]]] = defaultdict(list)
    for item in by_url.values():
        by_identity[(item[0].ch, item[0].fd)].append(item)
    final: list[CStream] = []
    for _ident, items in by_identity.items():
        items.sort(key=lambda it: _rank(*it), reverse=True)
        final.extend(r for r, _ in items[: cfg.streams_per_channel])
        if len(items) > cfg.streams_per_channel:
            dedup["duplicate-channel"] += len(items) - cfg.streams_per_channel
    final.sort(key=lambda s: (s.cc, s.name.casefold(), s.id))

    for name in FILTERS:
        report["after"][name] = passed[name]
    report["dropped"] = dict(sorted(report["dropped"].items()))
    report["deduplicated"] = dict(sorted(dedup.items()))
    report["catalog"] = len(final)
    report["sources"] = dict(sorted(report["sources"].items()))
    report["per_country"] = dict(Counter(s.cc for s in final).most_common())
    catalog = {
        "schema": SCHEMA,
        "built_at": built_at or iso(utc_now()),
        "source_mode": mode,
        "report": report,
        "columns": COLUMNS,
        "streams": [list(s) for s in final],
    }
    return catalog, report


def _policy_key(reason: str) -> str:
    for start, key in (
        ("port", "url-policy-port"),
        ("IP-address", "url-policy-ip-host"),
        ("tokenized", "url-policy-token"),
        ("host", "url-policy-restream-or-dynamic-dns"),
        ("scheme", "url-policy-scheme"),
        ("credentials", "url-policy-credentials"),
    ):
        if reason.startswith(start):
            return key
    return "url-policy-other"


def _word(term: str, text: str) -> bool:
    return re.search(rf"(^|\W){re.escape(term)}(\W|$)", text) is not None


# ------------------------------------------------------------------------------------------------ state files
def _dump_rows(head: dict, key: str, rows: Iterable[str]) -> str:
    """JSON with one row per line (git-friendly diffs), the rows being already serialised."""
    body = ",\n".join(rows)
    return json.dumps(head, ensure_ascii=False, separators=(",", ":"))[:-1] + f',"{key}":[\n{body}\n]}}\n'


def catalog_text(catalog: dict) -> str:
    head = {k: v for k, v in catalog.items() if k != "streams"}
    rows = (json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in catalog["streams"])
    return _dump_rows(head, "streams", rows)


def save_catalog(catalog: dict, path: Path | None = None) -> None:
    path = path or CATALOG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(catalog_text(catalog), encoding="utf-8")
    tmp.replace(path)


def load_catalog(path: Path | None = None) -> dict | None:
    """The stored catalogue, or None when there is none (or it is unreadable: the last good copy is never half-written
    because ``save_catalog`` replaces the file atomically)."""
    path = path or CATALOG_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("schema") != SCHEMA or data.get("columns") != COLUMNS or not isinstance(data.get("streams"), list):
        return None
    return data


def catalog_streams(catalog: dict | None) -> list[CStream]:
    return [CStream(*r) for r in (catalog or {}).get("streams", [])]


def history_text(history: dict[str, list[list]], keep: int) -> str:
    head = {"schema": SCHEMA, "keep": keep, "row": ["checked_at", "status", "level", "latency_ms", "height"]}
    rows = (
        json.dumps(sid, ensure_ascii=False) + ":" + json.dumps(history[sid], separators=(",", ":"))
        for sid in sorted(history)
    )
    body = ",\n".join(rows)
    return json.dumps(head, separators=(",", ":"))[:-1] + f',"streams":{{\n{body}\n}}}}\n'


def save_history(history: dict[str, list[list]], keep: int, path: Path | None = None) -> None:
    path = path or HISTORY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(history_text(history, keep), encoding="utf-8")
    tmp.replace(path)


def load_history(path: Path | None = None) -> dict[str, list[list]]:
    path = path or HISTORY_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    streams = data.get("streams")
    return streams if data.get("schema") == SCHEMA and isinstance(streams, dict) else {}


def row_of(result: CheckResult) -> list:
    height = height_of(result.details.get("max_resolution"))
    return [result.checked_at, STATUS_CODES.get(result.status, "K"), result.level, result.latency_ms or 0, height]


def results_of(sid: str, rows: list[list]) -> list[CheckResult]:
    out = []
    for checked_at, code, level, latency, height in rows:
        details = {"max_resolution": f"{height}p"} if height else {}
        out.append(
            CheckResult(
                sid,
                CODE_STATUS.get(code, Status.UNKNOWN),
                checked_at,
                level=level,
                latency_ms=latency or None,
                details=details,
            )
        )
    return out


def reference_time(history: dict[str, list[list]]) -> dt.datetime | None:
    latest = max((rows[-1][0] for rows in history.values() if rows), default=None)
    return parse_iso(latest) if latest else None


def quarantine_config(cfg: CommunityConfig) -> QuarantineConfig:
    return QuarantineConfig(
        consecutive_failures=cfg.quarantine_failures,
        distinct_days=cfg.quarantine_distinct_days,
        intermittent_window_days=cfg.intermittent_window_days,
    )


# ------------------------------------------------------------------------------------------------ classification
@dataclass
class Evaluated:
    stream: CStream
    state: str  # verified | untested | failing
    lifecycle: lifecycle.LifecycleInfo
    height: int  # measured height of the latest working check, 0 when not recorded
    last_checked: str | None


def evaluate_streams(
    streams: list[CStream], history: dict[str, list[list]], cfg: CommunityConfig, ref: dt.datetime | None
) -> list[Evaluated]:
    q = quarantine_config(cfg)
    out = []
    for s in streams:
        results = results_of(s.id, history.get(s.id, []))
        info = lifecycle.evaluate(results, ref, q)
        tested = [r for r in results if r.status is not Status.NOT_TESTED]
        if lifecycle.in_verified(results, ref, q, cfg.verified_days * 24):
            state = "verified"
        elif tested and tested[-1].status in FAILURES:
            state = "failing"
        else:
            state = "untested"
        height = next(
            (
                height_of(r.details.get("max_resolution"))
                for r in reversed(results)
                if r.status is Status.VERIFIED_WORKING
            ),
            0,
        )
        out.append(Evaluated(s, state, info, height, tested[-1].checked_at if tested else None))
    return out


def apply_tier_rules(
    streams: list[CStream],
    official: OfficialContext,
    exclusions: Exclusions,
    allow_restream: bool = False,
) -> tuple[list[CStream], dict[str, int]]:
    """Generation-time rules: the current URL policy, official records and takedown entries win, however (and
    whenever) the catalogue was built."""
    kept: list[CStream] = []
    removed: Counter = Counter()
    for s in streams:
        pol = check_url_policy(s.url, allow_restream=allow_restream, strict_tokens=True)
        if not pol.ok:
            removed[_policy_key(pol.reason)] += 1
        elif exclusions.reason(s.ch, s.id, s.url):
            removed["excluded-by-takedown-list"] += 1
        elif official.overlap(s.ch, s.cc, s.name, s.url):
            removed["official-duplicate"] += 1
        else:
            kept.append(s)
    return kept, dict(removed)


# ------------------------------------------------------------------------------------------------ rotation
def _stable(sid: str) -> str:
    return hashlib.sha1(sid.encode()).hexdigest()  # noqa: S324 - ordering only


def select_for_check(
    streams: list[CStream],
    history: dict[str, list[list]],
    now: dt.datetime,
    cfg: CommunityConfig,
) -> list[CStream]:
    """Pick this run's slice: never-checked streams first, then the oldest-checked ones.

    A stream whose last check failed waits ``retry_failed_days`` (``retry_quarantined_days`` when quarantined) before
    it is tried again; every other stream waits ``min_recheck_hours``. At most ``max_per_host_per_run`` streams of one
    host and ``max_checks_per_run`` in total are selected.
    """
    q = quarantine_config(cfg)
    never: list[tuple[str, CStream]] = []
    due: list[tuple[str, str, CStream]] = []
    for s in streams:
        rows = history.get(s.id) or []
        if not rows:
            never.append((_stable(s.id), s))
            continue
        last_at, last_code = rows[-1][0], rows[-1][1]
        wait = dt.timedelta(hours=cfg.min_recheck_hours)
        if CODE_STATUS.get(last_code) in FAILURES:
            quarantined = lifecycle.is_quarantined(results_of(s.id, rows), q)
            wait = dt.timedelta(days=cfg.retry_quarantined_days if quarantined else cfg.retry_failed_days)
        if parse_iso(last_at) + wait <= now:
            due.append((last_at, _stable(s.id), s))
    ordered = [s for _, s in sorted(never, key=lambda t: t[0])] + [s for _, _, s in sorted(due, key=lambda t: t[:2])]
    per_host: Counter = Counter()
    chosen: list[CStream] = []
    for s in ordered:
        if len(chosen) >= cfg.max_checks_per_run:
            break
        if per_host[s.host] >= cfg.max_per_host_per_run:
            continue
        per_host[s.host] += 1
        chosen.append(s)
    return chosen


@dataclass
class CheckTarget:
    """The part of a record the checker reads (id, stream URL and protocol, known geo restriction)."""

    id: str
    stream: SimpleNamespace
    geo: SimpleNamespace

    @classmethod
    def of(cls, s: CStream) -> CheckTarget:
        return cls(
            s.id,
            SimpleNamespace(url=s.url, protocol=s.protocol),
            SimpleNamespace(restricted=True if s.fl & FLAG_GEO_BLOCKED else "unknown"),
        )


def limits_for(cfg: CommunityConfig, budget_seconds: float) -> Limits:
    return Limits(
        timeout=cfg.timeout,
        concurrency=max(1, min(cfg.concurrency, cfg.max_concurrency)),
        retries=cfg.retries,
        backoff_base=cfg.backoff_base,
        per_host_interval=cfg.per_host_interval,
        channel_timeout=cfg.channel_timeout,
        use_ffprobe=False,
        run_budget=budget_seconds,
        allow_restream=cfg.allow_restream_hosts,
    )


def merge_results(
    history: dict[str, list[list]], results: list[CheckResult], keep: int, live_ids: set[str]
) -> dict[str, list[list]]:
    """Append this run's results (not-tested ones are skipped), keep ``keep`` rows per stream, drop retired streams."""
    merged = {sid: rows for sid, rows in history.items() if sid in live_ids}
    for r in sorted(results, key=lambda r: r.checked_at):
        if r.status is Status.NOT_TESTED or r.channel_id not in live_ids:
            continue
        rows = merged.setdefault(r.channel_id, [])
        rows.append(row_of(r))
        del rows[:-keep]
    return merged


# ------------------------------------------------------------------------------------------------ daily run
def download_sources(
    disc: DiscoveryConfig,
    tmp: Path,
    log: Callable[[str], None] = print,
    *,
    fetch_archive=fetch_iptv_org,
    fetch_raw=fetch_iptv_org_raw,
    fetch_extra=fetch_extra_m3u,
) -> tuple[Path, Path, list[ExtraPlaylist], str]:
    """Bounded downloads through nexonic/fetch.py: repository archives first, raw files as a fallback."""
    mode = "archive"
    try:
        got = fetch_archive(disc, tmp)
    except FetchError as exc:
        log(f"community: archive download failed ({exc}); trying raw files")
        mode = "raw"
        got = fetch_raw(disc, tmp / "raw")
    extras: list[ExtraPlaylist] = []
    if disc.extra_m3u:
        missing: list[str] = []
        extras = fetch_extra(disc, tmp, missing=missing)
        for label in missing:
            log(f"community: {label} no longer exists upstream; skipped")
    return got["streams"], got["database"], extras, mode


def catalog_is_stale(catalog: dict | None, cfg: CommunityConfig, now: dt.datetime) -> bool:
    if not catalog:
        return True
    try:
        built = parse_iso(catalog["built_at"])
    except (KeyError, ValueError):
        return True
    return (now - built).total_seconds() > cfg.refresh_max_age_hours * 3600


def refresh_catalog(
    disc: DiscoveryConfig,
    cfg: CommunityConfig,
    official: OfficialContext,
    exclusions: Exclusions,
    *,
    now: dt.datetime | None = None,
    path: Path | None = None,
    log: Callable[[str], None] = print,
    downloader=download_sources,
) -> dict | None:
    """Rebuild the catalogue; on any failure (or an implausibly small result) the last good snapshot stays.

    Returns the catalogue now in effect (None when there is none at all).
    """
    import tempfile

    now = now or utc_now()
    old = load_catalog(path)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            streams_dir, database_dir, extras, mode = downloader(disc, Path(tmp), log)
            new, report = build_catalog(
                streams_dir,
                database_dir,
                extras,
                official=official,
                exclusions=exclusions,
                cfg=cfg,
                built_at=iso(now),
                mode=mode,
            )
    except (FetchError, OSError, ValueError, KeyError, csv.Error) as exc:
        log(f"community: catalogue refresh failed ({type(exc).__name__}: {exc}); keeping the last good snapshot")
        return old
    count = len(new["streams"])
    previous = len((old or {}).get("streams", []))
    if count == 0 or (previous and count < previous * cfg.min_catalog_ratio):
        log(
            f"community: the rebuilt catalogue has {count} streams against {previous} before; "
            "rejected, keeping the last good snapshot"
        )
        return old
    save_catalog(new, path)
    log(f"community: catalogue rebuilt with {count} streams from {report['read']} entries ({mode})")
    return new


def run_daily(
    disc: DiscoveryConfig,
    cfg: CommunityConfig,
    official: OfficialContext,
    exclusions: Exclusions,
    *,
    elapsed_seconds: float = 0.0,
    budget_override: float | None = None,
    now: dt.datetime | None = None,
    catalog_path: Path | None = None,
    history_path: Path | None = None,
    log: Callable[[str], None] = print,
    downloader=download_sources,
    checker=None,
    force_refresh: bool = False,
) -> dict:
    """Refresh the catalogue when due, then check this run's rotating slice. Never raises for network problems."""
    summary: dict = {"enabled": cfg.enabled}
    if not cfg.enabled:
        return summary
    now = now or utc_now()
    catalog = load_catalog(catalog_path)
    if force_refresh or catalog_is_stale(catalog, cfg, now):
        catalog = refresh_catalog(
            disc, cfg, official, exclusions, now=now, path=catalog_path, log=log, downloader=downloader
        )
    if not catalog:
        log("community: no catalogue available; nothing to check")
        summary["catalog"] = 0
        return summary
    streams, removed = apply_tier_rules(catalog_streams(catalog), official, exclusions, cfg.allow_restream_hosts)
    summary["catalog"] = len(streams)
    history = load_history(history_path)
    chosen = select_for_check(streams, history, now, cfg)
    budget = min(
        budget_override if budget_override is not None else cfg.run_budget_seconds,
        cfg.total_deadline_minutes * 60 - elapsed_seconds,
    )
    summary.update(selected=len(chosen), budget_seconds=max(0.0, round(budget)))
    if not chosen or budget < 30:
        log(f"community: nothing checked (selected {len(chosen)}, budget {budget:.0f}s)")
        return summary
    log(f"community: checking {len(chosen)} of {len(streams)} streams within {budget:.0f}s")
    runner = checker or run_checks
    results = runner(chosen, cfg, budget)
    run_id = now.strftime("community-%Y%m%dT%H%M%SZ")
    for r in results:
        r.details["run_id"] = run_id
    live = {s.id for s in streams}
    merged = merge_results(history, results, cfg.history_per_stream, live)
    save_history(merged, cfg.history_per_stream, history_path)
    counts = Counter(r.status.value for r in results)
    summary.update(
        checked=sum(n for k, n in counts.items() if k != "NOT_TESTED"), by_status=dict(sorted(counts.items()))
    )
    for status, n in sorted(counts.items()):
        log(f"  community {status:<18} {n}")
    return summary


def run_checks(chosen: list[CStream], cfg: CommunityConfig, budget_seconds: float) -> list[CheckResult]:
    limits = limits_for(cfg, budget_seconds)
    return asyncio.run(check_all([CheckTarget.of(s) for s in chosen], limits))  # type: ignore[arg-type]


# ------------------------------------------------------------------------------------------------ playlists
@dataclass
class CommunityPlan:
    files: dict = field(default_factory=dict)  # rel path -> content
    index: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    # merge_into_main: main playlist path -> (kind, key, name, entries) of verified streams to add to it
    merge: dict = field(default_factory=dict)


def _entry(ev: Evaluated, group: str, bucket: str | None) -> m3u.Entry:
    s = ev.stream
    attrs = {
        "tvg-id": s.epg_id,
        "tvg-name": s.name,
        "tvg-country": s.cc.upper(),
        "tvg-language": ";".join(LANGUAGES[x] for x in s.lg),
        "tvg-logo": s.lo,
        "group-title": group,
        "x-tier": "community",
        "x-status": ev.state,
    }
    if bucket:
        attrs["x-quality"] = bucket
    return m3u.Entry(title=s.name, url=s.url, attrs=attrs)


def _bucket(ev: Evaluated) -> str | None:
    return quality_bucket(ev.height) or quality_bucket(ev.stream.q)


def _order(ev: Evaluated) -> tuple:
    return (ev.state != "verified", ev.stream.cc, ev.stream.name.casefold(), ev.stream.id)


def plan_community(
    catalog: dict | None,
    history: dict[str, list[list]],
    official: OfficialContext,
    exclusions: Exclusions,
    cfg: CommunityConfig,
) -> CommunityPlan:
    """Playlists, index entries and statistics of the community tier, a pure function of its inputs."""
    plan = CommunityPlan()
    if not cfg.enabled or not catalog or not catalog.get("streams"):
        return plan
    cn = countries()
    streams, removed = apply_tier_rules(catalog_streams(catalog), official, exclusions, cfg.allow_restream_hosts)
    ref = reference_time(history)
    evaluated = evaluate_streams(streams, history, cfg, ref)
    published = [e for e in evaluated if e.state in ("verified", "untested")]
    published.sort(key=_order)
    verified = [e for e in published if e.state == "verified"]
    untested = [e for e in published if e.state == "untested"]

    def add(rel: str, kind: str, key: str, name: str, evs: list[Evaluated], group_fn, label: str) -> None:
        if not evs:
            return
        entries = [_entry(e, group_fn(e), _bucket(e)) for e in evs]
        plan.files[rel] = m3u.render(entries, {"x-nexonic-playlist": name, "x-nexonic-tier": label})
        plan.index.append(
            {
                "path": rel,
                "kind": kind,
                "key": key,
                "name": name,
                "count": len(evs),
                "url": playlist_url(rel),
                "tier": "community",
                "verified": sum(1 for e in evs if e.state == "verified"),
                "untested": sum(1 for e in evs if e.state == "untested"),
            }
        )

    def country_name(e: Evaluated) -> str:
        return cn[e.stream.cc]["name"]

    if not cfg.merge_into_main:
        add(
            "playlists/community/verified.m3u",
            "community-verified",
            "verified",
            f"Community verified (worked at the latest check, within {cfg.verified_days} days)",
            verified,
            country_name,
            "community",
        )
    add(
        "playlists/community/untested.m3u",
        "community-untested",
        "untested",
        "Community UNTESTED (never checked, not recently checked or inconclusive; not confirmed working)",
        untested,
        lambda e: f"Untested | {country_name(e)}",
        "community",
    )

    if cfg.merge_into_main:
        _plan_merge(plan, verified, cn)
        _finish_stats(plan, catalog, streams, removed, ref, evaluated, published, cfg, cn)
        return plan

    pool = published if cfg.untested_in_dimension_playlists else verified

    def tagged(group: str, e: Evaluated) -> str:
        return f"{group} | {'Verified' if e.state == 'verified' else 'Untested'}"

    for code in sorted({e.stream.cc for e in pool}):
        add(
            f"playlists/community/countries/{code}.m3u",
            "community-country",
            code,
            f"Community: {cn[code]['name']}",
            [e for e in pool if e.stream.cc == code],
            lambda e: tagged(CATEGORIES[e.stream.ct[0]], e),
            "community",
        )
    for lang in sorted({lg for e in pool for lg in e.stream.lg}):
        add(
            f"playlists/community/languages/{lang}.m3u",
            "community-language",
            lang,
            f"Community: {LANGUAGES[lang]}",
            [e for e in pool if lang in e.stream.lg],
            lambda e: tagged(country_name(e), e),
            "community",
        )
    for cat in sorted({c for e in pool for c in e.stream.ct}):
        add(
            f"playlists/community/categories/{cat}.m3u",
            "community-category",
            cat,
            f"Community: {CATEGORIES[cat]}",
            [e for e in pool if cat in e.stream.ct],
            lambda e: tagged(country_name(e), e),
            "community",
        )
    for b in QUALITY_BUCKETS:
        add(
            f"playlists/community/quality/{b}.m3u",
            "community-quality",
            b,
            f"Community: {BUCKET_LABELS[b]}",
            [e for e in pool if _bucket(e) == b],
            lambda e: tagged(country_name(e), e),
            "community",
        )

    _finish_stats(plan, catalog, streams, removed, ref, evaluated, published, cfg, cn)
    return plan


def _finish_stats(plan, catalog, streams, removed, ref, evaluated, published, cfg, cn) -> None:
    states = Counter(e.state for e in evaluated)
    life = Counter(e.lifecycle.state.value for e in evaluated)
    never = sum(1 for e in evaluated if e.last_checked is None)
    plan.stats = {
        "catalog_built_at": catalog.get("built_at"),
        "catalog_streams": len(catalog["streams"]),
        "after_generation_rules": len(streams),
        "removed_at_generation": removed,
        "reference_time": iso(ref) if ref else None,
        "verified": states["verified"],
        "untested": states["untested"],
        "failing_held_back": states["failing"],
        "never_checked": never,
        "lifecycle": dict(sorted(life.items())),
        "verified_days": cfg.verified_days,
        "playlist_files": len(plan.files),
        "countries": len({e.stream.cc for e in published}),
        "languages": len({lg for e in published for lg in e.stream.lg}),
        "top_countries": [
            {"code": c, "name": cn[c]["name"], "streams": n}
            for c, n in Counter(e.stream.cc for e in published).most_common(10)
        ],
        "build_report": catalog.get("report"),
    }
    plan.stats["merged_into_main"] = bool(cfg.merge_into_main)


def _plan_merge(plan: CommunityPlan, verified: list[Evaluated], cn: dict) -> None:
    """Verified streams for the main playlists, grouped the same way as the official ones."""

    def country_name(e: Evaluated) -> str:
        return cn[e.stream.cc]["name"]

    def put(rel: str, kind: str, key: str, name: str, evs: list[Evaluated], group_fn) -> None:
        if evs:
            plan.merge[rel] = (kind, key, name, [_entry(e, group_fn(e), _bucket(e)) for e in evs])

    put("playlists/all.m3u", "global", "all", "All channels", verified, country_name)
    put("playlists/verified.m3u", "verified", "verified", "Nexonic Verified", verified, country_name)
    for code in sorted({e.stream.cc for e in verified}):
        put(
            f"playlists/countries/{code}.m3u",
            "country",
            code,
            cn[code]["name"],
            [e for e in verified if e.stream.cc == code],
            lambda e: CATEGORIES[e.stream.ct[0]],
        )
    for lang in sorted({lg for e in verified for lg in e.stream.lg}):
        put(
            f"playlists/languages/{lang}.m3u",
            "language",
            lang,
            LANGUAGES[lang],
            [e for e in verified if lang in e.stream.lg],
            country_name,
        )
    for cat in sorted({c for e in verified for c in e.stream.ct}):
        put(
            f"playlists/categories/{cat}.m3u",
            "category",
            cat,
            CATEGORIES[cat],
            [e for e in verified if cat in e.stream.ct],
            country_name,
        )
    for b in QUALITY_BUCKETS:
        put(
            f"playlists/quality/{b}.m3u",
            "quality",
            b,
            f"Measured {BUCKET_LABELS[b]}",
            [e for e in verified if _bucket(e) == b],
            country_name,
        )
