#!/usr/bin/env python3
"""Write the static files the cloud Xtream gateway serves (see cloud/README.md). Run by the website deployment.

python scripts/xtream_export.py --out website/dist/xtream
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import _bootstrap  # noqa: F401

from nexonic.records import ROOT
from nexonic.xtream import export_static


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--playlists", type=Path, default=ROOT / "playlists")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    meta = export_static(args.playlists, args.out)
    print(f"Xtream files in {args.out}: {meta['live']} channels, {meta['movies']} films, {meta['episodes']} episodes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
