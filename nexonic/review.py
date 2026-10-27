"""Maintainer review of pending channel records.

``list`` shows what waits in ``data/pending``; ``approve`` moves a record to ``data/approved/<country>.yaml`` (automated
records to ``data/approved/auto/<country>.yaml``) and ``reject`` moves it to ``data/rejected/<country>.yaml``.

Files are edited as text so nothing else in them changes: the record's block is cut out of the source file and the new
block is appended to the destination, written the way the catalogue writers do (``yaml.safe_dump`` with
``sort_keys=False``, ``allow_unicode=True`` and ``width=120``) below the file's leading comment header. A file left
without records is deleted. After a change the whole data directory is validated again, and everything is rolled back
if that fails.

Approval is a human decision: it needs a real authorization basis and a passed adult-content screening, both of which
the record must already carry or the reviewer must state explicitly (``basis``, ``confirm_screening``).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .models import AuthorizationBasis, Channel
from .moderation import publication_gate
from .records import DATA, load_records

MAX_RECORD_NOTE = 500


class ReviewError(ValueError):
    pass


@dataclass
class Pending:
    id: str
    name: str
    country: str
    file: str  # relative to the data directory
    broadcaster: str
    stream_url: str
    automated: bool
    authorization_basis: str
    adult_screening: str
    notes: str


def _header(text: str) -> str:
    """The leading comment block of a data file."""
    lines = []
    for line in text.split("\n"):
        if not line.startswith("#"):
            break
        lines.append(line + "\n")
    return "".join(lines)


def _read(path: Path) -> tuple[str, list[dict]]:
    text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(text) or {}
    items = raw.get("channels") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise ReviewError(f"{path.name}: top-level key 'channels' must be a list")
    return _header(text), items


def _blocks(text: str) -> tuple[list[str], list[tuple[int, int]]]:
    """Split a file into lines and the (start, end) line range of each top-level ``channels`` list item."""
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.startswith("- ")]
    return lines, [(a, b) for a, b in zip(starts, starts[1:] + [len(lines)], strict=True)]


def _item_id(block: str) -> str | None:
    item = yaml.safe_load(block)
    return item[0].get("id") if isinstance(item, list) and item and isinstance(item[0], dict) else None


def _remove_block(text: str, channel_id: str) -> str:
    lines, ranges = _blocks(text)
    for a, b in ranges:
        if _item_id("".join(lines[a:b])) == channel_id:
            rest = lines[:a] + lines[b:]
            if not ranges or len(ranges) == 1:
                # no records left: keep only the header and an empty list so the caller can delete the file
                return ""
            return "".join(rest)
    raise ReviewError(f"could not locate {channel_id!r} in its file")


def _dump_block(item: dict) -> str:
    body = yaml.safe_dump({"channels": [item]}, sort_keys=False, allow_unicode=True, width=120)
    return body.split("\n", 1)[1]  # drop the "channels:" line


def _append_block(text: str, header: str, item: dict) -> str:
    block = _dump_block(item)
    if not text.strip():
        return header + "channels:\n" + block
    if re.search(r"^channels:\s*\[\s*\]\s*$", text, re.M):
        return re.sub(r"^channels:\s*\[\s*\]\s*$", lambda _: "channels:\n" + block.rstrip("\n"), text, flags=re.M) + (
            "" if text.endswith("\n") else "\n"
        )
    return text + ("" if text.endswith("\n") else "\n") + block


def list_pending(data: Path | None = None) -> list[Pending]:
    data = data or DATA
    out = []
    for path in sorted((data / "pending").glob("*.yaml")):
        _, items = _read(path)
        for item in items:
            try:
                ch = Channel.model_validate(item)
            except Exception:  # invalid records are reported by validate.py; show what we can here
                review = item.get("review") or {}
                out.append(
                    Pending(
                        str(item.get("id", "?")),
                        str(item.get("name", "")),
                        str(item.get("country", "")),
                        path.relative_to(data).as_posix(),
                        str(item.get("broadcaster", "")),
                        str((item.get("stream") or {}).get("url", "")),
                        False,
                        str(review.get("authorization_basis", "")),
                        str(review.get("adult_screening", "")),
                        "invalid record",
                    )
                )
                continue
            out.append(
                Pending(
                    ch.id,
                    ch.name,
                    ch.country,
                    path.relative_to(data).as_posix(),
                    ch.broadcaster,
                    ch.stream.url,
                    ch.automated,
                    ch.review.authorization_basis.value,
                    ch.review.adult_screening,
                    " ".join(ch.review.notes.split())[:MAX_RECORD_NOTE],
                )
            )
    return out


def _find(data: Path, channel_id: str) -> tuple[Path, dict]:
    hits = []
    for path in sorted((data / "pending").glob("*.yaml")):
        _, items = _read(path)
        for item in items:
            if isinstance(item, dict) and item.get("id") == channel_id:
                hits.append((path, item))
    if not hits:
        raise ReviewError(f"no pending record with id {channel_id!r}")
    if len(hits) > 1:
        raise ReviewError(f"id {channel_id!r} appears more than once in data/pending")
    return hits[0]


def _target(data: Path, folder: str, item: dict) -> tuple[Path, str]:
    country = str(item.get("country", "")).lower()
    if folder == "rejected":
        return (
            data / "rejected" / f"{country}.yaml",
            f"# Rejected candidates for {country.upper()}, kept so they are not re-added. Never published.\n",
        )
    if (item.get("source") or {}).get("method") == "automated-domain-match":
        return (
            data / "approved" / "auto" / f"{country}.yaml",
            "# Automatically admitted channels (scripts/expand_catalog.py). Published only after a successful live\n"
            "# check. Edit by moving a record to data/approved/<cc>.yaml (human-reviewed) or data/rejected/.\n",
        )
    return (
        data / "approved" / f"{country}.yaml",
        f"# Approved channels for {country.upper()}. See docs/SOURCE_POLICY.md before editing.\n",
    )


def _move(data: Path, channel_id: str, folder: str, edit) -> Path:
    src, item = _find(data, channel_id)
    item = dict(item)
    review = dict(item.get("review") or {})
    edit(item, review)
    item["review"] = review
    try:
        ch = Channel.model_validate(item)
    except Exception as exc:
        raise ReviewError(f"the record would not be valid: {exc}") from exc
    if folder == "approved":
        ok, problems = publication_gate(ch)
        if not ok:
            raise ReviewError("cannot approve: " + "; ".join(problems))
    dest, default_header = _target(data, folder, item)
    dest_text = dest.read_text(encoding="utf-8") if dest.exists() else ""
    if dest.exists() and channel_id in {c.get("id") for c in _read(dest)[1] if isinstance(c, dict)}:
        raise ReviewError(f"{channel_id!r} already exists in {dest.relative_to(data).as_posix()}")
    src_text = src.read_text(encoding="utf-8")
    snapshot = {src: src_text, dest: dest_text if dest.exists() else None}
    remaining = _remove_block(src_text, channel_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_append_block(dest_text, _header(dest_text) or default_header, item), encoding="utf-8")
    if remaining:
        src.write_text(remaining, encoding="utf-8")
    else:
        src.unlink()
    errors = load_records(data).errors
    if errors:
        for path, text in snapshot.items():
            if text is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(text, encoding="utf-8")
        raise ReviewError(f"data validation failed after the change (rolled back): {errors[:3]}")
    return dest


def approve(
    channel_id: str,
    reviewer: str,
    data: Path | None = None,
    today: dt.date | None = None,
    basis: str | None = None,
    confirm_screening: bool = False,
    note: str = "",
) -> Path:
    data = data or DATA
    reviewer = reviewer.strip()
    if len(reviewer) < 2:
        raise ReviewError("a reviewer name is required")
    if basis is not None and basis not in {b.value for b in AuthorizationBasis}:
        raise ReviewError(f"unknown authorization basis {basis!r}")

    def edit(item: dict, review: dict) -> None:
        if basis:
            review["authorization_basis"] = basis
        if review.get("authorization_basis") in (None, "none"):
            raise ReviewError("record has no authorization_basis; pass --basis after checking the evidence")
        if review.get("adult_screening") != "pass":
            if not confirm_screening:
                raise ReviewError(
                    f"adult_screening is {review.get('adult_screening')!r}; review the channel and pass "
                    "--confirm-screening to record 'pass'"
                )
            review["adult_screening"] = "pass"
        review.update(status="approved", reviewer=reviewer, reviewed_at=(today or dt.date.today()).isoformat())
        review["rejection_reason"] = ""
        if note:
            review["notes"] = note

    return _move(data, channel_id, "approved", edit)


def reject(
    channel_id: str,
    reason: str,
    reviewer: str = "maintainer",
    data: Path | None = None,
    today: dt.date | None = None,
) -> Path:
    data = data or DATA
    reason = " ".join(reason.split())
    if not reason:
        raise ReviewError("a rejection reason is required")

    def edit(item: dict, review: dict) -> None:
        review.update(status="rejected", reviewer=reviewer, reviewed_at=(today or dt.date.today()).isoformat())
        review["rejection_reason"] = reason

    return _move(data, channel_id, "rejected", edit)
