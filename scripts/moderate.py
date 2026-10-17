#!/usr/bin/env python3
"""Run adult-content moderation over every record.

    python scripts/moderate.py                       # report; exit 1 if any APPROVED record is not PASS
    python scripts/moderate.py --refresh-blocklist path/to/iptv-org/database/data/blocklist.csv \
                               --channels path/to/iptv-org/database/data/channels.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import _bootstrap  # noqa: F401

from nexonic.moderation import MODERATION_DIR, Decision, screen
from nexonic.records import load_records


def refresh(blocklist: Path, channels: Path | None) -> None:
    ids = sorted({r["channel"] for r in csv.DictReader(blocklist.open(encoding="utf-8")) if r["reason"] == "nsfw"})
    header = (
        "# Channel IDs blocked by iptv-org/database with reason 'nsfw'.\n"
        "# Source: https://github.com/iptv-org/database/blob/master/data/blocklist.csv (Unlicense)\n"
    )
    (MODERATION_DIR / "iptv-org-nsfw-blocklist.txt").write_text(header + "\n".join(ids) + "\n", encoding="utf-8")
    print(f"wrote {len(ids)} blocklist ids")
    if channels:
        nsfw = [r for r in csv.DictReader(channels.open(encoding="utf-8")) if r["is_nsfw"] == "TRUE"]
        (MODERATION_DIR / "iptv-org-nsfw-channels.txt").write_text(
            "# Channel IDs with is_nsfw=TRUE in iptv-org/database (Unlicense)\n"
            + "\n".join(sorted({r["id"] for r in nsfw}))
            + "\n",
            encoding="utf-8",
        )
        names = sorted(
            {n.strip() for r in nsfw for n in [r["name"], *r["alt_names"].split(";")] if n.strip()}, key=str.casefold
        )
        (MODERATION_DIR / "iptv-org-nsfw-names.txt").write_text(
            "# Names of NSFW channels in iptv-org/database (Unlicense)\n" + "\n".join(names) + "\n", encoding="utf-8"
        )
        print(f"wrote {len(nsfw)} nsfw channel ids and {len(names)} names")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh-blocklist", type=Path)
    ap.add_argument("--channels", type=Path)
    args = ap.parse_args(argv)
    if args.refresh_blocklist:
        refresh(args.refresh_blocklist, args.channels)
        return 0
    records = load_records()
    bad = 0
    for folder, group in records.channels.items():
        for ch in group:
            res = screen(ch)
            mark = {"pass": "PASS ", "quarantine": "REVIEW", "reject": "REJECT"}[res.decision.value]
            if folder == "approved" and res.decision is not Decision.PASS:
                bad += 1
                mark += " !!"
            if res.decision is not Decision.PASS or folder != "approved":
                print(f"[{folder:8}] {mark:9} {ch.id}: {'; '.join(res.reasons) or 'ok'}")
    total = sum(len(g) for g in records.channels.values())
    print(f"Screened {total} records; {bad} approved record(s) failed moderation.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
