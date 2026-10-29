#!/usr/bin/env python3
"""Generate all playlists, the playlist index, PLAYLISTS.md and statistics from approved data.

python scripts/generate.py           # write outputs
python scripts/generate.py --check   # exit 1 if committed outputs are out of date (used in CI)

With GITHUB_EVENT_NAME=pull_request, --check is lenient about stale committed outputs: they are regenerated on main
after a merge (Generate playlists workflow). It then verifies that generation succeeds, is deterministic (two fresh
builds are identical) and passes the validation rules, and lists the outputs that will change after the merge.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

import _bootstrap  # noqa: F401

from nexonic import changes, community, config, generate, reports, validation, vod
from nexonic import regional as regional_mod
from nexonic.records import ROOT, load_history, load_records

OUTPUTS = [
    "playlists",
    "PLAYLISTS.md",
    "README.md",
    "reports/channels.json",
    "reports/statistics.json",
    "reports/verification.json",
    "reports/verification.md",
    "reports/changes.json",
    "reports/changes.md",
]
# Written by the same build; compared only for determinism (they are committed by the verification workflow).
STATE_OUTPUTS = ["state/lifecycle.json", "state/change-history.json"]


def build(root: Path) -> int:
    records = load_records()
    if records.errors:
        for e in records.errors:
            print(f"ERROR {e}", file=sys.stderr)
        return 2
    history = load_history()
    cfg = config.load_pipeline()
    try:
        regional = regional_mod.load_all(ROOT / "state" / "regional")
    except regional_mod.RegionalError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2
    state_in, state_out = ROOT / "state", root / "state"
    state = changes.load_state(state_in / changes.SNAPSHOT_FILE)
    restored = {
        cid: e["restored_at"]
        for cid, e in ((state.get("current") or {}).get("channels") or {}).items()
        if e.get("restored_at")
    }
    plan = generate.plan(records, history, cfg.quarantine, restored, regional)
    try:
        exclusions = community.load_exclusions()
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR data/community-exclusions.yaml: {exc}", file=sys.stderr)
        return 2
    cplan = community.plan_community(
        community.load_catalog(),
        community.load_history(),
        community.official_context(records),
        exclusions,
        cfg.community,
    )
    generate.extend(plan, "community", cplan.files, cplan.index, cplan.stats)
    generate.merge_main(plan, cplan.merge)
    vplan = vod.plan_vod(vod.load_items(), exclusions, cfg.vod, vod.load_progress())
    generate.extend(plan, "vod", vplan.files, vplan.index, vplan.stats)
    current = changes.build_snapshot(records, plan, state.get("current"))
    plan.last_metadata_update = {
        cid: e["meta_changed_at"] for cid, e in current["channels"].items() if "meta_changed_at" in e
    }
    baseline, new_state = changes.advance(state, current)
    generate.write(plan, root)
    (root / "PLAYLISTS.md").write_text(generate.playlists_markdown(plan), encoding="utf-8")
    stats = reports.statistics(records, plan, history)
    vdata, vmd = reports.verification_report(records, history)
    try:
        discovery = json.loads((state_in / changes.DISCOVERY_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        discovery = None
    report = changes.build_report(records, plan, history, baseline, current, discovery, cfg.changes)
    reports.write_json("verification.json", vdata, root)
    (root / "reports" / "verification.md").write_text(vmd + changes.summary_markdown(report), encoding="utf-8")
    reports.write_json("statistics.json", stats, root)
    reports.write_json("changes.json", report, root)
    (root / "reports" / "changes.md").write_text(changes.to_markdown(report), encoding="utf-8")
    changes.write_json_if_changed(state_out / changes.SNAPSHOT_FILE, new_state)
    changes.update_history(state_out / changes.HISTORY_FILE, report, cfg.changes)
    readme_src = ROOT / "README.md"
    if readme_src.exists():
        text = generate.update_readme(readme_src.read_text(encoding="utf-8"), generate.readme_block(plan, stats))
        (root / "README.md").write_text(text, encoding="utf-8")
    print(
        f"Published {len(plan.published)} channels in {len(plan.files)} playlist files; "
        f"{len(plan.verified_ids)} in verified.m3u; {len(plan.excluded)} approved records excluded."
    )
    if cplan.stats:
        cs = cplan.stats
        print(
            f"Community tier: {cs['verified']} verified, {cs['untested']} untested, "
            f"{cs['failing_held_back']} held back after a failed check ({len(cplan.files)} playlist files)."
        )
    if vplan.stats:
        print(f"Free VOD tier: {vplan.stats['items']} items ({len(vplan.files)} playlist files).")
    for item in report["attention"]:
        print(f"ATTENTION {item}")
    reasons: dict[str, int] = {}
    for ex in plan.excluded:
        key = "; ".join(ex["reasons"])[:120]
        reasons[key] = reasons.get(key, 0) + 1
    for key, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"  excluded {n:4}: {key}")
    return 0


def _snapshot(root: Path, items: list[str] = OUTPUTS) -> dict[str, bytes]:
    out = {}
    for item in items:
        p = root / item
        files = sorted(p.rglob("*")) if p.is_dir() else [p]
        for f in files:
            if f.is_file():
                out[f.relative_to(root).as_posix()] = f.read_bytes()
    return out


def _fresh_build(tmp_root: Path, quiet: bool = False) -> int:
    (tmp_root / "reports").mkdir(parents=True, exist_ok=True)
    if (ROOT / "playlists").exists():
        shutil.copytree(ROOT / "playlists", tmp_root / "playlists", dirs_exist_ok=True)
    if quiet:
        with contextlib.redirect_stdout(io.StringIO()):
            return build(tmp_root)
    return build(tmp_root)


def _differences(fresh: dict[str, bytes], committed: dict[str, bytes]) -> list[str]:
    return sorted(k for k in fresh.keys() | committed.keys() if fresh.get(k) != committed.get(k))


def check_pull_request() -> int:
    """Pull request mode: generation must work, be deterministic and valid; stale committed outputs are only listed."""
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        first, second = Path(a), Path(b)
        rc = _fresh_build(first)
        if rc:
            return rc
        rc = _fresh_build(second, quiet=True)
        if rc:
            return rc
        both = OUTPUTS + STATE_OUTPUTS
        unstable = _differences(_snapshot(first, both), _snapshot(second, both))
        if unstable:
            print("Generation is not deterministic: two builds of the same inputs differ.", file=sys.stderr)
            for d in unstable:
                print(f"  {d}", file=sys.stderr)
            return 1
        report = validation.collect(first)
        for e in report["errors"]:
            print(f"ERROR {e}", file=sys.stderr)
        for w in report["warnings"][:5]:
            print(f"WARNING {w}")
        if len(report["warnings"]) > 5:
            print(f"... and {len(report['warnings']) - 5} more warning(s); run scripts/validate.py for the full list.")
        if report["errors"]:
            print(f"Validation of the generated outputs failed ({len(report['errors'])} error(s)).", file=sys.stderr)
            return 1
        stale = _differences(_snapshot(first), _snapshot(ROOT))
    print("Generation succeeded, is deterministic and passes the validation rules.")
    if stale:
        print(
            "Pull request mode: these committed outputs differ from a fresh build. They are regenerated on main "
            "after the merge (Generate playlists workflow), so this does not fail the check:"
        )
        for d in stale:
            print(f"  will change after merge: {d}")
    else:
        print("Committed outputs already match a fresh build; nothing will change after the merge.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    if not args.check:
        return build(ROOT)
    if os.environ.get("GITHUB_EVENT_NAME") == "pull_request":
        return check_pull_request()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        rc = _fresh_build(tmp_root)
        if rc:
            return rc
        diff = _differences(_snapshot(tmp_root), _snapshot(ROOT))
        if diff:
            print("Generated outputs are out of date. Run: python scripts/generate.py", file=sys.stderr)
            for d in diff:
                print(f"  {d}", file=sys.stderr)
            return 1
    print("Generated outputs are up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
