"""Verification from additional vantage points ("regional" checks).

The primary pipeline runs on GitHub-hosted runners in the United States, so streams limited to other regions show up
as ``GEO_RESTRICTED``. A second location (a self-hosted runner or the owner's own computer) can re-check just those
channels. Its results live in ``state/regional/<label>.json`` and have the same shape as ``state/history.json``; they
never enter the primary history, so they cannot change a channel's global lifecycle, quarantine state or health
score. ``scripts/generate.py`` reads them to add ``works_in`` to restricted channels and to write
``playlists/regions/<label>.m3u``.

Selection (``--only``) accepts statuses (upper case, e.g. ``GEO_RESTRICTED``, ``UNKNOWN``, ``TIMEOUT``) and lifecycle
states (lower case, e.g. ``restricted``, ``unreachable``). A channel is selected when its latest primary result has
one of the statuses or its primary lifecycle is one of the states. ``all`` selects every approved channel.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from . import health, lifecycle
from .config import QuarantineConfig
from .models import Channel
from .records import ROOT
from .status import CheckResult, Status

REGIONAL_DIR = ROOT / "state" / "regional"
REGIONAL_HISTORY_LIMIT = 30  # results kept per channel and location
LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,31}$")
LIFECYCLE_STATES = {s.value for s in lifecycle.Lifecycle}
STATUS_NAMES = {s.value for s in Status}


class RegionalError(ValueError):
    pass


def check_label(label: str) -> str:
    if not LABEL_RE.match(label or ""):
        raise RegionalError(
            f"invalid location label {label!r}: use 2-32 characters of a-z, 0-9 and '-', starting with a letter or digit"
        )
    return label


def parse_selectors(values: list[str]) -> tuple[set[str], set[str], bool]:
    """Split ``--only`` values (space and/or comma separated) into (statuses, lifecycle states, all)."""
    statuses: set[str] = set()
    states: set[str] = set()
    everything = False
    tokens = [t.strip() for v in values for t in v.split(",") if t.strip()]
    if not tokens:
        raise RegionalError("--only needs at least one status or lifecycle state")
    for tok in tokens:
        if tok.lower() == "all":
            everything = True
        elif tok in STATUS_NAMES:
            statuses.add(tok)
        elif tok in LIFECYCLE_STATES:
            states.add(tok)
        elif tok.upper() in STATUS_NAMES and tok.lower() not in LIFECYCLE_STATES:
            statuses.add(tok.upper())
        else:
            raise RegionalError(
                f"unknown selector {tok!r}; use a status ({', '.join(sorted(STATUS_NAMES))}), "
                f"a lifecycle state ({', '.join(sorted(LIFECYCLE_STATES))}) or all"
            )
    return statuses, states, everything


def select_channels(
    channels: list[Channel],
    history: dict[str, list[CheckResult]],
    selectors: list[str],
    quarantine: QuarantineConfig,
) -> list[Channel]:
    """Approved channels whose primary result matches ``selectors`` (see the module docstring)."""
    statuses, states, everything = parse_selectors(selectors)
    if everything:
        return list(channels)
    ref = _reference(history, channels)
    out = []
    for ch in channels:
        results = history.get(ch.id, [])
        tested = sorted((r for r in results if r.status is not Status.NOT_TESTED), key=lambda r: r.checked_at)
        if not tested:
            continue
        if tested[-1].status.value in statuses:
            out.append(ch)
        elif states and lifecycle.evaluate(results, ref, quarantine).state.value in states:
            out.append(ch)
    return out


def _reference(history: dict[str, list[CheckResult]], channels: list[Channel]) -> dt.datetime | None:
    from .generate import reference_time

    return reference_time(history, {c.id for c in channels})


def path_for(label: str, directory: Path | None = None) -> Path:
    return (directory or REGIONAL_DIR) / f"{check_label(label)}.json"


def load_location(path: Path) -> dict[str, list[CheckResult]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {cid: [CheckResult.from_dict(r) for r in items] for cid, items in raw.get("channels", {}).items()}
    except OSError:
        return {}
    except (ValueError, TypeError, KeyError) as exc:
        raise RegionalError(f"{path.name}: unreadable regional results ({exc})") from exc


def load_all(directory: Path | None = None) -> dict[str, dict[str, list[CheckResult]]]:
    """label -> channel id -> results, for every valid ``<label>.json`` in the directory."""
    out: dict[str, dict[str, list[CheckResult]]] = {}
    directory = directory or REGIONAL_DIR
    if not directory.exists():
        return out
    for path in sorted(directory.glob("*.json")):
        if not LABEL_RE.match(path.stem):
            raise RegionalError(f"{path.name}: file name is not a valid location label")
        data = load_location(path)
        if data:
            out[path.stem] = data
    return out


def merge(
    existing: dict[str, list[CheckResult]], results: list[CheckResult], known_ids: set[str]
) -> dict[str, list[CheckResult]]:
    merged = {k: list(v) for k, v in existing.items()}
    for r in results:
        merged.setdefault(r.channel_id, []).append(r)
    return {k: v for k, v in merged.items() if k in known_ids}


def save_location(label: str, history: dict[str, list[CheckResult]], directory: Path | None = None) -> Path:
    path = path_for(label, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema": 1,
        "label": label,
        "note": "Results from an additional checking location, written by scripts/verify.py --location-label. "
        "They describe reachability from that location only. Do not edit by hand.",
        "channels": {
            cid: [r.to_dict() for r in sorted(items, key=lambda r: r.checked_at)[-REGIONAL_HISTORY_LIMIT:]]
            for cid, items in sorted(history.items())
        },
    }
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return path


def working_from(
    regional: dict[str, dict[str, list[CheckResult]]], reference: dt.datetime | None
) -> dict[str, set[str]]:
    """label -> ids whose latest result from that location is VERIFIED_WORKING inside the freshness window."""
    out: dict[str, set[str]] = {}
    for label, by_id in regional.items():
        ids = {cid for cid, results in by_id.items() if health.is_verified_fresh(results, reference)}
        out[label] = ids
    return out
