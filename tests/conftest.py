"""Shared fixtures. All network access in unit tests is mocked; nothing here touches the internet."""

from __future__ import annotations

import copy
import importlib
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASE = {
    "id": "example-news",
    "name": "Example News",
    "alt_names": [],
    "broadcaster": "Example Public Broadcaster",
    "country": "de",
    "languages": ["de"],
    "categories": ["news"],
    "website": "https://www.example-broadcaster.de",
    "stream": {"url": "https://live.example-broadcaster.de/hls/news/master.m3u8", "protocol": "hls"},
    "source": {
        "reference_url": "https://www.example-broadcaster.de/live",
        "evidence_url": "https://www.example-broadcaster.de/live",
        "evidence_summary": "Broadcaster's own free live page (test fixture).",
    },
    "epg_id": "ExampleNews.de",
    "geo": {"restricted": False, "regions": []},
    "first_discovered": "2026-10-17",
    "review": {
        "status": "approved",
        "reviewer": "test-suite",
        "reviewed_at": "2026-10-17",
        "authorization_basis": "official-broadcaster-stream",
        "adult_screening": "pass",
    },
}


def make(**overrides) -> dict:
    rec = copy.deepcopy(BASE)
    for key, value in overrides.items():
        if "." in key:
            outer, inner = key.split(".", 1)
            rec[outer][inner] = value
        else:
            rec[key] = value
    return rec


@pytest.fixture
def record():
    return make


def write_dataset(root: Path, approved: list[dict], pending: list[dict] = (), rejected: list[dict] = ()) -> Path:
    data = root / "data"
    for folder in ("approved", "pending", "rejected"):
        (data / folder).mkdir(parents=True, exist_ok=True)
    by_cc: dict[str, list[dict]] = {}
    for r in approved:
        by_cc.setdefault(r["country"], []).append(r)
    for cc, items in by_cc.items():
        (data / "approved" / f"{cc}.yaml").write_text(yaml.safe_dump({"channels": items}), encoding="utf-8")
    if pending:
        (data / "pending" / "q.yaml").write_text(yaml.safe_dump({"channels": list(pending)}), encoding="utf-8")
    if rejected:
        (data / "rejected" / "r.yaml").write_text(yaml.safe_dump({"channels": list(rejected)}), encoding="utf-8")
    return data


@pytest.fixture
def dataset(tmp_path):
    def _make(approved, pending=(), rejected=()):
        return write_dataset(tmp_path, approved, pending, rejected)

    return _make


def load_script(name: str):
    """Import scripts/<name>.py (scripts/_bootstrap.py drops the scripts directory from sys.path after import)."""
    scripts = str(ROOT / "scripts")
    sys.path.insert(0, scripts)
    try:
        return importlib.import_module(name)
    finally:
        if scripts in sys.path:
            sys.path.remove(scripts)
