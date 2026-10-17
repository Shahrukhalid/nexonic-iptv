#!/usr/bin/env python3
"""Print project statistics computed from data, history and the generation plan (writes reports/statistics.json)."""

from __future__ import annotations

import json
import sys

import _bootstrap  # noqa: F401

from nexonic import generate, reports
from nexonic.records import load_history, load_records


def main() -> int:
    records = load_records()
    history = load_history()
    plan = generate.plan(records, history)
    stats = reports.statistics(records, plan, history)
    reports.write_json("statistics.json", stats)
    summary = {
        k: stats[k]
        for k in (
            "reference_time",
            "records",
            "published_channels",
            "countries",
            "languages",
            "categories",
            "verified_playlist_channels",
            "latest_run_status_counts",
        )
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
