#!/usr/bin/env python3
"""Validate source records and generated playlists. Exit code 1 on any error.

Checks: schema, folder/status consistency, duplicate ids/URLs/names, URL policy, moderation of approved records,
strict M3U syntax of every generated file, that every playlist entry belongs to a publishable approved record, that
no pending/rejected record appears anywhere, no duplicates inside a playlist, and index counts.
Finally the publication guard compares the new channel counts with the last commit (see nexonic/guard.py).
Writes reports/validation.json.
"""

from __future__ import annotations

import json
import sys

import _bootstrap  # noqa: F401

from nexonic.records import ROOT
from nexonic.validation import check_guard, collect

__all__ = ["check_guard", "collect", "main"]


def main() -> int:
    report = collect(ROOT)
    errors, warnings = report["errors"], report["warnings"]
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "validation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for e in errors:
        print(f"ERROR {e}")
    print(
        f"{len(errors)} error(s), {len(warnings)} warning(s); "
        f"{report['playlist_files_checked']} playlist files checked."
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
