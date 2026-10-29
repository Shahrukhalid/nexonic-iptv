"""Project-wide public URLs and pipeline settings.

URLs can be overridden with environment variables when forking. Pipeline settings live in
``config/pipeline.toml`` (see docs/AUTOMATION.md); a missing file or key falls back to the defaults below, which
match the values the scripts used before the file existed.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

REPO = os.environ.get("NEXONIC_REPO", "Shahrukhalid/nexonic-iptv")
SITE_URL = os.environ.get("NEXONIC_SITE_URL", "https://shahrukhalid.github.io/nexonic-iptv").rstrip("/")
RAW_BASE = os.environ.get("NEXONIC_RAW_BASE", f"https://raw.githubusercontent.com/{REPO}/main").rstrip("/")
REPO_URL = f"https://github.com/{REPO}"

ROOT = Path(__file__).resolve().parent.parent
PIPELINE_FILE = ROOT / "config" / "pipeline.toml"


def playlist_url(rel_path: str) -> str:
    """Public URL of a generated playlist (served by GitHub Pages with the site)."""
    return f"{SITE_URL}/{rel_path.lstrip('/')}"


@dataclass
class VerifyConfig:
    timeout: float = 10.0
    concurrency: int = 12
    max_concurrency: int = 16
    retries: int = 1
    backoff_base: float = 1.0
    per_host_interval: float = 1.0
    channel_timeout: float = 60.0
    budget_minutes: float = 40.0


@dataclass
class QuarantineConfig:
    consecutive_failures: int = 3
    distinct_days: int = 2
    intermittent_window_days: int = 7


@dataclass
class GuardConfig:
    max_drop_percent: float = 10.0
    max_added: int = 300
    max_verified_drop_percent: float = 50.0
    min_baseline: int = 50
    override: bool = False


@dataclass
class ChangesConfig:
    history_days: int = 30
    max_listed: int = 200


def _default_sources() -> list[dict]:
    return [
        {"name": "iptv", "repo": "iptv-org/iptv", "ref": "master"},
        {"name": "database", "repo": "iptv-org/database", "ref": "master"},
    ]


def _default_extra_m3u() -> list[dict]:
    """Public lists shipped by default; config/pipeline.toml shows the same values."""
    return [
        {
            "name": "m3upt",
            "repo": "LITUATUI/M3UPT",
            "ref": "main",
            "paths": ["M3U/M3UPT.m3u"],
            "licence": "MIT",
        },
        {
            "name": "iprtl",
            "repo": "iprtl/m3u",
            "ref": "live",
            "paths": ["Freetv.m3u"],
            "licence": "Unlicense",
        },
        {
            "name": "iptv-com",
            "repo": "iptv-com/iptv",
            "ref": "main",
            "paths": ["lists/world.m3u", "lists/brazil.m3u"],
            "licence": "Unlicense",
        },
        {
            "name": "openiptvitaly",
            "repo": "xN1ckuz/OpenIPTVItaly",
            "ref": "main",
            "paths": ["OpenIPTVItaly.m3u"],
            "licence": "MIT",
        },
        {
            "name": "iptv-m3u-tr",
            "repo": "omerdenizhan/IPTV-M3U",
            "ref": "main",
            "paths": ["m3u/turkiye-iptv-org.m3u"],
            "licence": "Unlicense",
        },
        {
            "name": "iptv-spain",
            "repo": "Ignac16/Iptv-spain-m3u-1416",
            "ref": "main",
            "paths": ["playlist_spain.m3u8"],
            "licence": "CC0-1.0",
        },
        {
            "name": "ipmx",
            "repo": "Osares10/ipmx",
            "ref": "main",
            "paths": ["Mexico.m3u"],
            "licence": "Unlicense",
        },
        {
            "name": "iptv-ecuador",
            "repo": "CL-Maker283/iptv-ecuador-tv",
            "ref": "main",
            "paths": ["streamings-ecuador-all.m3u"],
            "licence": "Unlicense",
        },
    ]


@dataclass
class DiscoveryConfig:
    timeout: float = 30.0
    retries: int = 4
    backoff_base: float = 2.0
    max_archive_mb: int = 300
    allowed_hosts: list[str] = field(
        default_factory=lambda: ["github.com", "codeload.github.com", "raw.githubusercontent.com"]
    )
    sources: list[dict] = field(default_factory=_default_sources)
    max_playlist_mb: int = 50
    extra_m3u: list[dict] = field(default_factory=_default_extra_m3u)


@dataclass
class CommunityConfig:
    """Community live tier (nexonic/community.py): catalogue refresh, rotating checks and playlist rules."""

    enabled: bool = True
    refresh_max_age_hours: float = 20.0  # the catalogue is rebuilt by the daily run when older than this
    min_catalog_ratio: float = 0.5  # a rebuilt catalogue smaller than this share of the last good one is rejected
    streams_per_channel: int = 1  # best-ranked streams kept per channel feed (1 = one stream per channel identity)
    allow_restream_hosts: bool = True  # known restream hosts may be listed and checked in this tier (never tokens)
    # Rotating, budgeted validation
    max_checks_per_run: int = 3000
    run_budget_seconds: float = 1200.0  # no new community check is started after this
    total_deadline_minutes: float = 44.0  # ... nor after this many minutes since scripts/verify.py started
    concurrency: int = 32
    max_concurrency: int = 64
    timeout: float = 8.0
    retries: int = 0
    backoff_base: float = 1.0
    per_host_interval: float = 1.0  # minimum seconds between requests to the same host
    max_per_host_per_run: int = 40  # one CDN carrying hundreds of channels cannot use the whole budget
    channel_timeout: float = 30.0
    retry_failed_days: int = 3  # a stream whose last check failed is not re-checked before this
    retry_quarantined_days: int = 14
    history_per_stream: int = 8
    # Lifecycle (nexonic/lifecycle.py) with thresholds suited to one check every few days
    min_recheck_hours: float = 20.0  # a stream checked more recently than this is not due again
    quarantine_failures: int = 2
    quarantine_distinct_days: int = 2
    intermittent_window_days: int = 14
    # Playlists
    verified_days: int = 7  # verified.m3u: the stream worked at its latest check within this many days
    untested_in_dimension_playlists: bool = True  # country/language/category/quality files also list untested streams
    merge_into_main: bool = True  # verified community streams join the main playlists (all, verified, countries, ...)


def _default_vod_collections() -> list[dict]:
    return [
        {"id": "feature_films", "kind": "movie"},
        {"id": "film_noir", "kind": "movie", "genre": "noir"},
        {"id": "SciFi_Horror", "kind": "movie", "genre": "scifi-horror"},
        {"id": "comedy_films", "kind": "movie", "genre": "comedy"},
        {"id": "classic_cartoons", "kind": "movie", "genre": "animation"},
        {"id": "classic_tv", "kind": "series"},
    ]


@dataclass
class VodConfig:
    """Free VOD tier (nexonic/vod.py): Internet Archive public-domain and openly licensed films and TV."""

    enabled: bool = True
    refresh_max_age_hours: float = 20.0
    timeout: float = 30.0
    retries: int = 3
    backoff_base: float = 2.0
    request_interval: float = 1.0  # seconds between requests to archive.org
    rows_per_page: int = 200
    search_pages_per_run: int = 4  # advancedsearch pages read per run, across all collections
    metadata_per_run: int = 150  # item metadata documents read per run (the daily slice)
    run_budget_seconds: float = 300.0
    max_items: int = 5000  # items kept in state/vod/items.json
    rescan_days: int = 14  # a finished collection search starts over after this many days
    allow_weak_terms: bool = False  # titles with words such as "love" or "night" go to manual review unless true
    total_deadline_minutes: float = 48.0  # no VOD request is made after this many minutes since verify.py started
    allowed_licences: list = field(
        default_factory=lambda: ["publicdomain", "by", "by-sa", "by-nc", "by-nc-sa", "by-nd", "by-nc-nd"]
    )
    allowed_hosts: list = field(default_factory=lambda: ["archive.org"])
    collections: list = field(default_factory=_default_vod_collections)


@dataclass
class PipelineConfig:
    verify: VerifyConfig = field(default_factory=VerifyConfig)
    quarantine: QuarantineConfig = field(default_factory=QuarantineConfig)
    guard: GuardConfig = field(default_factory=GuardConfig)
    changes: ChangesConfig = field(default_factory=ChangesConfig)
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    community: CommunityConfig = field(default_factory=CommunityConfig)
    vod: VodConfig = field(default_factory=VodConfig)


class ConfigError(ValueError):
    pass


def _fill(cls, raw: dict, where: str):
    known = {f.name: f for f in fields(cls)}
    unknown = sorted(set(raw) - set(known))
    if unknown:
        raise ConfigError(f"unknown key(s) in [{where}]: {', '.join(unknown)}")
    obj = cls()
    for key, value in raw.items():
        current = getattr(obj, key)
        if isinstance(current, bool):
            ok = isinstance(value, bool)
        elif isinstance(current, int):
            ok = isinstance(value, int) and not isinstance(value, bool)
        elif isinstance(current, float):
            ok = isinstance(value, int | float) and not isinstance(value, bool)
            value = float(value) if ok else value
        else:
            ok = isinstance(value, list)
        if not ok:
            raise ConfigError(f"[{where}] {key} has the wrong type ({type(value).__name__})")
        setattr(obj, key, value)
    return obj


EXTRA_M3U_KEYS = {"name", "repo", "ref", "paths", "licence"}
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_REF_RE = re.compile(r"^[A-Za-z0-9_./-]+$")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _check_extra_m3u(entries: list[dict]) -> None:
    """Every ``[[discovery.extra_m3u]]`` entry names a public GitHub repo, a branch/tag and plain M3U file paths."""
    seen: set[str] = set()
    for e in entries:
        if not isinstance(e, dict) or set(e) != EXTRA_M3U_KEYS:
            raise ConfigError("[[discovery.extra_m3u]] entries need exactly name, repo, ref, paths and licence")
        name = e["name"]
        if not isinstance(name, str) or not _NAME_RE.match(name) or name in seen:
            raise ConfigError(f"[[discovery.extra_m3u]] name {name!r} must be a unique lower-case slug")
        seen.add(name)
        if not isinstance(e["repo"], str) or not _REPO_RE.match(e["repo"]):
            raise ConfigError(f"[[discovery.extra_m3u]] {name}: repo must look like owner/name")
        if not isinstance(e["ref"], str) or not _REF_RE.match(e["ref"]) or ".." in e["ref"]:
            raise ConfigError(f"[[discovery.extra_m3u]] {name}: invalid ref")
        if not isinstance(e["licence"], str) or not e["licence"].strip():
            raise ConfigError(f"[[discovery.extra_m3u]] {name}: the repository licence must be recorded")
        paths = e["paths"]
        if not isinstance(paths, list) or not paths or not all(isinstance(x, str) for x in paths):
            raise ConfigError(f"[[discovery.extra_m3u]] {name}: paths must be a non-empty list of strings")
        for rel in paths:
            parts = rel.split("/")
            if (
                rel.startswith("/")
                or any(x in ("", ".", "..") for x in parts)
                or "\\" in rel
                or "?" in rel
                or "#" in rel
                or not rel.lower().endswith((".m3u", ".m3u8"))
            ):
                raise ConfigError(f"[[discovery.extra_m3u]] {name}: unsafe or non-M3U path {rel!r}")


VOD_COLLECTION_KEYS = {"id", "kind", "genre"}
VOD_LICENCES = {"publicdomain", "by", "by-sa", "by-nc", "by-nc-sa", "by-nd", "by-nc-nd"}
_COLLECTION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")


def _check_vod(v: VodConfig) -> None:
    seen: set[str] = set()
    for c in v.collections:
        if not isinstance(c, dict) or not {"id", "kind"} <= set(c) or not set(c) <= VOD_COLLECTION_KEYS:
            raise ConfigError("[[vod.collections]] entries need id and kind (and optionally genre)")
        cid = c["id"]
        if not isinstance(cid, str) or not _COLLECTION_ID_RE.match(cid) or cid in seen:
            raise ConfigError(f"[[vod.collections]] id {cid!r} must be a unique Internet Archive collection id")
        seen.add(cid)
        if c["kind"] not in ("movie", "series"):
            raise ConfigError(f"[[vod.collections]] {cid}: kind must be 'movie' or 'series'")
        genre = c.get("genre", "")
        if not isinstance(genre, str) or (genre and not _NAME_RE.match(genre)):
            raise ConfigError(f"[[vod.collections]] {cid}: genre must be a lower-case slug or empty")
    if not v.allowed_licences or not set(v.allowed_licences) <= VOD_LICENCES:
        raise ConfigError(f"vod.allowed_licences must be a non-empty subset of {sorted(VOD_LICENCES)}")
    if not v.allowed_hosts or not all(isinstance(h, str) and "." in h for h in v.allowed_hosts):
        raise ConfigError("vod.allowed_hosts must list host names")


def _check(cfg: PipelineConfig) -> None:
    v, q, g, d = cfg.verify, cfg.quarantine, cfg.guard, cfg.discovery
    positive = {
        "verify.timeout": v.timeout,
        "verify.concurrency": v.concurrency,
        "verify.max_concurrency": v.max_concurrency,
        "verify.channel_timeout": v.channel_timeout,
        "verify.budget_minutes": v.budget_minutes,
        "quarantine.consecutive_failures": q.consecutive_failures,
        "quarantine.distinct_days": q.distinct_days,
        "quarantine.intermittent_window_days": q.intermittent_window_days,
        "guard.max_added": g.max_added,
        "changes.history_days": cfg.changes.history_days,
        "discovery.timeout": d.timeout,
        "discovery.max_archive_mb": d.max_archive_mb,
        "discovery.max_playlist_mb": d.max_playlist_mb,
    }
    for name, value in positive.items():
        if value <= 0:
            raise ConfigError(f"{name} must be greater than 0")
    for name, value in {
        "verify.retries": v.retries,
        "verify.backoff_base": v.backoff_base,
        "verify.per_host_interval": v.per_host_interval,
        "discovery.retries": d.retries,
        "discovery.backoff_base": d.backoff_base,
        "guard.min_baseline": g.min_baseline,
    }.items():
        if value < 0:
            raise ConfigError(f"{name} must not be negative")
    for name, value in {
        "guard.max_drop_percent": g.max_drop_percent,
        "guard.max_verified_drop_percent": g.max_verified_drop_percent,
    }.items():
        if not 0 <= value <= 100:
            raise ConfigError(f"{name} must be between 0 and 100")
    if not d.sources or any(set(s) != {"name", "repo", "ref"} for s in d.sources):
        raise ConfigError("[[discovery.sources]] entries need exactly name, repo and ref")
    _check_extra_m3u(d.extra_m3u)
    c, vod = cfg.community, cfg.vod
    for name, value in {
        "community.refresh_max_age_hours": c.refresh_max_age_hours,
        "community.streams_per_channel": c.streams_per_channel,
        "community.max_checks_per_run": c.max_checks_per_run,
        "community.run_budget_seconds": c.run_budget_seconds,
        "community.total_deadline_minutes": c.total_deadline_minutes,
        "community.concurrency": c.concurrency,
        "community.max_concurrency": c.max_concurrency,
        "community.timeout": c.timeout,
        "community.min_recheck_hours": c.min_recheck_hours,
        "community.max_per_host_per_run": c.max_per_host_per_run,
        "community.channel_timeout": c.channel_timeout,
        "community.history_per_stream": c.history_per_stream,
        "community.quarantine_failures": c.quarantine_failures,
        "community.quarantine_distinct_days": c.quarantine_distinct_days,
        "community.intermittent_window_days": c.intermittent_window_days,
        "community.verified_days": c.verified_days,
        "vod.refresh_max_age_hours": vod.refresh_max_age_hours,
        "vod.timeout": vod.timeout,
        "vod.rows_per_page": vod.rows_per_page,
        "vod.search_pages_per_run": vod.search_pages_per_run,
        "vod.metadata_per_run": vod.metadata_per_run,
        "vod.run_budget_seconds": vod.run_budget_seconds,
        "vod.max_items": vod.max_items,
        "vod.rescan_days": vod.rescan_days,
        "vod.total_deadline_minutes": vod.total_deadline_minutes,
    }.items():
        if value <= 0:
            raise ConfigError(f"{name} must be greater than 0")
    for name, value in {
        "community.retries": c.retries,
        "community.backoff_base": c.backoff_base,
        "community.per_host_interval": c.per_host_interval,
        "community.retry_failed_days": c.retry_failed_days,
        "community.retry_quarantined_days": c.retry_quarantined_days,
        "vod.retries": vod.retries,
        "vod.backoff_base": vod.backoff_base,
        "vod.request_interval": vod.request_interval,
    }.items():
        if value < 0:
            raise ConfigError(f"{name} must not be negative")
    if not 0 < c.min_catalog_ratio <= 1:
        raise ConfigError("community.min_catalog_ratio must be between 0 (exclusive) and 1")
    if c.streams_per_channel > 5:
        raise ConfigError("community.streams_per_channel must be at most 5")
    _check_vod(vod)


def load_pipeline(path: Path | None = None) -> PipelineConfig:
    """Read the pipeline settings; a missing file yields the defaults."""
    path = path or Path(os.environ.get("NEXONIC_PIPELINE_CONFIG") or PIPELINE_FILE)
    if not path.exists():
        return PipelineConfig()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    unknown = sorted(set(raw) - {f.name for f in fields(PipelineConfig)})
    if unknown:
        raise ConfigError(f"unknown section(s): {', '.join(unknown)}")
    cfg = PipelineConfig()
    for f in fields(PipelineConfig):
        if f.name in raw:
            section = dict(raw[f.name])
            setattr(cfg, f.name, _fill(type(getattr(cfg, f.name)), section, f.name))
    _check(cfg)
    return cfg


def guard_override(cfg: GuardConfig) -> bool:
    return cfg.override or os.environ.get("NEXONIC_GUARD_OVERRIDE", "").strip().lower() in {"1", "true", "yes"}
