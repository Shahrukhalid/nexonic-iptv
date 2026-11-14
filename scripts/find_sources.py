#!/usr/bin/env python3
"""Write the new-source report now (scripts/verify.py also writes it once a week). See nexonic/finder.py.

    python scripts/find_sources.py            # writes reports/source-candidates.json and .md

GITHUB_TOKEN is optional; without it GitHub's lower anonymous rate limits apply.
"""

from __future__ import annotations

import argparse
import os
import sys

import _bootstrap  # noqa: F401

from nexonic import finder


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--max", type=int, default=25, help="repositories examined")
    args = ap.parse_args(argv)
    result = finder.find(os.environ.get("GITHUB_TOKEN"), args.days, args.max)
    finder.write(result)
    print(f"{len(result['candidates'])} candidate(s), {len(result['skipped'])} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
