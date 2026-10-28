"""Deterministic playlist generation.

Inputs: approved records, moderation, verification history. Outputs are a pure function of those inputs: sorting is
stable, no wall-clock time is written, and the freshness reference is the time of the latest verification run.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import config, health, lifecycle, m3u
from . import regional as regional_mod
from .config import QuarantineConfig
from .dedup import identity_key, stream_key
from .lifecycle import LifecycleInfo
from .models import Channel
from .moderation import publication_gate
from .quality import BUCKET_LABELS, QUALITY_BUCKETS, measured_height, quality_bucket
from .records import ROOT, LoadResult
from .reference import CATEGORIES, LANGUAGES, countries
from .status import CheckResult, Status
from .timeutil import iso, parse_iso

PLAYLISTS = ROOT / "playlists"
REPORTS = ROOT / "reports"


@dataclass
class Plan:
    reference: dt.datetime | None
    published: list[Channel] = field(default_factory=list)
    excluded: list[dict] = field(default_factory=list)
    verified_ids: set[str] = field(default_factory=set)
    files: dict[str, str] = field(default_factory=dict)  # rel path -> content
    index: list[dict] = field(default_factory=list)
    health: dict[str, health.Health] = field(default_factory=dict)
    lifecycle: dict[str, LifecycleInfo] = field(default_factory=dict)
    last_metadata_update: dict[str, str] = field(default_factory=dict)  # channel id -> date, set by the caller
    works_in: dict[str, list[str]] = field(default_factory=dict)  # restricted channel id -> locations it works from
    regional: dict[str, dict] = field(default_factory=dict)  # location label -> {"checked": n, "last_checked": ts}
    quality: dict[str, str] = field(default_factory=dict)  # published channel id -> measured quality bucket
    tiers: dict[str, dict] = field(default_factory=dict)  # "community" / "vod" -> statistics, set by ``extend``


def reference_time(history: dict[str, list[CheckResult]], ids: set[str]) -> dt.datetime | None:
    stamps = [r.checked_at for cid in ids for r in history.get(cid, []) if r.status.value != "NOT_TESTED"]
    return parse_iso(max(stamps)) if stamps else None


def sort_key(ch: Channel) -> tuple:
    return (ch.country, ch.name.casefold(), ch.id)


def entry_for(ch: Channel, group: str) -> m3u.Entry:
    attrs = {
        "tvg-id": ch.epg_id or "",
        "tvg-name": ch.name,
        "tvg-country": ch.country.upper(),
        "tvg-language": ";".join(LANGUAGES[lang] for lang in ch.languages),
        "tvg-logo": ch.logo or "",
        "group-title": group,
    }
    return m3u.Entry(title=ch.name, url=ch.stream.url, attrs=attrs)


def _render(channels: list[Channel], group_fn, title: str) -> str:
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    entries = []
    for ch in sorted(channels, key=sort_key):
        u = stream_key(ch.stream.url)
        if ch.id in seen_ids or u in seen_urls:
            continue  # duplicates within one playlist are never written
        seen_ids.add(ch.id)
        seen_urls.add(u)
        entries.append(entry_for(ch, group_fn(ch)))
    return m3u.render(entries, {"x-nexonic-playlist": title})


def plan(
    records: LoadResult,
    history: dict[str, list[CheckResult]],
    quarantine: QuarantineConfig | None = None,
    previous_restored: dict[str, str] | None = None,
    regional: dict[str, dict[str, list[CheckResult]]] | None = None,
) -> Plan:
    quarantine = quarantine or config.load_pipeline().quarantine
    previous_restored = previous_restored or {}
    approved = records.approved
    ref = reference_time(history, {c.id for c in approved})
    p = Plan(reference=ref)
    cnames = countries()

    seen_streams: dict[str, str] = {}
    seen_idents: dict[tuple[str, str], str] = {}
    # Curated records win over automated ones when two records describe the same stream or channel.
    for ch in sorted(approved, key=lambda c: (c.automated, *sort_key(c))):
        ok, problems = publication_gate(ch)
        results = history.get(ch.id, [])
        p.health[ch.id] = health.compute(results, ref)
        info = lifecycle.evaluate(results, ref, quarantine, previous_restored.get(ch.id))
        p.lifecycle[ch.id] = info
        if ok and health.is_stale(results, ref):
            ok, problems = False, ["stale: failed its last 3+ checks and has not worked for 7+ days"]
        if ok and ch.automated and not any(r.status is Status.VERIFIED_WORKING for r in results):
            ok, problems = False, ["automated record awaiting its first successful live check"]
        skey, ikey = stream_key(ch.stream.url), identity_key(ch)
        if ok and skey in seen_streams:
            ok, problems = False, [f"duplicate stream URL of {seen_streams[skey]}"]
        elif ok and ikey in seen_idents:
            ok, problems = False, [f"duplicate channel identity of {seen_idents[ikey]}"]
        if not ok:
            p.excluded.append({"id": ch.id, "name": ch.name, "reasons": problems, "lifecycle": info.state.value})
            continue
        seen_streams[skey] = ch.id
        seen_idents[ikey] = ch.id
        p.published.append(ch)
        if lifecycle.in_verified(results, ref, quarantine):
            p.verified_ids.add(ch.id)
    order = {c.id: sort_key(c) for c in approved}
    p.excluded.sort(key=lambda e: order[e["id"]])
    p.published.sort(key=sort_key)

    def country_group(c: Channel) -> str:
        return cnames[c.country]["name"]

    def category_group(c: Channel) -> str:
        return CATEGORIES[c.primary_category]

    def add(rel: str, kind: str, key: str, name: str, chans: list[Channel], group_fn) -> None:
        if not chans:
            return  # never write empty or misleading files
        p.files[rel] = _render(chans, group_fn, name)
        p.index.append(
            {
                "path": rel,
                "kind": kind,
                "key": key,
                "name": name,
                "count": len(chans),
                "url": config.playlist_url(rel),
                "tier": "official",
            }
        )

    pub = p.published
    add("playlists/all.m3u", "global", "all", "All channels", pub, country_group)
    add(
        "playlists/verified.m3u",
        "verified",
        "verified",
        "Nexonic Verified (working in the last 48 h)",
        [c for c in pub if c.id in p.verified_ids],
        country_group,
    )
    working = regional_mod.working_from(regional or {}, ref)
    for label, by_id in sorted((regional or {}).items()):
        stamps = [r.checked_at for results in by_id.values() for r in results if r.status is not Status.NOT_TESTED]
        p.regional[label] = {"channels_checked": len(by_id), "last_checked": max(stamps) if stamps else None}
    for ch in pub:
        labels = sorted(lb for lb, ids in working.items() if ch.id in ids)
        if labels and p.lifecycle[ch.id].state is lifecycle.Lifecycle.RESTRICTED:
            p.works_in[ch.id] = labels
    for label in sorted(working):
        add(
            f"playlists/regions/{label}.m3u",
            "region",
            label,
            f"Verified working from {label} (last 48 h)",
            [c for c in pub if c.id in working[label]],
            country_group,
        )
    for code in sorted({c.country for c in pub}):
        add(
            f"playlists/countries/{code}.m3u",
            "country",
            code,
            cnames[code]["name"],
            [c for c in pub if c.country == code],
            category_group,
        )
    for lang in sorted({lg for c in pub for lg in c.languages}):
        add(
            f"playlists/languages/{lang}.m3u",
            "language",
            lang,
            LANGUAGES[lang],
            [c for c in pub if lang in c.languages],
            country_group,
        )
    for cat in sorted({ct for c in pub for ct in c.categories}):
        add(
            f"playlists/categories/{cat}.m3u",
            "category",
            cat,
            CATEGORIES[cat],
            [c for c in pub if cat in c.categories],
            country_group,
        )
    for c in pub:
        bucket = quality_bucket(measured_height(history.get(c.id, [])))
        if bucket:
            p.quality[c.id] = bucket
    for bucket in QUALITY_BUCKETS:
        add(
            f"playlists/quality/{bucket}.m3u",
            "quality",
            bucket,
            f"Measured {BUCKET_LABELS[bucket]}",
            [c for c in pub if p.quality.get(c.id) == bucket],
            country_group,
        )
    return p


def extend(p: Plan, name: str, files: dict[str, str], index: list[dict], stats: dict) -> None:
    """Add the playlists of another tier (community, free VOD) to the plan. Official outputs are never touched."""
    clash = sorted(set(files) & set(p.files))
    if clash:
        raise ValueError(f"tier {name!r} would overwrite other playlists: {clash[:3]}")
    p.files.update(files)
    p.index.extend(index)
    if stats:
        p.tiers[name] = stats


def channel_export(p: Plan) -> list[dict]:
    cnames = countries()
    out = []
    for ch in sorted(p.published, key=sort_key):
        h = p.health[ch.id]
        info = p.lifecycle[ch.id]
        entry = {
            "id": ch.id,
            "name": ch.name,
            "broadcaster": ch.broadcaster,
            "country": ch.country,
            "country_name": cnames[ch.country]["name"],
            "flag": cnames[ch.country]["flag"],
            "languages": ch.languages,
            "language_names": [LANGUAGES[x] for x in ch.languages],
            "categories": ch.categories,
            "website": ch.website,
            "stream_url": ch.stream.url,
            "protocol": ch.stream.protocol,
            "epg_id": ch.epg_id,
            "geo_restricted": ch.geo.restricted,
            "geo_regions": ch.geo.regions,
            "evidence_url": ch.source.evidence_url,
            "authorization_basis": ch.review.authorization_basis.value,
            "admission": "automated" if ch.automated else "curated",
            "in_verified_playlist": ch.id in p.verified_ids,
            "quality": p.quality.get(ch.id),
            "health": h.to_dict(),
            "lifecycle": info.state.value,
            "quarantined": info.quarantined,
            "restored_at": info.restored_at,
            "last_validated": info.last_validated,
            "last_metadata_update": p.last_metadata_update.get(ch.id, ch.review.reviewed_at.isoformat()),
            "provenance": {
                "source_reference": ch.source.reference_url,
                "evidence_url": ch.source.evidence_url,
                "evidence_summary": ch.source.evidence_summary,
                "evidence_checked": ch.source.evidence_checked.isoformat() if ch.source.evidence_checked else None,
                "discovery_method": ch.source.method,
                "first_discovered": ch.first_discovered.isoformat(),
                "authorization_basis": ch.review.authorization_basis.value,
                "reviewed_at": ch.review.reviewed_at.isoformat(),
            },
        }
        if ch.id in p.works_in:
            entry["works_in"] = p.works_in[ch.id]  # restricted from the primary location, verified from these
        out.append(entry)
    return out


def write(p: Plan, root: Path = ROOT) -> list[str]:
    """Write playlists and the playlist index; remove playlist files that are no longer generated."""
    written = []
    pl_root = root / "playlists"
    wanted = {root / rel for rel in p.files}
    for rel, content in sorted(p.files.items()):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
        written.append(rel)
    if pl_root.exists():
        for old in sorted(pl_root.rglob("*.m3u")):
            if old not in wanted:
                old.unlink()
    index = {
        "reference_time": iso(p.reference) if p.reference else None,
        "playlists": sorted(p.index, key=lambda x: (_KIND_ORDER[x["kind"]], x["key"])),
    }
    pl_root.mkdir(parents=True, exist_ok=True)
    (pl_root / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (root / "reports").mkdir(exist_ok=True)
    channels = {"reference_time": index["reference_time"], "channels": channel_export(p), "excluded": p.excluded}
    (root / "reports" / "channels.json").write_text(
        json.dumps(channels, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return written


_KIND_ORDER = {
    "global": 0,
    "verified": 1,
    "country": 2,
    "language": 3,
    "category": 4,
    "region": 5,
    "quality": 6,
    "community-verified": 7,
    "community-untested": 8,
    "community-country": 9,
    "community-language": 10,
    "community-category": 11,
    "community-quality": 12,
    "vod-movies": 13,
    "vod-series": 14,
    "vod-genre": 15,
    "vod-decade": 16,
}


def playlists_markdown(p: Plan) -> str:
    cn = countries()
    lines = [
        "# Playlists",
        "",
        "<!-- Generated by scripts/generate.py — do not edit by hand. -->",
        "",
        "Paste any URL below into VLC, Kodi or another IPTV player. Counts come from the generated files. Three tiers "
        "are published and never mixed; read [docs/TIERS.md](docs/TIERS.md) for what each one promises.",
        "",
        f"Freshness reference (latest verification run): **{iso(p.reference) if p.reference else 'no verification run yet'}**",
        "",
    ]
    by_kind: dict[str, list[dict]] = {}
    for item in p.index:
        by_kind.setdefault(item["kind"], []).append(item)
    titles = {
        "global": "Main",
        "verified": "Nexonic Verified",
        "country": "By country",
        "language": "By language",
        "category": "By category",
        "region": "Verified from another location",
        "quality": "By measured quality",
    }
    for kind in ("global", "verified", "country", "language", "category", "region", "quality"):
        items = sorted(by_kind.get(kind, []), key=lambda x: x["key"])
        if not items:
            if kind == "verified":
                lines += [
                    "## Nexonic Verified",
                    "",
                    "Not generated yet: no channel has a successful verification in the last 48 hours.",
                    "",
                ]
            continue
        lines += [f"## {titles[kind]}", ""]
        if kind == "region":
            lines += [
                "Channels that could not be confirmed from the main checker (GitHub-hosted, United States) but passed "
                "a live check from the named location in the last 48 hours. Reachability from that location only.",
                "",
            ]
        if kind == "quality":
            lines += [
                "Official channels grouped by the resolution the checker measured (best variant of the master "
                "playlist, or the probed rendition of a single-rendition stream). Channels without a measurement "
                "are not listed here.",
                "",
            ]
        lines += ["| Playlist | Channels | URL |", "|---|---:|---|"]
        for it in items:
            label = it["name"]
            if kind == "country":
                label = f"{cn[it['key']]['flag']} {label}"
            lines.append(f"| {label} | {it['count']} | `{it['url']}` |")
        lines.append("")

    community_kinds = (
        ("community-verified", "Verified"),
        ("community-untested", "Untested"),
        ("community-country", "By country"),
        ("community-language", "By language"),
        ("community-category", "By category"),
        ("community-quality", "By quality"),
    )
    if any(k in by_kind for k, _ in community_kinds):
        lines += [
            "## Community tier",
            "",
            "Publicly listed free streams from iptv-org/iptv and the other open lists named in "
            "[config/pipeline.toml](config/pipeline.toml), screened and de-duplicated but **not** limited to the "
            "broadcaster's own hosts. Quality varies. *Verified* means the stream worked at its latest check within "
            f"{(p.tiers.get('community') or {}).get('verified_days', 7)} days; *untested* streams have not been "
            "confirmed working and may not play. Removal requests: [docs/TIERS.md](docs/TIERS.md#takedown).",
            "",
        ]
        for kind, title in community_kinds:
            items = sorted(by_kind.get(kind, []), key=lambda x: x["key"])
            if not items:
                continue
            lines += [f"### Community: {title}", ""]
            lines += ["| Playlist | Streams | Verified | Untested | URL |", "|---|---:|---:|---:|---|"]
            for it in items:
                label = it["name"]
                if kind == "community-country":
                    label = f"{cn[it['key']]['flag']} {label}"
                lines.append(
                    f"| {label} | {it['count']} | {it.get('verified', 0)} | {it.get('untested', 0)} | `{it['url']}` |"
                )
            lines.append("")

    vod_kinds = (
        ("vod-movies", "Movies"),
        ("vod-series", "Series"),
        ("vod-genre", "By genre"),
        ("vod-decade", "By decade"),
    )
    if any(k in by_kind for k, _ in vod_kinds):
        lines += [
            "## Free VOD tier",
            "",
            "On-demand films and TV from the Internet Archive that are public domain or carry an open Creative Commons "
            "licence (recorded per item). These are files, not live channels. Removal requests: "
            "[docs/TIERS.md](docs/TIERS.md#takedown).",
            "",
        ]
        for kind, title in vod_kinds:
            items = sorted(by_kind.get(kind, []), key=lambda x: x["key"])
            if not items:
                continue
            lines += [f"### Free VOD: {title}", "", "| Playlist | Items | URL |", "|---|---:|---|"]
            lines += [f"| {it['name']} | {it['count']} | `{it['url']}` |" for it in items]
            lines.append("")
    return "\n".join(lines)


STATS_START = "<!-- nexonic:stats:start -->"
STATS_END = "<!-- nexonic:stats:end -->"


def tier_rows(p: Plan) -> list[str]:
    """README table of the three tiers; numbers come from the plan, never typed by hand."""
    lines = [
        "",
        "| Tier | Streams | Of which verified | Not verified |",
        "|---|---:|---:|---:|",
        f"| Official live channels | {len(p.published)} | {len(p.verified_ids)} | {len(p.published) - len(p.verified_ids)} |",
    ]
    c = p.tiers.get("community")
    if c:
        lines.append(
            f"| Community live streams | {c['verified'] + c['untested']} | {c['verified']} | {c['untested']} (untested) |"
        )
    else:
        lines.append("| Community live streams | not built yet | n/a | n/a |")
    v = p.tiers.get("vod")
    if v:
        lines.append(f"| Free VOD (films and TV, open licences) | {v['items']} | n/a | n/a |")
    else:
        lines.append("| Free VOD (films and TV, open licences) | not built yet | n/a | n/a |")
    return lines


def readme_block(p: Plan, stats: dict) -> str:
    """Numbers for README.md, taken from the generation plan and statistics (never typed by hand)."""
    cn = countries()
    run = stats.get("latest_run")
    counts = stats["latest_run_status_counts"]
    lines = [
        STATS_START,
        "<!-- Generated by scripts/generate.py — do not edit by hand. -->",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Approved channels published | {stats['published_channels']} |",
        f"| Countries | {stats['countries']} |",
        f"| Languages | {stats['languages']} |",
        f"| In `verified.m3u` (last 48 h) | {stats['verified_playlist_channels']} |",
    ]
    if run:
        failing = sum(counts.get(k, 0) for k in ("UNAVAILABLE", "TIMEOUT", "INVALID_STREAM", "AUTH_REQUIRED"))
        lines += [
            f"| Latest run: verified working | {counts.get('VERIFIED_WORKING', 0)} |",
            f"| Latest run: unavailable / failing | {failing} |",
            f"| Latest run: geo-restricted from checker | {counts.get('GEO_RESTRICTED', 0)} |",
            f"| Latest run: unknown / rate-limited / unsupported | "
            f"{counts.get('UNKNOWN', 0) + counts.get('RATE_LIMITED', 0) + counts.get('UNSUPPORTED', 0)} |",
            f"| Latest verification run (UTC) | {run['finished_at']} |",
        ]
    else:
        lines.append("| Latest verification run | none yet — all channels `NOT_TESTED` |")
    lines += tier_rows(p)
    lines += [
        "",
        "**Country playlists:** "
        + " · ".join(
            f"{cn[c]['flag']} [{cn[c]['name']}](playlists/countries/{c}.m3u) ({v['channels']})"
            for c, v in stats["per_country"].items()
        ),
        "",
        STATS_END,
    ]
    return "\n".join(lines)


def update_readme(text: str, block: str) -> str:
    start, end = text.find(STATS_START), text.find(STATS_END)
    if start == -1 or end == -1:
        return text
    return text[:start] + block + text[end + len(STATS_END) :]
