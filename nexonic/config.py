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
class PipelineConfig:
    verify: VerifyConfig = field(default_factory=VerifyConfig)
    quarantine: QuarantineConfig = field(default_factory=QuarantineConfig)
    guard: GuardConfig = field(default_factory=GuardConfig)
    changes: ChangesConfig = field(default_factory=ChangesConfig)
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)


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
