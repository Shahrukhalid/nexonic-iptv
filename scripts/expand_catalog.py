#!/usr/bin/env python3
"""Automated catalogue expansion under strict, documented rules (see docs/SOURCE_POLICY.md §5).

Reads iptv-org/iptv stream playlists, the iptv-org/database CSVs (public domain) and, optionally, other M3U lists,
and admits a stream ONLY when every rule holds:

1. The stream host belongs to the broadcaster: its registrable domain (or second-level label) equals that of the
   channel's official website in iptv-org/database, or the host is a CDN hostname whose first label contains the
   broadcaster's domain label (e.g. ``cdn-euronews.akamaized.net`` for euronews.com).
2. The URL passes Nexonic's URL policy (https/http, no IP hosts, no tokens, no credentials, no restream hosts).
3. No special headers are required (no ``http-referrer``/``http-user-agent``/``#EXTVLCOPT``).
4. The channel is not NSFW, not blocklisted (nsfw or dmca), not closed, and not a shopping or religious channel.
5. Nexonic's adult-content screening returns PASS (QUARANTINE goes to data/pending/, REJECT is dropped).

Admitted records are written to ``data/approved/auto/<cc>.yaml`` with ``source.method: automated-domain-match``.
The generator publishes an automated record only after it has passed at least one live check (``VERIFIED_WORKING``),
so nothing reaches a playlist on the strength of this script alone.

    python scripts/expand_catalog.py --streams DIR --database DIR [--extra-m3u FILE ...]
    python scripts/expand_catalog.py            # no paths: downloads the iptv-org data over HTTPS (retries, backoff)

Without both ``--streams`` and ``--database`` the M3U files listed under ``[[discovery.extra_m3u]]`` in
config/pipeline.toml are downloaded too (https, allowed hosts, retries, size cap) and treated exactly like
``--extra-m3u`` inputs: same rules, no exceptions. Sources are read in a fixed order (iptv-org, ``--extra-m3u`` files,
configured sources in file order); for one channel the first source that offers an admissible stream wins, and
duplicates (same normalised URL or same channel identity) are never admitted twice. ``source.reference_url`` points at
the exact file the stream was read from.

Re-running on unchanged input rewrites nothing: records keep their ``first_discovered`` / ``reviewed_at`` dates, files
are only written when their content changes, and ordering is stable. A summary of each run (no timestamps) is kept
in state/discovery.json for the daily change report.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml

import _bootstrap  # noqa: F401

from nexonic.config import load_pipeline
from nexonic.dedup import stream_key
from nexonic.fetch import ExtraPlaylist, FetchError, fetch_extra_m3u, fetch_iptv_org
from nexonic.iptvorg import (  # noqa: F401 - the names are re-exported for tests and callers of this script
    CATEGORY_MAP,
    EXCLUDED_CATEGORIES,
    EXCLUDED_NAME_TERMS,
    ISO3_TO_1,
    PAID_HOST_PATTERNS,
    PAID_NAME_TERMS,
    SANCTIONED_COUNTRIES,
    SANCTIONED_NAME_TERMS,
    SANCTIONED_OWNER_TERMS,
    SPECIAL_OPTION_PREFIXES,
    parse_streams,
    resolution_rank,
    slug,
)
from nexonic.models import Channel
from nexonic.moderation import Decision, screen
from nexonic.records import DATA, STATE, load_records
from nexonic.reference import LANGUAGES, countries
from nexonic.safety import check_url_policy

MULTI_SUFFIXES = {
    s
    for s in (
        "co.uk org.uk gov.uk ac.uk me.uk com.br gov.br leg.br org.br net.br tv.br jus.br com.ar gob.ar gov.ar "
        "tur.ar com.mx gob.mx org.mx com.au net.au gov.au org.au co.nz govt.nz org.nz co.jp or.jp ne.jp go.jp "
        "co.kr or.kr go.kr com.tr gov.tr net.tr org.tr gen.tr tv.tr co.in gov.in nic.in org.in co.id go.id or.id "
        "com.cn gov.cn cn.com com.tw gov.tw org.tw com.hk gov.hk org.hk com.sg gov.sg com.my gov.my com.ph gov.ph "
        "com.pk gov.pk com.eg gov.eg com.sa gov.sa co.za gov.za org.za co.il gov.il org.il com.co gov.co com.pe "
        "gob.pe com.ve gob.ve com.ec gob.ec com.uy gub.uy com.py gov.py com.bo gob.bo com.do gob.do com.gt gob.gt "
        "com.ni gob.ni com.sv gob.sv com.hn gob.hn com.pa gob.pa com.cu co.cr go.cr com.ua gov.ua org.ua com.pl "
        "gov.pl com.gr gov.gr com.cy com.mt co.ke go.ke co.tz go.tz co.ug go.ug com.ng gov.ng com.gh gov.gh co.ma "
        "gov.ma com.tn gov.tn com.dz gov.dz com.lb gov.lb com.jo gov.jo com.kw gov.kw com.qa gov.qa com.bh gov.bh "
        "com.om gov.om ac.ir co.ir gov.ir org.ir com.af gov.af com.bd gov.bd com.np gov.np com.lk gov.lk com.vn "
        "gov.vn co.th go.th or.th in.th com.kh gov.kh com.mm gov.mm com.la gov.la com.ru com.ua com.kz gov.kz "
        "com.az gov.az com.ge gov.ge com.am com.mk gov.mk com.al gov.al co.rs gov.rs com.hr com.ba gov.ba co.me "
        "com.ro com.ly gov.ly com.sy gov.sy com.iq gov.iq com.ye com.sd com.et gov.et co.zw gov.zw co.zm gov.zm "
        "co.mz gov.mz co.ao gov.ao co.bw gov.bw com.na gov.na com.mu govmu.org com.fj gov.fj com.pg gov.pg "
        "com.jm gov.jm co.tt gov.tt com.bs gov.bs com.bb gov.bb com.ht gouv.ht com.pr gouv.fr gouv.ci gouv.sn "
        "ac.id sch.id web.id com.vc com.lc com.gy gov.gy com.sr com.bz edu.mx edu.br edu.pe"
    ).split()
}
SHARED_CDN_SUFFIXES = (
    "akamaized.net",
    "akamaihd.net",
    "edgesuite.net",
    "edgekey.net",
    "akamai.net",
    "llnwi.net",
    "llnwd.net",
    "b-cdn.net",
    "cdn77.org",
    "fastly.net",
    "azureedge.net",
)
AGGREGATOR_HOSTS = re.compile(
    r"(pluto\.tv|samsung|wurl|amagi\.tv|mediatailor|rakuten|plex\.tv|roku|xumo|tubi|stirr|distro\.tv|"
    r"dai\.google\.com|vizio|tcl|klowdtv|frequency\.com|glewed|sofast|vegasplus)",
    re.I,
)


def registrable(host: str) -> str:
    parts = host.lower().rstrip(".").split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in MULTI_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def sld(domain: str) -> str:
    return domain.split(".")[0]


def owner_match(stream_host: str, website: str) -> str | None:
    """Return a short explanation when the stream host belongs to the website's owner, else None."""
    wh = (urlsplit(website).hostname or "").lower()
    if not wh:
        return None
    sreg, wreg = registrable(stream_host), registrable(wh)
    if sreg == wreg:
        return f"stream host {stream_host} is on the broadcaster's domain {wreg}"
    label = sld(wreg)
    if len(label) >= 4 and sld(sreg) == label:
        return f"stream host {stream_host} ({sreg}) shares the broadcaster's domain name '{label}' ({wreg})"
    if len(label) >= 5 and stream_host.endswith(SHARED_CDN_SUFFIXES):
        first = stream_host.split(".")[0]
        if label in first.replace("-", ""):
            return f"CDN hostname {stream_host} is named for the broadcaster's domain '{label}' ({wreg})"
    return None


@dataclass(frozen=True)
class Playlist:
    """One M3U input. ``priority`` orders the sources: a lower number is seen first and wins for the same channel."""

    path: Path
    source: str
    reference_url: str
    priority: int


def _iptv_org_reference(name: str) -> str:
    return f"https://github.com/iptv-org/iptv/blob/master/streams/{name}"


def _reviewed_quarantine(path: Path) -> list[dict]:
    """Quarantined records a maintainer has annotated ("Quarantine reviewed: ...") stay in the file untouched.

    They are loaded as "existing" records (their notes no longer start with "Quarantined"), so a fresh run would
    otherwise never regenerate them and would drop the review notes together with the file.
    """
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [
        r
        for r in data.get("channels", [])
        if str((r.get("review") or {}).get("notes", "")).startswith("Quarantine reviewed")
    ]


def _write_if_changed(path: Path, text: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def _undated(ch: Channel) -> dict:
    d = ch.model_dump(mode="json")
    d.pop("first_discovered", None)
    d["review"].pop("reviewed_at", None)
    return d


def _stabilise(rec: dict, prior: Channel | None) -> None:
    """Keep the dates of an unchanged record so that re-running discovery produces no diff."""
    if prior is None:
        return
    rec["first_discovered"] = prior.first_discovered.isoformat()
    try:
        same = _undated(Channel.model_validate(rec)) == _undated(prior)
    except Exception:  # noqa: BLE001 - an invalid record is reported by the caller
        return
    if same:
        rec["review"]["reviewed_at"] = prior.review.reviewed_at.isoformat()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--streams", type=Path, help="directory with iptv-org/iptv streams/*.m3u (default: download)")
    ap.add_argument("--database", type=Path, help="directory with iptv-org/database data/*.csv (default: download)")
    ap.add_argument("--extra-m3u", type=Path, nargs="*", default=[], help="other M3U lists (tvg-id must match)")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument(
        "--no-extra-sources",
        action="store_true",
        help="do not download the [[discovery.extra_m3u]] playlists (they are only downloaded when the iptv-org data is)",
    )
    args = ap.parse_args(argv)
    if args.streams and args.database:
        return run(args, args.streams, args.database)
    cfg = load_pipeline().discovery
    need = tuple(n for n, given in (("iptv", args.streams), ("database", args.database)) if not given)
    with tempfile.TemporaryDirectory() as tmp:
        extras: list[ExtraPlaylist] = []
        try:
            got = fetch_iptv_org(cfg, Path(tmp), need)
            if not args.no_extra_sources and cfg.extra_m3u:
                missing: list[str] = []
                extras = fetch_extra_m3u(cfg, Path(tmp), missing=missing)
                for label in missing:
                    print(f"warning: {label} no longer exists upstream; skipped", file=sys.stderr)
        except FetchError as exc:
            print(f"Could not download the discovery sources: {exc}", file=sys.stderr)
            return 1
        return run(args, args.streams or got["streams"], args.database or got["database"], extras)


def run(args, streams_dir: Path, database_dir: Path, extras: list[ExtraPlaylist] = ()) -> int:
    db = database_dir
    channels = {r["id"]: r for r in csv.DictReader((db / "channels.csv").open(encoding="utf-8"))}
    feeds = {(r["channel"], r["id"]): r for r in csv.DictReader((db / "feeds.csv").open(encoding="utf-8"))}
    main_feed = {r["channel"]: r for r in feeds.values() if r["is_main"] == "TRUE"}
    blocked = {r["channel"] for r in csv.DictReader((db / "blocklist.csv").open(encoding="utf-8"))}

    # The script regenerates data/approved/auto/ from scratch, so its own previous output is ignored here.
    loaded = load_records(DATA).all()
    prior_auto = {c.id: c for c in loaded if c.automated and c.review.status.value == "approved"}
    prior_quarantine = {
        c.id: c for c in loaded if c.review.status.value == "pending" and c.review.notes[:11] == "Quarantined"
    }
    existing = [c for c in loaded if not c.automated or c.review.status.value != "approved"]
    existing = [c for c in existing if c.review.notes[:11] != "Quarantined"]
    known_urls = {stream_key(c.stream.url) for c in existing}
    known_epg = {(c.epg_id or "").split("@")[0] for c in existing if c.epg_id}
    known_ids = {c.id for c in existing}
    known_names = {(c.country, c.name.casefold()) for c in existing}

    sources = [Playlist(p, "iptv-org", _iptv_org_reference(p.name), 0) for p in sorted(streams_dir.glob("*.m3u"))]
    sources += [Playlist(p, "local", _iptv_org_reference(p.name), 1) for p in args.extra_m3u]
    order = {}
    for ex in extras:
        order.setdefault(ex.source, len(order) + 2)
        sources.append(Playlist(ex.path, ex.source, ex.reference_url, order[ex.source]))
    candidates: dict[str, list] = defaultdict(list)
    stats = defaultdict(int)
    per_source: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def bump(source: str, key: str) -> None:
        stats[key] += 1
        per_source[source][key] += 1

    for src in sources:
        for attrs, title, url, opts in parse_streams(src.path):
            bump(src.source, "streams")
            tvg = attrs.get("tvg-id", "")
            cid, _, feed = tvg.partition("@")
            ch = channels.get(cid)
            if not ch:
                bump(src.source, "no-database-entry")
                continue
            if cid in known_epg:
                bump(src.source, "already-curated")
                continue
            if ch["is_nsfw"] == "TRUE" or cid in blocked:
                bump(src.source, "nsfw-or-blocklisted")
                continue
            if ch["closed"]:
                bump(src.source, "closed")
                continue
            owners = f"{ch['owners']} {ch['network']}".lower()
            lname = ch["name"].lower()
            if (
                ch["country"].lower() in SANCTIONED_COUNTRIES
                or any(t in owners for t in SANCTIONED_OWNER_TERMS)
                or any(re.search(rf"(^|\W){re.escape(t)}(\W|$)", lname) for t in SANCTIONED_NAME_TERMS)
            ):
                bump(src.source, "sanctions-exclusion")
                continue
            if any(t in lname for t in EXCLUDED_NAME_TERMS):
                bump(src.source, "excluded-category")
                continue
            if any(t in lname for t in PAID_NAME_TERMS):
                bump(src.source, "subscription-service")
                continue
            cats = [c for c in ch["categories"].split(";") if c]
            if set(cats) & EXCLUDED_CATEGORIES:
                bump(src.source, "excluded-category")
                continue
            if (
                any(k in attrs for k in ("http-referrer", "http-user-agent"))
                or any(o.startswith(SPECIAL_OPTION_PREFIXES) for o in opts)
                or "|" in url  # Kodi-style "url|Header=value"
            ):
                bump(src.source, "needs-special-headers")
                continue
            pol = check_url_policy(url)
            if not pol.ok:
                bump(src.source, "url-policy")
                continue
            host = (urlsplit(url).hostname or "").lower()
            if PAID_HOST_PATTERNS.search(host):
                bump(src.source, "subscription-service")
                continue
            if AGGREGATOR_HOSTS.search(host):
                bump(src.source, "aggregator-host")
                continue
            why = owner_match(host, ch["website"]) if ch["website"] else None
            if not why:
                bump(src.source, "host-not-owned-by-broadcaster")
                continue
            candidates[cid].append((feed, title, url, why, src))

    cn = countries()
    out_records: dict[str, list] = defaultdict(list)
    pending: list = []
    used_ids = set(known_ids)
    for cid, items in sorted(candidates.items()):
        ch = channels[cid]
        country = ch["country"].lower()
        if country not in cn:
            bump(items[0][4].source, "unknown-country")
            continue
        mf = main_feed.get(cid, {}).get("id")

        def rank(item, mf=mf):
            feed, title, url, _, src = item
            return (
                -src.priority,  # first-seen source wins
                feed == mf,
                url.startswith("https"),
                "Not 24/7" not in title,
                "Geo-blocked" not in title,
                resolution_rank(title),
            )

        best = max(items, key=rank)
        feed, title, url, why, src = best
        for other in items:
            if other[4].source != src.source:
                bump(other[4].source, "duplicate-channel-in-other-source")
        if stream_key(url) in known_urls or (country, ch["name"].casefold()) in known_names:
            bump(src.source, "duplicate-of-existing")
            continue
        known_names.add((country, ch["name"].casefold()))
        known_urls.add(stream_key(url))
        f = feeds.get((cid, feed)) or main_feed.get(cid) or {}
        langs = []
        for code in (f.get("languages") or "").split(";"):
            two = ISO3_TO_1.get(code)
            if two and two in LANGUAGES and two not in langs:
                langs.append(two)
        if not langs:
            bump(src.source, "language-not-supported")
            continue
        cats = []
        for c in ch["categories"].split(";"):
            m = CATEGORY_MAP.get(c)
            if m and m not in cats:
                cats.append(m)
        cats = cats or ["general"]
        base = slug(f"{ch['name']}-{country}")
        rid, n = base, 2
        while rid in used_ids:
            rid, n = f"{base}-{n}", n + 1
        used_ids.add(rid)
        geo_blocked = "Geo-blocked" in title
        epg = f"{cid}@{feed}" if feed else cid
        rec = {
            "id": rid,
            "name": ch["name"],
            "alt_names": [a for a in ch["alt_names"].split(";") if a][:5],
            "broadcaster": (ch["owners"].split(";")[0] or ch["network"] or ch["name"]).strip(),
            "country": country,
            "languages": langs,
            "categories": cats,
            "website": ch["website"],
            "stream": {"url": url, "protocol": "dash" if ".mpd" in url.split("?")[0] else "hls", "quality": "unknown"},
            "source": {
                "reference_url": src.reference_url,
                "evidence_url": ch["website"],
                "evidence_summary": f"Automated owner-domain match: {why}. Channel metadata from iptv-org/database.",
                "evidence_checked": None,
                "notes": "Not 24/7 according to iptv-org." if "Not 24/7" in title else "",
                "method": "automated-domain-match",
            },
            "epg_id": epg,
            "logo": None,
            "geo": {"restricted": True if geo_blocked else "unknown", "regions": [country] if geo_blocked else []},
            "is_nsfw": False,
            "first_discovered": args.date,
            "review": {
                "status": "approved",
                "reviewer": "automated (scripts/expand_catalog.py); not individually human-reviewed",
                "reviewed_at": args.date,
                "authorization_basis": "official-broadcaster-stream",
                "adult_screening": "pass",
                "notes": "Published only after passing a live check.",
                "rejection_reason": "",
            },
        }
        try:
            model = Channel.model_validate(rec)
        except Exception as exc:  # schema problems (e.g. invalid website) -> skip honestly
            bump(src.source, "schema-invalid")
            print(f"skip {rid}: {exc}".splitlines()[0], file=sys.stderr)
            continue
        res = screen(model)
        if res.decision is Decision.REJECT:
            bump(src.source, "moderation-reject")
            continue
        if res.decision is Decision.QUARANTINE:
            rec["review"].update(
                status="pending",
                authorization_basis="none",
                adult_screening="uncertain",
                notes="Quarantined by moderation: " + "; ".join(res.reasons),
            )
            _stabilise(rec, prior_quarantine.get(rid))
            pending.append(rec)
            bump(src.source, "moderation-quarantine")
            continue
        _stabilise(rec, prior_auto.get(rid))
        out_records[country].append(rec)
        bump(src.source, "admitted")

    auto_dir = DATA / "approved" / "auto"
    auto_dir.mkdir(parents=True, exist_ok=True)
    header = (
        "# Automatically admitted channels (scripts/expand_catalog.py). Published only after a successful live\n"
        "# check. Edit by moving a record to data/approved/<cc>.yaml (human-reviewed) or data/rejected/.\n"
    )
    for cc, recs in sorted(out_records.items()):
        recs.sort(key=lambda r: (r["name"].casefold(), r["id"]))
        _write_if_changed(
            auto_dir / f"{cc}.yaml",
            header + yaml.safe_dump({"channels": recs}, sort_keys=False, allow_unicode=True, width=120),
        )
    for old in auto_dir.glob("*.yaml"):
        if old.stem not in out_records:
            old.unlink()
    qpath = DATA / "pending" / "auto-quarantine.yaml"
    kept = _reviewed_quarantine(qpath)
    pending = kept + [r for r in pending if r["id"] not in {k["id"] for k in kept}]
    if pending:
        _write_if_changed(
            qpath,
            "# Automated candidates quarantined by moderation. Never published.\n"
            + yaml.safe_dump({"channels": pending}, sort_keys=False, allow_unicode=True, width=120),
        )
    elif qpath.exists():
        qpath.unlink()
    summary = {
        "schema": 1,
        "stats": dict(sorted(stats.items())),
        "sources": {name: dict(sorted(c.items())) for name, c in sorted(per_source.items())},
        "countries_with_admitted_channels": len(out_records),
    }
    _write_if_changed(STATE / "discovery.json", json.dumps(summary, indent=1, sort_keys=True) + "\n")
    for k, v in sorted(stats.items()):
        print(f"{k:32} {v}")
    print(f"countries with admitted channels: {len(out_records)}")
    if len(per_source) > 1:
        print("\nper source: entries read / admitted / quarantined")
        for name, c in sorted(per_source.items()):
            print(f"{name:32} {c['streams']:7} {c.get('admitted', 0):7} {c.get('moderation-quarantine', 0):7}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
