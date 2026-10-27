#!/usr/bin/env python3
"""Run live verification of approved channels and record genuine results.

    python scripts/verify.py                 # all approved channels
    python scripts/verify.py --ids dw-english france-24-english
    python scripts/verify.py --ffprobe       # add an FFprobe readability probe after the HTTP checks

Writes state/history.json, reports/verification.json and reports/verification.md.

Second-location checks (see docs/REGIONAL_CHECKS.md):

    python scripts/verify.py --location-label asia-pk --only restricted
    python scripts/verify.py --location-label asia-pk --only GEO_RESTRICTED,UNKNOWN,TIMEOUT,restricted

re-checks only channels whose latest primary result has one of the listed statuses (upper case) or whose lifecycle
is one of the listed states (lower case), with the same limits and safety rules, and writes
state/regional/<label>.json instead. state/history.json and reports/verification.* are not touched.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import _bootstrap  # noqa: F401

from nexonic import regional
from nexonic.config import load_pipeline
from nexonic.checker import Limits, check_all
from nexonic.records import load_history, load_records, merge_results, save_history
from nexonic.reports import verification_report, write_json
from nexonic.timeutil import utc_now


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ids", nargs="*", help="only check these channel ids")
    ap.add_argument("--ffprobe", action="store_true", help="also probe with FFprobe (if installed)")
    cfg_all = load_pipeline()
    cfg = cfg_all.verify  # defaults come from config/pipeline.toml; flags override
    ap.add_argument("--concurrency", type=int, default=cfg.concurrency)
    ap.add_argument("--timeout", type=float, default=cfg.timeout)
    ap.add_argument(
        "--budget-minutes", type=float, default=cfg.budget_minutes, help="stop starting new checks after this"
    )
    ap.add_argument(
        "--location-label", help="record results as a second checking location (state/regional/<label>.json)"
    )
    ap.add_argument(
        "--only",
        nargs="+",
        metavar="SELECTOR",
        help="with --location-label: only re-check channels whose primary status (e.g. GEO_RESTRICTED) or lifecycle "
        "state (e.g. restricted) matches; comma or space separated; 'all' selects every channel",
    )
    args = ap.parse_args(argv)
    label = None
    if args.only and not args.location_label:
        ap.error("--only needs --location-label (the primary history is always checked in full)")
    if args.location_label:
        try:
            label = regional.check_label(args.location_label)
            if args.only:
                regional.parse_selectors(args.only)
        except regional.RegionalError as exc:
            ap.error(str(exc))

    records = load_records()
    if records.errors:
        print("Refusing to verify: data has validation errors. Run scripts/validate.py.", file=sys.stderr)
        return 2
    channels = records.approved
    if args.ids:
        wanted = set(args.ids)
        channels = [c for c in channels if c.id in wanted]
        missing = wanted - {c.id for c in channels}
        if missing:
            print(f"Unknown or non-approved ids: {', '.join(sorted(missing))}", file=sys.stderr)
            return 2
    if label and args.only:
        channels = regional.select_channels(channels, load_history(), args.only, cfg_all.quarantine)
        if not channels:
            print(f"No channels match --only {' '.join(args.only)}; nothing to check.")
            return 0
    limits = Limits(
        timeout=args.timeout,
        concurrency=max(1, min(args.concurrency, cfg.max_concurrency)),
        retries=cfg.retries,
        backoff_base=cfg.backoff_base,
        per_host_interval=cfg.per_host_interval,
        channel_timeout=cfg.channel_timeout,
        use_ffprobe=args.ffprobe,
        run_budget=args.budget_minutes * 60,
    )
    run_id = utc_now().strftime("run-%Y%m%dT%H%M%SZ")
    where = f" from {label}" if label else ""
    print(f"Verifying {len(channels)} channels{where} ({run_id}) ...")
    results = asyncio.run(check_all(channels, limits))
    known = {c.id for c in records.all()}
    for r in results:
        r.details["run_id"] = f"{run_id}-{label}" if label else run_id
        if label:
            r.location = f"regional:{label}"
    if label:
        # Regional results never touch the primary history or reports.
        path = regional.path_for(label)
        saved = regional.save_location(label, regional.merge(regional.load_location(path), results, known_ids=known))
        print(f"Wrote {saved}")
    else:
        history = merge_results(load_history(), results, known_ids=known)
        save_history(history)
        data, md = verification_report(records, history)
        write_json("verification.json", data)
        (_bootstrap.ROOT / "reports" / "verification.md").write_text(md, encoding="utf-8")
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status.value] = counts.get(r.status.value, 0) + 1
    for status, n in sorted(counts.items()):
        print(f"  {status:<18} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
