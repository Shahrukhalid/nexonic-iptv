"""Project-wide public URLs and pipeline settings.

URLs can be overridden with environment variables when forking. Pipeline settings live in
``config/pipeline.toml`` (see docs/AUTOMATION.md); a missing file or key falls back to the defaults below, which
match the values the scripts used before the file existed.
"""

from __future__ import annotations

import os
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
