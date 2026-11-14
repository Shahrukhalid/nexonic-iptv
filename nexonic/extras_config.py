"""Settings of the free radio, open media and TV guide tiers (``config/extras.toml``) and their takedown list.

A missing file or key falls back to the defaults below. Takedowns live in ``data/extra-exclusions.yaml`` with the keys
``radio`` (station ids) and ``media`` (Commons file names such as ``File:Example.webm``).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml

from .config import ConfigError

ROOT = Path(__file__).resolve().parent.parent
EXTRAS_FILE = ROOT / "config" / "extras.toml"
EXCLUSIONS_FILE = ROOT / "data" / "extra-exclusions.yaml"

DEFAULT_MEDIA_SEARCHES = (
    {"q": "public domain feature film", "genre": "films"},
    {"q": "silent film", "genre": "silent"},
    {"q": "documentary", "genre": "documentary"},
    {"q": "animated short film", "genre": "animation"},
    {"q": "open movie", "genre": "animation"},
    {"q": "NASA", "genre": "science"},
    {"q": "newsreel", "genre": "history"},
)


@dataclass
class RadioConfig:
    """Free radio tier (nexonic/radio.py): stations from an open, public-domain station directory."""

    enabled: bool = True
    refresh_max_age_hours: float = 20.0
    timeout: float = 30.0
    retries: int = 3
    backoff_base: float = 2.0
    api_hosts: list = field(
        default_factory=lambda: [
            "de1.api.radio-browser.info",
            "fi1.api.radio-browser.info",
            "nl1.api.radio-browser.info",
        ]
    )
    max_stations: int = 30000  # most-listened working stations kept
    per_country: int = 1500  # cap per country file
    min_bitrate: int = 0  # 0 = any
    https_only: bool = False  # many stations only stream over http; players accept both


@dataclass
class MediaConfig:
    """Open media VOD tier (nexonic/openmedia.py): free-licensed videos from Wikimedia Commons."""

    enabled: bool = True
    refresh_max_age_hours: float = 20.0
    timeout: float = 30.0
    retries: int = 3
    backoff_base: float = 2.0
    request_interval: float = 1.0
    run_budget_seconds: float = 300.0
    pages_per_run: int = 20  # API pages (50 files each) read per daily run, across all searches
    min_seconds: int = 120  # shorter clips are left out
    max_items: int = 20000
    rescan_days: int = 14
    allowed_licences: list = field(default_factory=lambda: ["pd", "cc0", "cc-by", "cc-by-sa"])
    allowed_hosts: list = field(default_factory=lambda: ["commons.wikimedia.org", "upload.wikimedia.org"])
    searches: list = field(default_factory=lambda: [dict(s) for s in DEFAULT_MEDIA_SEARCHES])


@dataclass
class GuideConfig:
    """TV guide (nexonic/guide.py): XMLTV feeds merged and trimmed to the published channels."""

    enabled: bool = True
    timeout: float = 60.0
    retries: int = 3
    backoff_base: float = 2.0
    hours_ahead: int = 48
    hours_behind: int = 6
    max_feed_mb: int = 200
    allowed_hosts: list = field(default_factory=list)
    feeds: list = field(default_factory=list)  # https XMLTV (.xml or .xml.gz) whose publisher allows reuse


@dataclass
class ExtrasConfig:
    radio: RadioConfig = field(default_factory=RadioConfig)
    media: MediaConfig = field(default_factory=MediaConfig)
    guide: GuideConfig = field(default_factory=GuideConfig)


def load_extras(path: Path | None = None) -> ExtrasConfig:
    path = path or Path(os.environ.get("NEXONIC_EXTRAS_CONFIG") or EXTRAS_FILE)
    cfg = ExtrasConfig()
    if not path.exists():
        return cfg
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    for section, value in raw.items():
        if section not in {f.name for f in fields(ExtrasConfig)}:
            raise ConfigError(f"unknown section [{section}] in {path.name}")
        cls = type(getattr(cfg, section))
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(value) - known)
        if unknown:
            raise ConfigError(f"unknown key(s) in [{section}]: {', '.join(unknown)}")
        setattr(cfg, section, cls(**value))
    for s in cfg.media.searches:
        if not isinstance(s, dict) or not isinstance(s.get("q"), str) or not s["q"].strip():
            raise ConfigError("[[media.searches]] entries need a non-empty q (and optionally genre)")
    if any(not str(f).startswith("https://") for f in cfg.guide.feeds):
        raise ConfigError("[guide] feeds must be https addresses")
    return cfg


def load_exclusions(path: Path | None = None) -> dict[str, frozenset[str]]:
    """{"radio": ids, "media": file names}, lower case. A missing file means nothing is excluded."""
    path = path or EXCLUSIONS_FILE
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    raw = raw or {}
    if not isinstance(raw, dict) or set(raw) - {"radio", "media"}:
        raise ValueError(f"{path.name}: only the keys radio and media are allowed")
    out = {}
    for key in ("radio", "media"):
        values = raw.get(key) or []
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise ValueError(f"{path.name}: {key} must be a list of strings")
        out[key] = frozenset(v.lower() for v in values)
    return out
