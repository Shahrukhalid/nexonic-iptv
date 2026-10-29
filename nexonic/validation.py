"""Validation rules shared by scripts/validate.py and ``scripts/generate.py --check`` on pull requests.

Checks: schema, folder/status consistency, duplicate ids/URLs/names, URL policy, moderation of approved records,
strict M3U syntax of every playlist file, that every playlist entry belongs to a publishable approved record, that
no pending/rejected record appears anywhere, no duplicates inside a playlist, and index counts. Finally the
publication guard compares the new channel counts with the last commit (see nexonic/guard.py).
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

from . import community, config, guard, m3u, vod
from . import regional as regional_mod
from .dedup import stream_key
from .moderation import publication_gate
from .records import ROOT, load_records, normalise_url
from .safety import check_url_policy


def check_guard(root, index: dict, cfg) -> tuple[list[dict], list[dict], guard.GuardResult]:
    """Publication guard: compare the new channel counts with the last committed ones."""
    verdict = guard.evaluate(guard.baseline_index(root), index, cfg)
    errors, warnings = [], []
    for problem in verdict.violations:
        if verdict.ok:
            warnings.append({"stage": "publication-guard", "warning": f"{problem} (override active)"})
        else:
            errors.append({"stage": "publication-guard", "error": f"{problem}. {guard.HELP}"})
    if verdict.skipped:
        warnings.append({"stage": "publication-guard", "warning": "no committed baseline found; guard skipped"})
    return errors, warnings, verdict


class _TierContext:
    """Rules for the community and free VOD playlists, which are checked against their own state files instead of
    the approved records. Nothing here relaxes the official rules: official playlists never contain these files."""

    def __init__(self, records, cfg, errors: list[dict]):
        self.cfg = cfg
        try:
            self.exclusions = community.load_exclusions()
        except (OSError, ValueError) as exc:
            errors.append({"stage": "community", "error": f"data/community-exclusions.yaml: {exc}"})
            self.exclusions = community.Exclusions()
        self.catalog = {stream_key(s.url): s for s in community.catalog_streams(community.load_catalog())}
        self.official = {stream_key(c.stream.url) for c in records.approved}
        self.rejected = {stream_key(c.stream.url) for k in ("pending", "rejected") for c in records.channels[k]}
        self.vod = {r[0]: r for r in vod.load_items()}

    @staticmethod
    def tier_of(rel: str) -> str:
        if rel.startswith("playlists/community/"):
            return "community"
        if rel.startswith("playlists/vod/"):
            return "vod"
        return "official"

    def check(self, tier: str, rel: str, entries: list[m3u.Entry], errors: list[dict]) -> None:
        def bad(msg: str) -> None:
            errors.append({"stage": f"{tier}-tier", "file": rel, "error": msg})

        for e in entries:
            if tier == "community":
                key = stream_key(e.url)
                s = self.catalog.get(key)
                if s is None:
                    bad(f"URL not in the community catalogue: {e.url}")
                    continue
                pol = check_url_policy(e.url, allow_restream=self.cfg.community.allow_restream_hosts)
                if not pol.ok:
                    bad(f"URL policy: {pol.reason}: {e.url}")
                if key in self.official:
                    bad(f"duplicates an official stream: {e.url}")
                if key in self.rejected:
                    bad(f"pending/rejected URL published: {e.url}")
                if self.exclusions.reason(s.ch, s.id, e.url):
                    bad(f"on the takedown list: {e.url}")
                status = e.attrs.get("x-status")
                if status not in ("verified", "untested"):
                    bad(f"entry has no verified/untested status: {e.url}")
                if rel.endswith("/verified.m3u") and status != "verified":
                    bad(f"non-verified stream in verified.m3u: {e.url}")
                if rel.endswith("/untested.m3u") and (
                    status != "untested" or not e.attrs.get("group-title", "").startswith("Untested")
                ):
                    bad(f"untested.m3u entry is not labelled untested: {e.url}")
            else:
                parts = urlsplit(e.url)
                ident = parts.path.split("/")[2] if parts.path.count("/") >= 3 else ""
                row = self.vod.get(ident)
                if (
                    parts.scheme != "https"
                    or parts.hostname != "archive.org"
                    or not parts.path.startswith("/download/")
                ):
                    bad(f"VOD entry is not an archive.org download link: {e.url}")
                elif row is None:
                    bad(f"VOD item not in the cache: {e.url}")
                elif row[4] not in self.cfg.vod.allowed_licences or not e.attrs.get("x-licence"):
                    bad(f"VOD item without an accepted licence: {e.url}")
                if ident.lower() in self.exclusions.vod:
                    bad(f"on the takedown list: {e.url}")


def collect(base: Path = ROOT) -> dict:
    """Run every check. Records and the git baseline come from the repository; the generated playlists are read from
    ``base`` (the repository itself, or a directory holding freshly generated output)."""
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

    index_path = base / "playlists" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {"playlists": []}
    counts = {item["path"]: item["count"] for item in index["playlists"]}
    files = sorted((base / "playlists").rglob("*.m3u")) if (base / "playlists").exists() else []
    cfg = config.load_pipeline()
    tiers = _TierContext(records, cfg, errors)
    for f in files:
        rel = f.relative_to(base).as_posix()
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
        tier = tiers.tier_of(rel)
        if tier != "official":
            tiers.check(tier, rel, entries, errors)
        else:
            merged = [e for e in entries if e.attrs.get("x-tier") == "community"]
            if merged:
                tiers.check("community", rel, merged, errors)
                bad_status = [e.url for e in merged if e.attrs.get("x-status") != "verified"]
                for url in bad_status:
                    errors.append(
                        {
                            "stage": "community-tier",
                            "file": rel,
                            "error": f"unverified stream in a main playlist: {url}",
                        }
                    )
            for e, u in zip(entries, urls, strict=True):
                if e.attrs.get("x-tier") == "community":
                    continue
                if u in blocked_urls:
                    errors.append(
                        {"stage": "exclusion", "file": rel, "error": f"pending/rejected URL published: {e.url}"}
                    )
                if u not in approved_urls:
                    errors.append(
                        {"stage": "exclusion", "file": rel, "error": f"URL not from an approved record: {e.url}"}
                    )
                if approved_urls.get(u) in blocked_ids:
                    errors.append({"stage": "exclusion", "file": rel, "error": f"blocked id published: {e.url}"})
        if rel not in counts:
            errors.append({"stage": "index", "file": rel, "error": "file not listed in playlists/index.json"})
        elif counts[rel] != len(entries):
            errors.append(
                {"stage": "index", "file": rel, "error": f"index says {counts[rel]}, file has {len(entries)}"}
            )
    for rel in counts:
        if not (base / rel).exists():
            errors.append({"stage": "index", "file": rel, "error": "listed in index but missing"})

    try:
        approved_ids = {c.id for c in records.approved}
        for label, by_id in regional_mod.load_all().items():
            unknown = sorted(set(by_id) - approved_ids)
            if unknown:
                warnings.append(
                    {"stage": "regional", "warning": f"{label}: results for non-approved ids ignored: {unknown[:5]}"}
                )
    except regional_mod.RegionalError as exc:
        errors.append({"stage": "regional", "error": str(exc)})

    g_errors, g_warnings, verdict = check_guard(ROOT, index, cfg.guard)
    errors.extend(g_errors)
    warnings.extend(g_warnings)

    return {
        "ok": not errors,
        "guard": verdict.to_dict(),
        "records": {k: len(v) for k, v in records.channels.items()},
        "playlist_files_checked": len(files),
        "errors": errors,
        "warnings": warnings,
    }
