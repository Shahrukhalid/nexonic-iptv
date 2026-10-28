"""Machine- and human-readable reports. Every number comes from records, history or generated files."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .generate import Plan
from .records import ROOT, LoadResult
from .reference import CATEGORIES, LANGUAGES, countries
from .status import CheckResult, Status
from .timeutil import iso

REPORTS = ROOT / "reports"


def latest_run(history: dict[str, list[CheckResult]], ids: set[str]) -> dict | None:
    """The latest run is identified by its run_id stored in result details."""
    runs: dict[str, list[CheckResult]] = {}
    for cid in ids:
        for r in history.get(cid, []):
            run_id = r.details.get("run_id")
            if run_id:
                runs.setdefault(run_id, []).append(r)
    if not runs:
        return None
    run_id = max(runs, key=lambda k: max(r.checked_at for r in runs[k]))
    results = sorted(runs[run_id], key=lambda r: r.channel_id)
    counts = Counter(r.status.value for r in results)
    return {
        "run_id": run_id,
        "started_at": min(r.checked_at for r in results),
        "finished_at": max(r.checked_at for r in results),
        "location": results[0].location,
        "checked": len(results),
        "by_status": dict(sorted(counts.items())),
        "results": [r.to_dict() for r in results],
    }


def statistics(records: LoadResult, plan: Plan, history: dict[str, list[CheckResult]]) -> dict:
    pub = plan.published
    run = latest_run(history, {c.id for c in records.approved})
    by_status = Counter()
    if run:
        by_status.update(run["by_status"])
    display = Counter(plan.health[c.id].display_status for c in pub)
    cn = countries()
    out = {
        "reference_time": iso(plan.reference) if plan.reference else None,
        "records": {k: len(v) for k, v in records.channels.items()},
        "published_channels": len(pub),
        "excluded_approved": len(plan.excluded),
        "countries": len({c.country for c in pub}),
        "languages": len({lg for c in pub for lg in c.languages}),
        "categories": len({ct for c in pub for ct in c.categories}),
        "verified_playlist_channels": len(plan.verified_ids),
        "playlist_files": len(plan.files),
        "latest_run": None
        if not run
        else {k: run[k] for k in ("run_id", "started_at", "finished_at", "location", "checked", "by_status")},
        "latest_run_status_counts": {s.value: by_status.get(s.value, 0) for s in Status},
        "display_status_counts": dict(sorted(display.items())),
        "per_country": {
            code: {
                "name": cn[code]["name"],
                "flag": cn[code]["flag"],
                "channels": sum(1 for c in pub if c.country == code),
            }
            for code in sorted({c.country for c in pub})
        },
        "per_language": {
            lg: {"name": LANGUAGES[lg], "channels": sum(1 for c in pub if lg in c.languages)}
            for lg in sorted({lg for c in pub for lg in c.languages})
        },
        "per_category": {
            ct: {"name": CATEGORIES[ct], "channels": sum(1 for c in pub if ct in c.categories)}
            for ct in sorted({ct for c in pub for ct in c.categories})
        },
    }
    out["tiers"] = tier_statistics(plan)
    if plan.regional:  # only present when another location has reported results
        working = {i["key"]: i["count"] for i in plan.index if i["kind"] == "region"}
        out["regional"] = {
            "note": "Results from additional checking locations. They describe reachability from that location only.",
            "restricted_confirmed_elsewhere": len(plan.works_in),
            "locations": {
                label: {**info, "verified_working": working.get(label, 0)}
                for label, info in sorted(plan.regional.items())
            },
        }
    return out


def tier_statistics(plan: Plan) -> dict:
    """Numbers per tier. Official, community verified and community untested are always reported separately."""
    out: dict = {
        "note": "Tiers are never mixed. 'Untested' community streams have not been confirmed working.",
        "official": {
            "published": len(plan.published),
            "verified": len(plan.verified_ids),
            "not_verified": len(plan.published) - len(plan.verified_ids),
            "with_measured_quality": len(plan.quality),
            "per_quality": dict(sorted(Counter(plan.quality.values()).items())),
        },
        "community": None,
        "vod": None,
    }
    c = plan.tiers.get("community")
    if c:
        out["community"] = {
            "published": c["verified"] + c["untested"],
            "verified": c["verified"],
            "untested": c["untested"],
            "held_back_after_failed_check": c["failing_held_back"],
            "never_checked": c["never_checked"],
            "catalog_streams": c["catalog_streams"],
            "catalog_built_at": c["catalog_built_at"],
            "verified_days": c["verified_days"],
            "countries": c["countries"],
            "languages": c["languages"],
            "lifecycle": c["lifecycle"],
            "removed_at_generation": c["removed_at_generation"],
            "top_countries": c["top_countries"],
            "playlist_files": c["playlist_files"],
            "build_report": c["build_report"],
        }
    v = plan.tiers.get("vod")
    if v:
        out["vod"] = {k: v[k] for k in v}
    return out


def write_json(name: str, data: dict, root: Path = ROOT) -> Path:
    path = root / "reports" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")
    return path


def verification_report(records: LoadResult, history: dict[str, list[CheckResult]]) -> tuple[dict, str]:
    ids = {c.id for c in records.approved}
    run = latest_run(history, ids)
    names = {c.id: c.name for c in records.approved}
    if run is None:
        data = {
            "latest_run": None,
            "note": "No live verification run has been completed yet. Every channel is NOT_TESTED. "
            "Runs happen in GitHub Actions (.github/workflows/verify-streams.yml).",
            "channels": {cid: Status.NOT_TESTED.value for cid in sorted(ids)},
        }
        md = (
            "# Verification report\n\n**No live verification run has been completed yet.**\n\n"
            f"All {len(ids)} approved channels are `NOT_TESTED`. The scheduled workflow "
            "`verify-streams.yml` produces the first real results. Nothing in this repository claims a stream "
            "works before that run.\n"
        )
        return data, md
    data = {"latest_run": run}
    lines = [
        "# Verification report",
        "",
        f"- Run: `{run['run_id']}`",
        f"- Started: {run['started_at']} (UTC) · Finished: {run['finished_at']} (UTC)",
        f"- Checked from: {run['location']}",
        f"- Channels checked: {run['checked']}",
        "",
        "Results describe reachability **from the checker's network location at that time** only.",
        "",
        "| Status | Count |",
        "|---|---:|",
    ]
    for status, n in sorted(run["by_status"].items()):
        lines.append(f"| `{status}` | {n} |")
    lines += [
        "",
        "| Channel | Status | Level | HTTP | Latency | Checked (UTC) | Note |",
        "|---|---|---:|---:|---:|---|---|",
    ]
    for r in run["results"]:
        note = (r.get("error") or r["details"].get("max_resolution") or "").replace("|", "/")[:90]
        lat = f"{r['latency_ms']} ms" if r.get("latency_ms") is not None else "–"
        lines.append(
            f"| {names.get(r['channel_id'], r['channel_id'])} | `{r['status']}` | {r['level']} | "
            f"{r.get('http_status') or '–'} | {lat} | {r['checked_at']} | {note} |"
        )
    return data, "\n".join(lines) + "\n"
