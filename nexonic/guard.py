"""Publication safety guard: refuse to publish a run whose output is implausibly different from the last commit.

The baseline is ``playlists/index.json`` as committed at ``HEAD`` (or a file named by NEXONIC_GUARD_BASELINE). The
guard fails when the published channel count falls by more than ``max_drop_percent``, when more than ``max_added``
channels appear in one run, or when the verified playlist shrinks by more than ``max_verified_drop_percent``.
``override`` in config/pipeline.toml, or NEXONIC_GUARD_OVERRIDE=1 in the environment, lets a reviewed change through.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .config import GuardConfig, guard_override


@dataclass
class GuardResult:
    ok: bool
    skipped: bool = False
    overridden: bool = False
    baseline: dict | None = None
    current: dict | None = None
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def counts_from_index(index: dict) -> dict[str, int]:
    out = {"published": 0, "verified": 0}
    for item in index.get("playlists", []):
        if item.get("kind") == "global":
            out["published"] = item["count"]
        elif item.get("kind") == "verified":
            out["verified"] = item["count"]
    return out


def baseline_index(root: Path, ref: str = "HEAD") -> dict | None:
    """The last committed playlists/index.json, or None when it cannot be read (first run, no git)."""
    override = os.environ.get("NEXONIC_GUARD_BASELINE")
    try:
        if override:
            return json.loads(Path(override).read_text(encoding="utf-8"))
        out = subprocess.run(
            ["git", "show", f"{ref}:playlists/index.json"], cwd=root, check=True, capture_output=True, text=True
        ).stdout
        return json.loads(out)
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None


def evaluate(baseline: dict | None, current: dict, cfg: GuardConfig, override: bool | None = None) -> GuardResult:
    override = guard_override(cfg) if override is None else override
    if baseline is None:
        return GuardResult(ok=True, skipped=True, current=counts_from_index(current))
    old, new = counts_from_index(baseline), counts_from_index(current)
    problems: list[str] = []
    if old["published"] >= cfg.min_baseline and new["published"] < old["published"]:
        pct = 100 * (old["published"] - new["published"]) / old["published"]
        if pct > cfg.max_drop_percent:
            problems.append(
                f"published channels fell from {old['published']} to {new['published']} "
                f"(-{pct:.1f}%, limit {cfg.max_drop_percent:g}%)"
            )
    added = new["published"] - old["published"]
    if added > cfg.max_added:
        problems.append(f"{added} channels were added in one run (limit {cfg.max_added})")
    if old["verified"] >= cfg.min_baseline and new["verified"] < old["verified"]:
        pct = 100 * (old["verified"] - new["verified"]) / old["verified"]
        if pct > cfg.max_verified_drop_percent:
            problems.append(
                f"the verified playlist fell from {old['verified']} to {new['verified']} "
                f"(-{pct:.1f}%, limit {cfg.max_verified_drop_percent:g}%)"
            )
    return GuardResult(
        ok=not problems or override,
        overridden=bool(problems) and override,
        baseline=old,
        current=new,
        violations=problems,
    )


HELP = (
    "Review reports/changes.md. If the change is expected, publish it deliberately by setting NEXONIC_GUARD_OVERRIDE=1 "
    "for the run or guard.override = true in config/pipeline.toml (revert it afterwards). Thresholds live in the "
    "[guard] section of config/pipeline.toml."
)
