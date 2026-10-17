#!/usr/bin/env python3
"""Generate all playlists, the playlist index, PLAYLISTS.md and statistics from approved data.

python scripts/generate.py           # write outputs
python scripts/generate.py --check   # exit 1 if committed outputs are out of date (used in CI)
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

import _bootstrap  # noqa: F401

from nexonic import generate, reports
from nexonic.records import ROOT, load_history, load_records

OUTPUTS = ["playlists", "PLAYLISTS.md", "README.md", "reports/channels.json", "reports/statistics.json"]


def build(root: Path) -> int:
    records = load_records()
    if records.errors:
        for e in records.errors:
            print(f"ERROR {e}", file=sys.stderr)
        return 2
    history = load_history()
    plan = generate.plan(records, history)
    generate.write(plan, root)
    (root / "PLAYLISTS.md").write_text(generate.playlists_markdown(plan), encoding="utf-8")
    stats = reports.statistics(records, plan, history)
    reports.write_json("statistics.json", stats, root)
    readme_src = ROOT / "README.md"
    if readme_src.exists():
        text = generate.update_readme(readme_src.read_text(encoding="utf-8"), generate.readme_block(plan, stats))
        (root / "README.md").write_text(text, encoding="utf-8")
    print(
        f"Published {len(plan.published)} channels in {len(plan.files)} playlist files; "
        f"{len(plan.verified_ids)} in verified.m3u; {len(plan.excluded)} approved records excluded."
    )
    reasons: dict[str, int] = {}
    for ex in plan.excluded:
        key = "; ".join(ex["reasons"])[:120]
        reasons[key] = reasons.get(key, 0) + 1
    for key, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"  excluded {n:4}: {key}")
    return 0


def _snapshot(root: Path) -> dict[str, bytes]:
    out = {}
    for item in OUTPUTS:
        p = root / item
        files = sorted(p.rglob("*")) if p.is_dir() else [p]
        for f in files:
            if f.is_file():
                out[f.relative_to(root).as_posix()] = f.read_bytes()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    if not args.check:
        return build(ROOT)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        (tmp_root / "reports").mkdir()
        if (ROOT / "playlists").exists():
            shutil.copytree(ROOT / "playlists", tmp_root / "playlists")
        rc = build(tmp_root)
        if rc:
            return rc
        fresh, committed = _snapshot(tmp_root), _snapshot(ROOT)
        diff = sorted(k for k in fresh.keys() | committed.keys() if fresh.get(k) != committed.get(k))
        if diff:
            print("Generated outputs are out of date. Run: python scripts/generate.py", file=sys.stderr)
            for d in diff:
                print(f"  {d}", file=sys.stderr)
            return 1
    print("Generated outputs are up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
