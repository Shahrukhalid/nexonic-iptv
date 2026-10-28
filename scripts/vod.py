#!/usr/bin/env python3
"""Maintain the free VOD cache (see docs/TIERS.md). The daily run does one slice through scripts/verify.py.

    python scripts/vod.py refresh [--budget-seconds N]   # one slice: search pages, then item metadata (needs network)
    python scripts/vod.py report                         # what the cache holds

Uses only the Internet Archive's free public search and metadata interfaces (no key, no account).
"""

from __future__ import annotations

import argparse
import json
import sys

import _bootstrap  # noqa: F401

from nexonic import community, vod
from nexonic.config import load_pipeline


def cmd_refresh(args) -> int:
    cfg = load_pipeline()
    summary = vod.refresh(
        cfg.vod,
        community.load_exclusions(),
        budget_seconds=args.budget_seconds or cfg.vod.run_budget_seconds,
        force=True,
    )
    print(json.dumps(summary, indent=1))
    return 0


def cmd_report(_args) -> int:
    cfg = load_pipeline()
    plan = vod.plan_vod(vod.load_items(), community.load_exclusions(), cfg.vod, vod.load_progress())
    print(json.dumps(plan.stats, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("refresh")
    r.add_argument("--budget-seconds", type=float)
    r.set_defaults(fn=cmd_refresh)
    sub.add_parser("report").set_defaults(fn=cmd_report)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
