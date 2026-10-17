"""Loading and cross-validating channel records and verification history."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import yaml
from pydantic import ValidationError

from .models import Channel, ReviewStatus
from .status import CheckResult

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STATE = ROOT / "state"
HISTORY_FILE = STATE / "history.json"
HISTORY_LIMIT = 60  # results kept per channel

DIR_STATUS = {"approved": ReviewStatus.APPROVED, "pending": ReviewStatus.PENDING, "rejected": ReviewStatus.REJECTED}


@dataclass
class LoadResult:
    channels: dict[str, list[Channel]] = field(default_factory=lambda: {k: [] for k in DIR_STATUS})
    errors: list[dict] = field(default_factory=list)

    def all(self) -> list[Channel]:
        return [c for group in self.channels.values() for c in group]

    @property
    def approved(self) -> list[Channel]:
        return self.channels["approved"]


def normalise_url(url: str) -> str:
    p = urlsplit(url.strip())
    host = (p.hostname or "").lower()
    netloc = host + (f":{p.port}" if p.port and p.port not in (80, 443) else "")
    return urlunsplit((p.scheme.lower(), netloc, p.path, p.query, ""))


def load_records(data_dir: Path = DATA) -> LoadResult:
    out = LoadResult()
    for dirname, status in DIR_STATUS.items():
        folder = data_dir / dirname
        if not folder.exists():
            continue
        for path in sorted(folder.rglob("*.yaml")):
            rel = path.relative_to(data_dir).as_posix()
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                out.errors.append({"file": rel, "error": f"YAML error: {exc}"})
                continue
            items = raw.get("channels", []) if isinstance(raw, dict) else None
            if not isinstance(items, list):
                out.errors.append({"file": rel, "error": "top-level key 'channels' must be a list"})
                continue
            for i, item in enumerate(items):
                try:
                    ch = Channel.model_validate(item)
                except ValidationError as exc:
                    ident = item.get("id", f"#{i}") if isinstance(item, dict) else f"#{i}"
                    for err in exc.errors():
                        loc = ".".join(str(x) for x in err["loc"])
                        out.errors.append({"file": rel, "id": ident, "error": f"{loc}: {err['msg']}"})
                    continue
                if ch.review.status is not status:
                    out.errors.append(
                        {
                            "file": rel,
                            "id": ch.id,
                            "error": f"review.status {ch.review.status.value} does not match folder {dirname}",
                        }
                    )
                    continue
                if dirname == "approved" and path.stem != ch.country:
                    out.errors.append(
                        {
                            "file": rel,
                            "id": ch.id,
                            "error": f"approved channel country {ch.country} must live in approved/{ch.country}.yaml",
                        }
                    )
                if dirname == "approved" and ch.automated != (path.parent.name == "auto"):
                    out.errors.append(
                        {"file": rel, "id": ch.id, "error": "automated records live in approved/auto/, manual ones not"}
                    )
                out.channels[dirname].append(ch)
    out.errors.extend(cross_check(out))
    return out


def cross_check(res: LoadResult) -> list[dict]:
    errors: list[dict] = []
    seen_ids: dict[str, str] = {}
    for dirname, group in res.channels.items():
        for ch in group:
            if ch.id in seen_ids:
                errors.append({"id": ch.id, "error": f"duplicate id (in {seen_ids[ch.id]} and {dirname})"})
            seen_ids.setdefault(ch.id, dirname)
    seen_urls: dict[str, str] = {}
    for ch in res.approved:
        key = normalise_url(ch.stream.url)
        if key in seen_urls:
            errors.append({"id": ch.id, "error": f"duplicate stream URL (also used by {seen_urls[key]})"})
        seen_urls.setdefault(key, ch.id)
    seen_names: dict[tuple[str, str], str] = {}
    for ch in res.approved:
        key = (ch.country, ch.name.casefold())
        if key in seen_names:
            errors.append({"id": ch.id, "error": f"duplicate channel name in {ch.country} (also {seen_names[key]})"})
        seen_names.setdefault(key, ch.id)
    return errors


def load_history(path: Path = HISTORY_FILE) -> dict[str, list[CheckResult]]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {cid: [CheckResult.from_dict(r) for r in items] for cid, items in raw.get("channels", {}).items()}


def save_history(history: dict[str, list[CheckResult]], path: Path = HISTORY_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema": 1,
        "note": "Rolling verification history written by scripts/verify.py. Do not edit by hand.",
        "channels": {
            cid: [r.to_dict() for r in sorted(items, key=lambda r: r.checked_at)[-HISTORY_LIMIT:]]
            for cid, items in sorted(history.items())
        },
    }
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def merge_results(
    history: dict[str, list[CheckResult]], results: list[CheckResult], known_ids: set[str] | None = None
) -> dict[str, list[CheckResult]]:
    merged = {k: list(v) for k, v in history.items()}
    for r in results:
        merged.setdefault(r.channel_id, []).append(r)
    if known_ids is not None:
        merged = {k: v for k, v in merged.items() if k in known_ids}
    return merged
