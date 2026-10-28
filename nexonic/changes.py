"""Daily change report: what changed since the previous verification run.

Inputs are the loaded records, the generation plan and the verification history; the only other input is the
snapshot kept in ``state/lifecycle.json``. Nothing here reads the clock: dates come from the verification
reference time, so running generation twice on the same inputs produces identical output and no diff.

Snapshot layout (``state/lifecycle.json``)::

    {"schema": 1, "current": <snapshot>, "previous": <snapshot|null>}

``current`` describes the latest generation. ``previous`` is the snapshot as it stood when the verification
reference time last changed; it is the baseline the report compares against. Re-running generation for the same
reference time keeps the baseline, so a mid-day data edit is reported together with that day's run.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from . import m3u, reports
from .config import ChangesConfig
from .dedup import stream_key
from .generate import Plan
from .lifecycle import Lifecycle
from .records import LoadResult
from .status import FAILURES, CheckResult
from .timeutil import iso

SNAPSHOT_FILE = "lifecycle.json"
HISTORY_FILE = "change-history.json"
DISCOVERY_FILE = "discovery.json"
FAILING_STATES = {Lifecycle.UNREACHABLE.value, Lifecycle.INVALID.value}
LIST_KEYS = (
    "new_candidates",
    "new_published",
    "updated",
    "duplicates_removed",
    "newly_failing",
    "newly_quarantined",
    "restored",
    "removed",
)


def _h(value) -> str:
    return hashlib.sha1(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:8]  # noqa: S324


def meta_of(ch) -> dict[str, str]:
    """Short hash per metadata field, so a change can be reported field by field without storing the values."""
    return {
        "name": _h(ch.name),
        "stream_url": _h(ch.stream.url),
        "website": _h(ch.website),
        "broadcaster": _h(ch.broadcaster),
        "categories": _h(ch.categories),
        "languages": _h(ch.languages),
        "epg_id": _h(ch.epg_id),
        "logo": _h(ch.logo),
        "geo": _h(ch.geo.model_dump()),
    }


def exclusion_kind(reasons: list[str]) -> str:
    first = reasons[0] if reasons else ""
    if first.startswith("stale"):
        return "stale"
    if first.startswith("automated record awaiting"):
        return "awaiting-first-check"
    if first.startswith("duplicate"):
        return "duplicate"
    return "gate"


def build_snapshot(records: LoadResult, plan: Plan, prior: dict | None) -> dict:
    prior_channels = (prior or {}).get("channels", {})
    published = {c.id for c in plan.published}
    excluded = {e["id"]: e for e in plan.excluded}
    ref_date = iso(plan.reference)[:10] if plan.reference else None
    channels: dict[str, dict] = {}
    for status, group in records.channels.items():
        for ch in group:
            entry: dict = {"record": status, "name": ch.name, "country": ch.country}
            if status == "approved":
                info = plan.lifecycle[ch.id]
                meta = meta_of(ch)
                before = prior_channels.get(ch.id, {})
                if before.get("meta") == meta and before.get("meta_changed_at"):
                    changed = before["meta_changed_at"]
                elif before.get("meta") and ref_date:
                    changed = ref_date
                else:
                    changed = ch.review.reviewed_at.isoformat()
                entry.update(
                    automated=ch.automated,
                    published=ch.id in published,
                    verified=ch.id in plan.verified_ids,
                    state=info.state.value,
                    quarantined=info.quarantined,
                    restored_at=info.restored_at,
                    kind=None if ch.id in published else exclusion_kind(excluded[ch.id]["reasons"]),
                    meta=meta,
                    meta_changed_at=changed,
                )
            channels[ch.id] = entry
    return {
        "reference_time": iso(plan.reference) if plan.reference else None,
        "channels": dict(sorted(channels.items())),
    }


def load_state(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": 1, "current": None, "previous": None}
    return {"schema": 1, "current": raw.get("current"), "previous": raw.get("previous")}


def advance(state: dict, new: dict) -> tuple[dict | None, dict]:
    """Return (baseline to compare with, state to store)."""
    cur = state.get("current")
    if cur and cur.get("reference_time") == new["reference_time"]:
        baseline = state.get("previous")
    else:
        baseline = cur
    return baseline, {"schema": 1, "current": new, "previous": baseline}


def write_json_if_changed(path: Path, data, indent: int | None = 1) -> bool:
    text = json.dumps(data, indent=indent, ensure_ascii=False, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def _cap(items: list[dict], limit: int) -> list[dict]:
    return items[:limit]


def build_report(
    records: LoadResult,
    plan: Plan,
    history: dict[str, list[CheckResult]],
    baseline: dict | None,
    current: dict,
    discovery: dict | None,
    cfg: ChangesConfig,
) -> dict:
    now = current["channels"]
    before = (baseline or {}).get("channels", {})
    base_ref = (baseline or {}).get("reference_time")
    lists: dict[str, list[dict]] = {k: [] for k in LIST_KEYS}

    def brief(cid: str, **extra) -> dict:
        e = now.get(cid) or before.get(cid) or {}
        return {"id": cid, "name": e.get("name", ""), "country": e.get("country", ""), **extra}

    if baseline is not None:
        for cid, e in now.items():
            b = before.get(cid)
            if e["record"] == "approved":
                if e["published"] and not (b or {}).get("published") and (b or {}).get("kind") != "stale":
                    lists["new_published"].append(brief(cid))
                if b and b.get("meta") and b["meta"] != e["meta"]:
                    fields = sorted(k for k in e["meta"] if b["meta"].get(k) != e["meta"][k])
                    lists["updated"].append(brief(cid, fields=fields, url_changed="stream_url" in fields))
                if e["kind"] == "duplicate" and (b or {}).get("kind") != "duplicate":
                    lists["duplicates_removed"].append(brief(cid))
                if e["state"] in FAILING_STATES and (b or {}).get("state") not in FAILING_STATES:
                    results = [r for r in history.get(cid, []) if r.status in FAILURES]
                    err = (results[-1].error if results else "")[:120]
                    lists["newly_failing"].append(brief(cid, state=e["state"], error=err))
                if e["quarantined"] and not (b or {}).get("quarantined"):
                    lists["newly_quarantined"].append(brief(cid, since=plan.lifecycle[cid].quarantined_since))
                if base_ref and e["restored_at"] and e["restored_at"] > base_ref:
                    lists["restored"].append(brief(cid, restored_at=e["restored_at"]))
            if b is None and (e["record"] == "pending" or (e["record"] == "approved" and not e["published"])):
                lists["new_candidates"].append(brief(cid, record=e["record"], kind=e.get("kind")))
        for cid, b in before.items():
            if (
                b.get("published")
                and not (now.get(cid) or {}).get("published")
                and now.get(cid, {}).get("record") != "approved"
            ):
                lists["removed"].append(brief(cid))

    published_states = Counter(plan.lifecycle[c.id].state.value for c in plan.published)
    dup_total = sum(1 for e in plan.excluded if e["reasons"] and e["reasons"][0].startswith("duplicate"))
    latest = reports.latest_run(history, {c.id for c in records.approved})
    attention: list[str] = []
    if records.errors:
        attention.append(f"{len(records.errors)} record validation error(s); run scripts/validate.py for details")
    if latest:
        not_tested = latest["by_status"].get("NOT_TESTED", 0)
        if not_tested:
            attention.append(f"{not_tested} channel(s) were not tested in the latest run (run budget exhausted)")
        failing = sum(latest["by_status"].get(s.value, 0) for s in FAILURES)
        if latest["checked"] >= 20 and failing / latest["checked"] > 0.5:
            attention.append(
                f"{failing} of {latest['checked']} checks failed in the latest run; the checker's network may be "
                "impaired, review before trusting the results"
            )
    else:
        attention.append("no verification run has been recorded yet")
    if discovery and discovery.get("stats", {}).get("schema-invalid"):
        attention.append(f"discovery skipped {discovery['stats']['schema-invalid']} candidate(s) with invalid schema")
    quarantined_now = sum(1 for e in now.values() if e.get("quarantined"))
    if lists["newly_quarantined"]:
        attention.append(f"{len(lists['newly_quarantined'])} channel(s) newly quarantined (failing repeatedly)")

    index_ok = all(len(m3u.parse(plan.files[i["path"]])) == i["count"] for i in plan.index)
    unique_streams = len({stream_key(c.stream.url) for c in plan.published}) == len(plan.published)
    integrity = {
        "ok": not records.errors and index_ok and unique_streams,
        "record_errors": len(records.errors),
        "playlist_index_matches_files": index_ok,
        "published_streams_unique": unique_streams,
        "playlist_files": len(plan.files),
        "note": "Full checks (URL policy, moderation, M3U syntax) run in scripts/validate.py before every commit.",
    }
    if not integrity["ok"]:
        attention.append("integrity check failed; see the integrity section")

    counts = {
        "published": len(plan.published),
        "verified_playlist": len(plan.verified_ids),
        "excluded": len(plan.excluded),
        "pending_authorization": len(records.channels["pending"]),
        "quarantined": quarantined_now,
        "duplicates_excluded_total": dup_total,
        **{k: len(v) for k, v in lists.items()},
    }
    report = {
        "reference_time": current["reference_time"],
        "baseline_reference_time": base_ref,
        "baseline_available": baseline is not None,
        "note": "Results describe reachability from the checker's network location at the reference time only.",
        "counts": counts,
        "lifecycle_counts": dict(sorted(published_states.items())),
        "latest_run": None
        if not latest
        else {k: latest[k] for k in ("run_id", "started_at", "finished_at", "location", "checked", "by_status")},
        "discovery": (discovery or {}).get("stats"),
        "integrity": integrity,
        "attention": attention,
        "lists": {k: _cap(v, cfg.max_listed) for k, v in lists.items()},
        "truncated": {k: len(v) - cfg.max_listed for k, v in lists.items() if len(v) > cfg.max_listed},
    }
    report["tiers"] = reports.tier_statistics(plan)
    if plan.regional:  # only present when another location has reported results
        names = {c.id: c for c in plan.published}
        elsewhere = [
            {"id": cid, "name": names[cid].name, "country": names[cid].country, "works_in": labels}
            for cid, labels in sorted(plan.works_in.items())
        ]
        counts["restricted_confirmed_elsewhere"] = len(elsewhere)
        report["regional"] = {
            "locations": sorted(plan.regional),
            "restricted_confirmed_elsewhere": _cap(elsewhere, cfg.max_listed),
        }
    return report


_TITLES = {
    "new_candidates": "New candidates discovered (not published)",
    "new_published": "New channels published",
    "updated": "Channels updated (metadata or URL)",
    "duplicates_removed": "Duplicates removed",
    "newly_failing": "Newly failing",
    "newly_quarantined": "Newly quarantined",
    "restored": "Restored (verified again after quarantine)",
    "removed": "Removed from publication",
}


def summary_markdown(rep: dict) -> str:
    """Short block appended to reports/verification.md, which the workflow Summary step prints."""
    c = rep["counts"]
    lines = ["", "## Changes since the previous run", ""]
    if not rep["baseline_available"]:
        lines += ["Baseline snapshot created; changes are reported from the next verification run on.", ""]
    else:
        lines += [
            f"Compared with the run at {rep['baseline_reference_time'] or 'n/a'} (UTC).",
            "",
            "| Change | Count |",
            "|---|---:|",
        ]
        lines += [f"| {_TITLES[k]} | {c[k]} |" for k in LIST_KEYS]
        lines.append("")
    lines += [
        f"Published {c['published']} · verified playlist {c['verified_playlist']} · quarantined {c['quarantined']} "
        f"· pending authorization {c['pending_authorization']} · integrity "
        f"{'OK' if rep['integrity']['ok'] else 'FAILED'}. Details: `reports/changes.md`.",
        "",
    ]
    t = rep.get("tiers")
    if t:
        parts = [f"official {t['official']['published']} ({t['official']['verified']} verified)"]
        if t.get("community"):
            cm = t["community"]
            parts.append(f"community {cm['verified']} verified / {cm['untested']} untested")
        if t.get("vod"):
            parts.append(f"free VOD {t['vod']['items']} items")
        lines += ["Tiers: " + " · ".join(parts) + ".", ""]
    if "regional" in rep:
        lines += [
            f"Restricted channels confirmed working elsewhere: {c['restricted_confirmed_elsewhere']} "
            f"(locations: {', '.join(rep['regional']['locations'])}).",
            "",
        ]
    if rep["attention"]:
        lines += ["**Needs attention:**", ""] + [f"- {a}" for a in rep["attention"]] + [""]
    return "\n".join(lines)


def _tier_lines(tiers: dict | None) -> list[str]:
    """The three tiers side by side (official, community verified / untested, free VOD)."""
    if not tiers:
        return []
    o, c, v = tiers["official"], tiers.get("community"), tiers.get("vod")
    lines = [
        "",
        "## Tiers",
        "",
        "Tiers are published separately. Community streams are not limited to the broadcaster's own hosts, and "
        "*untested* ones have not been confirmed working.",
        "",
        "| Tier | Published | Verified | Not verified |",
        "|---|---:|---:|---:|",
        f"| Official | {o['published']} | {o['verified']} | {o['not_verified']} |",
    ]
    if c:
        lines += [
            f"| Community: verified | {c['verified']} | {c['verified']} | 0 |",
            f"| Community: untested | {c['untested']} | 0 | {c['untested']} |",
        ]
    else:
        lines.append("| Community | not built yet | n/a | n/a |")
    lines.append(
        f"| Free VOD (items) | {v['items']} | n/a | n/a |" if v else "| Free VOD | not built yet | n/a | n/a |"
    )
    if c:
        lines += [
            "",
            f"Community catalogue: {c['catalog_streams']} streams (built {c['catalog_built_at']}); never checked: "
            f"{c['never_checked']}; held back after a failed check: {c['held_back_after_failed_check']}; verified means "
            f"worked at the latest check within {c['verified_days']} days.",
        ]
    return lines


def to_markdown(rep: dict, rows: int = 25) -> str:
    c = rep["counts"]
    lines = [
        "# Daily change report",
        "",
        "<!-- Generated by scripts/generate.py; do not edit by hand. -->",
        "",
        f"- Verification reference time: {rep['reference_time'] or 'no verification run yet'}",
        f"- Compared with: {rep['baseline_reference_time'] or ('first snapshot' if not rep['baseline_available'] else 'n/a')}",
        f"- {rep['note']}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Published channels | {c['published']} |",
        f"| In verified playlist | {c['verified_playlist']} |",
        f"| Quarantined | {c['quarantined']} |",
        f"| Excluded approved records | {c['excluded']} |",
        f"| Pending authorization | {c['pending_authorization']} |",
    ]
    if rep["baseline_available"]:
        lines += [f"| {_TITLES[k]} | {c[k]} |" for k in LIST_KEYS]
    if "regional" in rep:
        lines += [f"| Restricted channels confirmed working elsewhere | {c['restricted_confirmed_elsewhere']} |"]
    lines += _tier_lines(rep.get("tiers"))
    lines += ["", "## Lifecycle of published channels", "", "| State | Channels |", "|---|---:|"]
    lines += [f"| {k} | {v} |" for k, v in rep["lifecycle_counts"].items()]
    lines += ["", "## Integrity", ""]
    i = rep["integrity"]
    lines += [
        f"- Status: **{'OK' if i['ok'] else 'FAILED'}**",
        f"- Record validation errors: {i['record_errors']}",
        f"- Playlist index matches files: {'yes' if i['playlist_index_matches_files'] else 'NO'}",
        f"- Published streams unique: {'yes' if i['published_streams_unique'] else 'NO'}",
        f"- {i['note']}",
        "",
        "## Needs attention",
        "",
    ]
    lines += [f"- {a}" for a in rep["attention"]] or ["Nothing."]
    if rep["discovery"]:
        lines += ["", "## Discovery (latest catalogue refresh)", "", "| Outcome | Count |", "|---|---:|"]
        lines += [f"| {k} | {v} |" for k, v in sorted(rep["discovery"].items())]
    if "regional" in rep:
        total = rep["counts"]["restricted_confirmed_elsewhere"]
        lines += [
            "",
            f"## Restricted channels confirmed working elsewhere ({total})",
            "",
            "Restricted from the main checker's location (lifecycle stays `restricted`, not in `verified.m3u`), but "
            "verified working from the named location in the last 48 hours.",
            "",
        ]
        if total:
            lines += ["| Channel | Country | Works in |", "|---|---|---|"]
            for it in rep["regional"]["restricted_confirmed_elsewhere"][:rows]:
                lines.append(f"| {it['name']} (`{it['id']}`) | {it['country']} | {', '.join(it['works_in'])} |")
            if total > rows:
                lines.append(f"\n{total - rows} more in `reports/changes.json`.")
        else:
            lines.append("None at the moment.")
    for key in LIST_KEYS:
        items = rep["lists"][key]
        if not items:
            continue
        total = c[key]
        lines += ["", f"## {_TITLES[key]} ({total})", "", "| Channel | Country | Detail |", "|---|---|---|"]
        for it in items[:rows]:
            detail = ", ".join(
                f"{k}: {v}" for k, v in it.items() if k not in ("id", "name", "country") and v not in (None, "", [])
            )
            lines.append(f"| {it['name'] or it['id']} (`{it['id']}`) | {it['country']} | {detail.replace('|', '/')} |")
        if total > rows:
            lines.append(f"\n{total - rows} more in `reports/changes.json`.")
    return "\n".join(lines) + "\n"


def update_history(path: Path, rep: dict, cfg: ChangesConfig) -> bool:
    """Keep one summary per reference date (latest run of the day wins), newest ``history_days`` entries."""
    ref = rep["reference_time"]
    if not ref:
        return False
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        days = raw.get("days", [])
    except (OSError, ValueError):
        days = []
    entry = {
        "date": ref[:10],
        "reference_time": ref,
        "counts": rep["counts"],
        "lifecycle_counts": rep["lifecycle_counts"],
        "integrity_ok": rep["integrity"]["ok"],
        "attention": rep["attention"],
    }
    days = [d for d in days if d.get("date") != entry["date"]] + [entry]
    days = sorted(days, key=lambda d: d["date"])[-cfg.history_days :]
    return write_json_if_changed(path, {"schema": 1, "days": days})
