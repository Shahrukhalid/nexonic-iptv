#!/usr/bin/env python3
"""Turn an external M3U playlist into *review candidates* (never into approved records).

    python scripts/discover.py path/to/source.m3u --country de
    python scripts/discover.py https://example.org/list.m3u --country de

Each entry is pre-screened (URL policy + adult lexicon) and written to reports/discovery-candidates.yaml with the
problems found. A maintainer must research evidence on the broadcaster's own site and then add the record to
data/pending/ (and later data/approved/) by hand. Nothing is approved automatically.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import yaml

import _bootstrap  # noqa: F401

from nexonic import m3u
from nexonic.moderation import STRONG_TERMS, WEAK_TERMS, tokens
from nexonic.records import ROOT, load_records, normalise_url
from nexonic.safety import check_url_policy, resolve_public


def read_source(src: str) -> str:
    if src.startswith(("http://", "https://")):
        import httpx

        pol = check_url_policy(src)
        if not pol.ok:
            raise SystemExit(f"source URL rejected: {pol.reason}")
        from urllib.parse import urlsplit

        p = urlsplit(src)
        resolve_public(p.hostname, p.port or 443)
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            r = client.get(src)
            r.raise_for_status()
            if len(r.content) > 20 * 1024 * 1024:
                raise SystemExit("source too large")
            return r.text
    return Path(src).read_text(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("--country", required=True, help="ISO 3166-1 alpha-2 code for the candidates")
    ap.add_argument("--out", type=Path, default=ROOT / "reports" / "discovery-candidates.yaml")
    args = ap.parse_args(argv)

    entries = m3u.parse(read_source(args.source))
    known = {normalise_url(c.stream.url) for c in load_records().all()}
    candidates = []
    for e in entries:
        problems = []
        pol = check_url_policy(e.url)
        if not pol.ok:
            problems.append(f"url-policy: {pol.reason}")
        toks = set(tokens(f"{e.title} {e.attrs.get('group-title', '')} {e.attrs.get('tvg-id', '')}"))
        if toks & STRONG_TERMS:
            problems.append(f"adult terms: {sorted(toks & STRONG_TERMS)} — do not add")
        elif toks & WEAK_TERMS:
            problems.append(f"ambiguous terms: {sorted(toks & WEAK_TERMS)} — manual review")
        if normalise_url(e.url) in known:
            problems.append("already in data/")
        candidates.append(
            {
                "name": e.title,
                "stream_url": e.url,
                "country": args.country.lower(),
                "tvg_id": e.attrs.get("tvg-id"),
                "group": e.attrs.get("group-title"),
                "prescreen_problems": problems,
                "next_steps": "find the broadcaster's own live page (evidence_url), confirm the host belongs to the "
                "broadcaster, then add to data/pending/ with review.status: pending",
            }
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "generated_on": dt.date.today().isoformat(),
        "source": args.source,
        "warning": "Candidates are unreviewed. Do not publish without evidence.",
        "candidates": candidates,
    }
    args.out.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    clean = sum(1 for c in candidates if not c["prescreen_problems"])
    print(f"{len(candidates)} candidates written to {args.out} ({clean} without pre-screen problems)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
