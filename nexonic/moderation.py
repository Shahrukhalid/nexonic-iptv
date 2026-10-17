"""Adult-content screening and publication gate (defence in depth).

Layers, applied to every record before it can reach a playlist:

1. Schema: adult categories do not exist in ``CATEGORIES`` and ``is_nsfw: true`` cannot be approved.
2. Identity denylists: iptv-org/database NSFW channel IDs and blocklist, plus Nexonic's own denylist.
3. Strong-term lexicon on name, aliases, description, broadcaster, website, source notes, EPG id and URL → REJECT.
4. Weak/ambiguous-term lexicon → QUARANTINE (manual review), unless a maintainer allowlisted that exact channel id.
5. Human review: approved records must carry ``adult_screening: pass`` from a named reviewer.

Anything uncertain is quarantined; nothing is silently approved.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path

import yaml

from .models import Channel, ReviewStatus

ROOT = Path(__file__).resolve().parent.parent
MODERATION_DIR = ROOT / "data" / "moderation"

# Terms that on their own identify adult-oriented programming (multi-language). Matched on whole tokens.
STRONG_TERMS = {
    "xxx",
    "porn",
    "porno",
    "pornographic",
    "erotic",
    "erotica",
    "erotik",
    "eroticos",
    "erotico",
    "erotique",
    "sex",
    "sexy",
    "sexo",
    "sexe",
    "hentai",
    "nsfw",
    "milf",
    "playboy",
    "penthouse",
    "hustler",
    "brazzers",
    "redlight",
    "bangbros",
    "vivid",
    "dorcel",
    "adult",
    "adulto",
    "adulti",
    "adulte",
    "adults",
    "xxl18",
    "camgirl",
    "camgirls",
    "stripper",
    "striptease",
    "fetish",
    "bdsm",
    "nude",
    "nudes",
    "naked",
    "topless",
    "escort",
    "hardcore",
    "softcore",
    "hotclub",
    "babestation",
    "privatetv",
    "pinko",
    "bikini",
}
# Patterns that need more than one token or special characters.
STRONG_PATTERNS = [
    re.compile(r"(?<![0-9])18\s*\+"),
    re.compile(r"\+\s*18(?![0-9])"),
    re.compile(r"\bx{3,}\b"),
    re.compile(r"\bfor\s+adults?\b"),
]
# Terms that are often innocent but frequent in adult channel names → manual review.
WEAK_TERMS = {
    "hot",
    "babe",
    "babes",
    "desire",
    "passion",
    "lust",
    "love",
    "night",
    "nights",
    "private",
    "pink",
    "spice",
    "kiss",
    "kisses",
    "tease",
    "flirt",
    "dating",
    "lingerie",
    "intim",
    "intimate",
    "seduction",
    "pleasure",
    "dream",
    "dreams",
    "girls",
    "boys",
    "body",
    "bodies",
    "18",
    "21",
    "x",
    "xx",
    "after dark",
    "afterdark",
    "candy",
    "honey",
    "venus",
    "satisfaction",
}
TEXT_FIELDS = ("name", "description", "broadcaster", "website")


class Decision(str, Enum):
    PASS = "pass"
    QUARANTINE = "quarantine"
    REJECT = "reject"


@dataclass
class ModerationResult:
    channel_id: str
    decision: Decision
    reasons: list[str] = field(default_factory=list)

    @property
    def publishable(self) -> bool:
        return self.decision is Decision.PASS


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    # leetspeak commonly used to dodge filters
    text = text.translate(str.maketrans({"0": "o", "3": "e", "4": "a", "$": "s", "@": "a"}))
    return text


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", normalise(text))


def _name_key(text: str) -> str:
    return "".join(re.findall(r"[a-z0-9+]+", normalise(text)))


@lru_cache(maxsize=1)
def _iptv_org_ids() -> frozenset[str]:
    ids: set[str] = set()
    for fname in ("iptv-org-nsfw-blocklist.txt", "iptv-org-nsfw-channels.txt"):
        path = MODERATION_DIR / fname
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    ids.add(line.lower())
    return frozenset(ids)


@lru_cache(maxsize=1)
def _iptv_org_names() -> frozenset[str]:
    path = MODERATION_DIR / "iptv-org-nsfw-names.txt"
    if not path.exists():
        return frozenset()
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            out.add(_name_key(line))
    return frozenset(k for k in out if k)


@lru_cache(maxsize=1)
def _local_lists() -> dict:
    path = MODERATION_DIR / "denylist.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    data = data or {}
    allow_path = MODERATION_DIR / "allowlist.yaml"
    allow = yaml.safe_load(allow_path.read_text(encoding="utf-8")) if allow_path.exists() else {}
    allow = allow or {}
    return {
        "ids": {s.lower() for s in data.get("channel_ids", [])},
        "names": {_name_key(s) for s in data.get("names", [])},
        "hosts": [re.compile(p) for p in data.get("host_patterns", [])],
        "weak_allow": {str(k): set(v) for k, v in (allow.get("weak_term_overrides") or {}).items()},
    }


def clear_caches() -> None:
    _iptv_org_ids.cache_clear()
    _iptv_org_names.cache_clear()
    _local_lists.cache_clear()


def _texts(ch: Channel) -> dict[str, str]:
    out = {f: getattr(ch, f) or "" for f in TEXT_FIELDS}
    out["alt_names"] = " | ".join(ch.alt_names)
    out["categories"] = " ".join(ch.categories)
    out["source.notes"] = ch.source.notes
    out["source.evidence_summary"] = ch.source.evidence_summary
    out["review.notes"] = ch.review.notes
    out["epg_id"] = ch.epg_id or ""
    out["stream.url"] = ch.stream.url
    return out


def screen(ch: Channel) -> ModerationResult:
    """Return the moderation decision for one record (does not consider review status)."""
    reasons: list[str] = []
    reject = False
    quarantine = False
    lists = _local_lists()

    if ch.is_nsfw:
        reject = True
        reasons.append("record is flagged is_nsfw")
    if ch.review.adult_screening == "fail":
        reject = True
        reasons.append("human adult screening: fail")
    elif ch.review.adult_screening == "uncertain":
        quarantine = True
        reasons.append("human adult screening: uncertain")

    if ch.id.lower() in lists["ids"]:
        reject = True
        reasons.append("channel id is on the Nexonic denylist")
    if ch.epg_id and ch.epg_id.split("@")[0].lower() in _iptv_org_ids():
        reject = True
        reasons.append(f"epg_id {ch.epg_id} is NSFW-listed in iptv-org/database")
    for name in [ch.name, *ch.alt_names]:
        key = _name_key(name)
        if key in lists["names"]:
            reject = True
            reasons.append(f"name {name!r} is on the Nexonic denylist")
        elif key in _iptv_org_names():
            quarantine = True
            reasons.append(f"name {name!r} matches an NSFW-listed channel name in iptv-org/database")
    from urllib.parse import urlsplit

    host = (urlsplit(ch.stream.url).hostname or "").lower()
    for pat in lists["hosts"]:
        if pat.search(host):
            reject = True
            reasons.append(f"stream host {host} matches denylisted pattern {pat.pattern}")

    allowed_weak = lists["weak_allow"].get(ch.id, set())
    for fname, text in _texts(ch).items():
        if not text:
            continue
        toks = tokens(text)
        tokset = set(toks)
        norm = normalise(text)
        hits = sorted(tokset & STRONG_TERMS)
        # compound words such as "hotsex" / "pornotv"
        review_compounds = []
        for tok in tokset:
            for term in ("porn", "xxx", "sex", "erotic", "hentai", "nsfw"):
                if term in tok and tok not in hits and tok not in _SAFE_COMPOUNDS:
                    if tok in _REVIEW_COMPOUNDS:
                        review_compounds.append(tok)
                    else:
                        hits.append(tok)
        if review_compounds and fname not in ("stream.url", "website"):
            quarantine = True
            reasons.append(f"{fname}: term(s) {sorted(set(review_compounds))} need manual review")
        for pat in STRONG_PATTERNS:
            if pat.search(norm):
                hits.append(pat.pattern)
        if hits:
            reject = True
            reasons.append(f"{fname}: adult term(s) {sorted(set(hits))}")
        if fname in ("stream.url", "website", "source.evidence_summary", "review.notes", "source.notes"):
            continue  # weak terms are too noisy in URLs and prose
        weak = sorted((tokset & WEAK_TERMS) - allowed_weak)
        joined = " ".join(toks)
        for phrase in (w for w in WEAK_TERMS if " " in w):
            if phrase in joined and phrase not in allowed_weak:
                weak.append(phrase)
        if weak:
            quarantine = True
            reasons.append(f"{fname}: ambiguous term(s) {weak} need manual review")

    if reject:
        return ModerationResult(ch.id, Decision.REJECT, reasons)
    if quarantine:
        return ModerationResult(ch.id, Decision.QUARANTINE, reasons)
    return ModerationResult(ch.id, Decision.PASS, reasons)


# Real words that contain a strong substring but are not adult terms.
_SAFE_COMPOUNDS = {"sussex", "essex", "middlesex", "wessex", "sexton", "sextet", "sextant", "sexagesimal"}
# Words that are not adult terms by themselves but warrant a human look.
_REVIEW_COMPOUNDS = {"unisex", "sexual", "sexuality", "bisexual", "homosexual", "heterosexual", "sexology"}


def publication_gate(ch: Channel) -> tuple[bool, list[str]]:
    """Final gate used by the playlist generator. Every condition must hold."""
    problems: list[str] = []
    if ch.review.status is not ReviewStatus.APPROVED:
        problems.append(f"review status is {ch.review.status.value}")
    result = screen(ch)
    if not result.publishable:
        problems.append(f"moderation: {result.decision.value} ({'; '.join(result.reasons)})")
    if ch.review.adult_screening != "pass":
        problems.append("adult screening is not 'pass'")
    return (not problems, problems)
