#!/usr/bin/env python3
"""Validate source records and generated playlists. Exit code 1 on any error.

Checks: schema, folder/status consistency, duplicate ids/URLs/names, URL policy, moderation of approved records,
strict M3U syntax of every generated file, that every playlist entry belongs to a publishable approved record, that
no pending/rejected record appears anywhere, no duplicates inside a playlist, and index counts.
Writes reports/validation.json.
"""

from __future__ import annotations

import json
import sys

import _bootstrap  # noqa: F401

from nexonic import m3u
from nexonic.moderation import publication_gate
from nexonic.records import ROOT, load_records, normalise_url
from nexonic.safety import check_url_policy


def main() -> int:
    errors: list[dict] = []
    warnings: list[dict] = []
    records = load_records()
    errors.extend({"stage": "schema", **e} for e in records.errors)

    for ch in records.approved:
        for label, url in (
            ("stream.url", ch.stream.url),
            ("website", ch.website),
            ("source.evidence_url", ch.source.evidence_url),
        ):
            pol = check_url_policy(url, check_tokens=(label == "stream.url"))
            if not pol.ok:
                errors.append({"stage": "url-policy", "id": ch.id, "field": label, "error": pol.reason})
        if not ch.automated and (
            not ch.website.startswith("https://") or not ch.source.evidence_url.startswith("https://")
        ):
            errors.append({"stage": "provenance", "id": ch.id, "error": "website and evidence_url must be https"})
        ok, problems = publication_gate(ch)
        if not ok:
            errors.append({"stage": "moderation", "id": ch.id, "error": "; ".join(problems)})
        if ch.source.evidence_checked is None and not ch.automated:
            warnings.append(
                {
                    "stage": "provenance",
                    "id": ch.id,
                    "warning": "evidence_url not yet confirmed by a maintainer (source.evidence_checked)",
                }
            )

    approved_urls = {normalise_url(c.stream.url): c.id for c in records.approved}
    blocked_ids = {c.id for k in ("pending", "rejected") for c in records.channels[k]}
    blocked_urls = {normalise_url(c.stream.url) for k in ("pending", "rejected") for c in records.channels[k]}

    index_path = ROOT / "playlists" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {"playlists": []}
    counts = {item["path"]: item["count"] for item in index["playlists"]}
    files = sorted((ROOT / "playlists").rglob("*.m3u")) if (ROOT / "playlists").exists() else []
    for f in files:
        rel = f.relative_to(ROOT).as_posix()
        try:
            entries = m3u.parse(f.read_text(encoding="utf-8"))
        except m3u.M3UError as exc:
            errors.append({"stage": "m3u-syntax", "file": rel, "error": str(exc)})
            continue
        if not entries:
            errors.append({"stage": "m3u", "file": rel, "error": "empty playlist file"})
        urls = [normalise_url(e.url) for e in entries]
        if len(urls) != len(set(urls)):
            errors.append({"stage": "m3u", "file": rel, "error": "duplicate entry inside playlist"})
        for e, u in zip(entries, urls, strict=True):
            if u in blocked_urls:
                errors.append({"stage": "exclusion", "file": rel, "error": f"pending/rejected URL published: {e.url}"})
            if u not in approved_urls:
                errors.append({"stage": "exclusion", "file": rel, "error": f"URL not from an approved record: {e.url}"})
            if approved_urls.get(u) in blocked_ids:
                errors.append({"stage": "exclusion", "file": rel, "error": f"blocked id published: {e.url}"})
        if rel not in counts:
            errors.append({"stage": "index", "file": rel, "error": "file not listed in playlists/index.json"})
        elif counts[rel] != len(entries):
            errors.append(
                {"stage": "index", "file": rel, "error": f"index says {counts[rel]}, file has {len(entries)}"}
            )
    for rel in counts:
        if not (ROOT / rel).exists():
            errors.append({"stage": "index", "file": rel, "error": "listed in index but missing"})

    report = {
        "ok": not errors,
        "records": {k: len(v) for k, v in records.channels.items()},
        "playlist_files_checked": len(files),
        "errors": errors,
        "warnings": warnings,
    }
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "validation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for e in errors:
        print(f"ERROR {e}")
    print(f"{len(errors)} error(s), {len(warnings)} warning(s); {len(files)} playlist files checked.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
