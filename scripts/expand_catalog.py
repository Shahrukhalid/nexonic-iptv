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
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

import yaml

import _bootstrap  # noqa: F401

from nexonic.models import Channel
from nexonic.moderation import Decision, screen
from nexonic.records import DATA, load_records, normalise_url
from nexonic.reference import LANGUAGES, countries
from nexonic.safety import check_url_policy

ISO3_TO_1 = {
    "ara": "ar",
    "ben": "bn",
    "dan": "da",
    "deu": "de",
    "ell": "el",
    "eng": "en",
    "spa": "es",
    "fas": "fa",
    "fin": "fi",
    "fra": "fr",
    "hin": "hi",
    "hun": "hu",
    "ind": "id",
    "ita": "it",
    "jpn": "ja",
    "kor": "ko",
    "kur": "ku",
    "msa": "ms",
    "zsm": "ms",
    "nld": "nl",
    "nor": "no",
    "nob": "no",
    "nno": "no",
    "pol": "pl",
    "por": "pt",
    "rus": "ru",
    "swe": "sv",
    "swa": "sw",
    "tam": "ta",
    "tha": "th",
    "tur": "tr",
    "ukr": "uk",
    "urd": "ur",
    "vie": "vi",
    "zho": "zh",
    "cmn": "zh",
    "yue": "zh",
    "ces": "cs",
    "slk": "sk",
    "slv": "sl",
    "hrv": "hr",
    "srp": "sr",
    "bos": "bs",
    "bul": "bg",
    "ron": "ro",
    "mkd": "mk",
    "sqi": "sq",
    "lit": "lt",
    "lav": "lv",
    "est": "et",
    "isl": "is",
    "cat": "ca",
    "eus": "eu",
    "glg": "gl",
    "gle": "ga",
    "cym": "cy",
    "heb": "he",
    "hye": "hy",
    "kat": "ka",
    "aze": "az",
    "kaz": "kk",
    "uzb": "uz",
    "mon": "mn",
    "pus": "ps",
    "prs": "fa",
    "tgl": "tl",
    "fil": "tl",
    "mal": "ml",
    "tel": "te",
    "kan": "kn",
    "mar": "mr",
    "guj": "gu",
    "pan": "pa",
    "ori": "or",
    "asm": "as",
    "nep": "ne",
    "sin": "si",
    "mya": "my",
    "khm": "km",
    "lao": "lo",
    "amh": "am",
    "som": "so",
    "hau": "ha",
    "yor": "yo",
    "ibo": "ig",
    "zul": "zu",
    "afr": "af",
    "mlt": "mt",
    "ltz": "lb",
    "fao": "fo",
    "kal": "kl",
    "bel": "be",
    "tat": "tt",
    "kir": "ky",
    "tuk": "tk",
    "tgk": "tg",
    "hat": "ht",
    "que": "qu",
    "grn": "gn",
    "aym": "ay",
    "mri": "mi",
    "smo": "sm",
    "ton": "to",
    "fij": "fj",
    "kin": "rw",
    "lug": "lg",
    "wol": "wo",
    "lin": "ln",
    "fry": "fy",
    "bre": "br",
    "cos": "co",
    "roh": "rm",
}
CATEGORY_MAP = {
    "auto": "lifestyle",
    "animation": "kids",
    "business": "business",
    "classic": "entertainment",
    "comedy": "entertainment",
    "cooking": "lifestyle",
    "culture": "culture",
    "documentary": "documentary",
    "education": "education",
    "entertainment": "entertainment",
    "family": "entertainment",
    "general": "general",
    "kids": "kids",
    "legislative": "legislative",
    "lifestyle": "lifestyle",
    "movies": "movies",
    "music": "music",
    "news": "news",
    "outdoor": "lifestyle",
    "public": "general",
    "relax": "lifestyle",
    "science": "science",
    "series": "entertainment",
    "sports": "sports",
    "travel": "lifestyle",
    "weather": "weather",
}
EXCLUDED_CATEGORIES = {"xxx", "shop", "religious", "interactive"}
# Broadcasters subject to EU/UK/US broadcasting or entity sanctions, outlets of occupation authorities, and
# countries under comprehensive sanctions. Excluded from automated admission (a maintainer must decide manually).
SANCTIONED_OWNER_TERMS = (
    "vgtrk",
    "gazprom media",
    "russian ministry of defen",
    "tv-novosti",
    "rt (",
    "sputnik",
    "islamic republic of iran broadcasting",
    "irib",
    "gtrk lnr",
    "national media group",
)
SANCTIONED_NAME_TERMS = (
    "russia today",
    "rt news",
    "rt arabic",
    "rt documentary",
    "rt espanol",
    "sputnik",
    "press tv",
    "al alam",
    "zvezda",
    "solovyov",
    "ntv",
    "rossiya",
    "russia-1",
    "russia-24",
    "russia-k",
    "pervyi kanal",
    "channel one russia",
    "perviy krymskiy",
    "lugansk 24",
    "donetsk",
    "krym 24",
    "izvestia",
    "ren tv",
)
SANCTIONED_COUNTRIES = {"kp", "sy"}
EXCLUDED_NAME_TERMS = ("scientology",)  # religious networks not tagged as such in the database
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


def slug(text: str) -> str:
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:56] or "channel"


EXTINF_ATTR = re.compile(r'([a-zA-Z-]+)="([^"]*)"')


def parse_streams(path: Path):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#EXTINF"):
            attrs = dict(EXTINF_ATTR.findall(line))
            title = line.rsplit(",", 1)[-1].strip() if "," in line else ""
            j, opts = i + 1, []
            while j < len(lines) and lines[j].startswith("#"):
                opts.append(lines[j])
                j += 1
            if j < len(lines):
                yield attrs, title, lines[j].strip(), opts
            i = j + 1
        else:
            i += 1


def resolution_rank(title: str) -> int:
    m = re.search(r"\((\d{3,4})[pi]\)", title)
    return int(m.group(1)) if m else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--streams", type=Path, required=True, help="directory with iptv-org/iptv streams/*.m3u")
    ap.add_argument("--database", type=Path, required=True, help="directory with iptv-org/database data/*.csv")
    ap.add_argument("--extra-m3u", type=Path, nargs="*", default=[], help="other M3U lists (tvg-id must match)")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    args = ap.parse_args(argv)

    db = args.database
    channels = {r["id"]: r for r in csv.DictReader((db / "channels.csv").open(encoding="utf-8"))}
    feeds = {(r["channel"], r["id"]): r for r in csv.DictReader((db / "feeds.csv").open(encoding="utf-8"))}
    main_feed = {r["channel"]: r for r in feeds.values() if r["is_main"] == "TRUE"}
    blocked = {r["channel"] for r in csv.DictReader((db / "blocklist.csv").open(encoding="utf-8"))}

    # The script regenerates data/approved/auto/ from scratch, so its own previous output is ignored here.
    existing = [c for c in load_records().all() if not c.automated or c.review.status.value != "approved"]
    existing = [c for c in existing if c.review.notes[:11] != "Quarantined"]
    known_urls = {normalise_url(c.stream.url) for c in existing}
    known_epg = {(c.epg_id or "").split("@")[0] for c in existing if c.epg_id}
    known_ids = {c.id for c in existing}
    known_names = {(c.country, c.name.casefold()) for c in existing}

    sources = sorted(args.streams.glob("*.m3u")) + list(args.extra_m3u)
    candidates: dict[str, list] = defaultdict(list)
    stats = defaultdict(int)
    for src in sources:
        for attrs, title, url, opts in parse_streams(src):
            stats["streams"] += 1
            tvg = attrs.get("tvg-id", "")
            cid, _, feed = tvg.partition("@")
            ch = channels.get(cid)
            if not ch:
                stats["no-database-entry"] += 1
                continue
            if cid in known_epg:
                stats["already-curated"] += 1
                continue
            if ch["is_nsfw"] == "TRUE" or cid in blocked:
                stats["nsfw-or-blocklisted"] += 1
                continue
            if ch["closed"]:
                stats["closed"] += 1
                continue
            owners = f"{ch['owners']} {ch['network']}".lower()
            lname = ch["name"].lower()
            if (
                ch["country"].lower() in SANCTIONED_COUNTRIES
                or any(t in owners for t in SANCTIONED_OWNER_TERMS)
                or any(re.search(rf"(^|\W){re.escape(t)}(\W|$)", lname) for t in SANCTIONED_NAME_TERMS)
            ):
                stats["sanctions-exclusion"] += 1
                continue
            if any(t in lname for t in EXCLUDED_NAME_TERMS):
                stats["excluded-category"] += 1
                continue
            cats = [c for c in ch["categories"].split(";") if c]
            if set(cats) & EXCLUDED_CATEGORIES:
                stats["excluded-category"] += 1
                continue
            if any(k in attrs for k in ("http-referrer", "http-user-agent")) or any(
                o.startswith("#EXTVLCOPT") for o in opts
            ):
                stats["needs-special-headers"] += 1
                continue
            pol = check_url_policy(url)
            if not pol.ok:
                stats["url-policy"] += 1
                continue
            host = (urlsplit(url).hostname or "").lower()
            if AGGREGATOR_HOSTS.search(host):
                stats["aggregator-host"] += 1
                continue
            why = owner_match(host, ch["website"]) if ch["website"] else None
            if not why:
                stats["host-not-owned-by-broadcaster"] += 1
                continue
            candidates[cid].append((feed, title, url, why, src.name))

    cn = countries()
    out_records: dict[str, list] = defaultdict(list)
    pending: list = []
    used_ids = set(known_ids)
    for cid, items in sorted(candidates.items()):
        ch = channels[cid]
        country = ch["country"].lower()
        if country not in cn:
            stats["unknown-country"] += 1
            continue
        mf = main_feed.get(cid, {}).get("id")

        def rank(item, mf=mf):
            feed, title, url, _, _ = item
            return (
                feed == mf,
                url.startswith("https"),
                "Not 24/7" not in title,
                "Geo-blocked" not in title,
                resolution_rank(title),
            )

        feed, title, url, why, srcname = max(items, key=rank)
        if normalise_url(url) in known_urls or (country, ch["name"].casefold()) in known_names:
            stats["duplicate-of-existing"] += 1
            continue
        known_names.add((country, ch["name"].casefold()))
        known_urls.add(normalise_url(url))
        f = feeds.get((cid, feed)) or main_feed.get(cid) or {}
        langs = []
        for code in (f.get("languages") or "").split(";"):
            two = ISO3_TO_1.get(code)
            if two and two in LANGUAGES and two not in langs:
                langs.append(two)
        if not langs:
            stats["language-not-supported"] += 1
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
                "reference_url": f"https://github.com/iptv-org/iptv/blob/master/streams/{srcname}",
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
            stats["schema-invalid"] += 1
            print(f"skip {rid}: {exc}".splitlines()[0], file=sys.stderr)
            continue
        res = screen(model)
        if res.decision is Decision.REJECT:
            stats["moderation-reject"] += 1
            continue
        if res.decision is Decision.QUARANTINE:
            rec["review"].update(
                status="pending",
                authorization_basis="none",
                adult_screening="uncertain",
                notes="Quarantined by moderation: " + "; ".join(res.reasons),
            )
            pending.append(rec)
            stats["moderation-quarantine"] += 1
            continue
        out_records[country].append(rec)
        stats["admitted"] += 1

    auto_dir = DATA / "approved" / "auto"
    auto_dir.mkdir(parents=True, exist_ok=True)
    for old in auto_dir.glob("*.yaml"):
        old.unlink()
    header = (
        "# Automatically admitted channels (scripts/expand_catalog.py). Published only after a successful live\n"
        "# check. Edit by moving a record to data/approved/<cc>.yaml (human-reviewed) or data/rejected/.\n"
    )
    for cc, recs in sorted(out_records.items()):
        recs.sort(key=lambda r: (r["name"].casefold(), r["id"]))
        (auto_dir / f"{cc}.yaml").write_text(
            header + yaml.safe_dump({"channels": recs}, sort_keys=False, allow_unicode=True, width=120),
            encoding="utf-8",
        )
    qpath = DATA / "pending" / "auto-quarantine.yaml"
    if pending:
        qpath.write_text(
            "# Automated candidates quarantined by moderation. Never published.\n"
            + yaml.safe_dump({"channels": pending}, sort_keys=False, allow_unicode=True, width=120),
            encoding="utf-8",
        )
    elif qpath.exists():
        qpath.unlink()
    for k, v in sorted(stats.items()):
        print(f"{k:32} {v}")
    print(f"countries with admitted channels: {len(out_records)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
