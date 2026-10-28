#!/usr/bin/env python3
"""Maintain the community live tier (see docs/TIERS.md). The daily run does this through scripts/verify.py.

    python scripts/community.py refresh                    # download iptv-org data and rebuild state/community/catalog.json
    python scripts/community.py refresh --streams DIR --database DIR [--extra-m3u FILE ...]   # from local copies
    python scripts/community.py check [--budget-seconds N]  # check this run's rotating slice (needs network)
    python scripts/community.py report                      # candidate counts after every filter, from the stored catalogue

``refresh`` keeps the last good catalogue when the download fails or the result is implausibly small.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401

from nexonic import community
from nexonic.config import load_pipeline
from nexonic.fetch import ExtraPlaylist
from nexonic.records import load_records
from nexonic.timeutil import iso, utc_now


def _context(records):
    return community.official_context(records), community.load_exclusions()


def cmd_refresh(args) -> int:
    cfg = load_pipeline()
    records = load_records()
    official, exclusions = _context(records)
    if args.streams and args.database:
        extras = [
            ExtraPlaylist("local", "local", p, f"file://{p.name}", f"local:{p.name}") for p in args.extra_m3u or []
        ]
        catalog, report = community.build_catalog(
            args.streams,
            args.database,
            extras,
            official=official,
            exclusions=exclusions,
            cfg=cfg.community,
            built_at=iso(utc_now()),
            mode="local",
        )
        community.save_catalog(catalog)
        print(f"wrote {community.CATALOG_FILE} with {report['catalog']} streams")
    else:
        catalog = community.refresh_catalog(cfg.discovery, cfg.community, official, exclusions)
        if catalog is None:
            return 1
    return cmd_report(args)


def cmd_check(args) -> int:
    cfg = load_pipeline()
    official, exclusions = _context(load_records())
    summary = community.run_daily(
        cfg.discovery,
        cfg.community,
        official,
        exclusions,
        budget_override=args.budget_seconds,
        force_refresh=args.force_refresh,
    )
    print(json.dumps(summary, indent=1))
    return 0


def cmd_report(_args) -> int:
    catalog = community.load_catalog()
    if not catalog:
        print("no community catalogue yet; run: python scripts/community.py refresh", file=sys.stderr)
        return 1
    rep = catalog["report"]
    print(f"catalogue built {catalog['built_at']} ({catalog.get('source_mode')})")
    print(f"entries read: {rep['read']}")
    for name, n in rep["after"].items():
        print(f"  after {name:<28} {n}")
    for key, n in rep.get("deduplicated", {}).items():
        print(f"  de-duplication {key:<30} {n}")
    print(f"catalogue streams: {rep['catalog']}")
    print("top countries: " + ", ".join(f"{c}={n}" for c, n in list(rep["per_country"].items())[:10]))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("refresh")
    r.add_argument("--streams", type=Path)
    r.add_argument("--database", type=Path)
    r.add_argument("--extra-m3u", type=Path, nargs="*")
    r.set_defaults(fn=cmd_refresh)
    c = sub.add_parser("check")
    c.add_argument("--budget-seconds", type=float)
    c.add_argument("--force-refresh", action="store_true")
    c.set_defaults(fn=cmd_check)
    sub.add_parser("report").set_defaults(fn=cmd_report)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
