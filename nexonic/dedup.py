"""Duplicate detection shared by record checks, generation and discovery.

Two records are the same channel when they use the same stream (scheme-insensitive: ``http://h/p`` and
``https://h/p`` are one stream) or the same identity. Identity is the full EPG id within a country (``DW.de@English``
and ``DW.de@Spanish`` are different feeds), or the folded name within a country when there is no EPG id. Names keep
digits and ``+`` so ``ETV``, ``ETV 2`` and ``ETV+`` stay distinct, and regional variants (different names or feeds)
are never merged.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

from .models import Channel


def stream_key(url: str) -> str:
    """Normalised stream identity: host (lower case), non-default port, path without a trailing slash, query."""
    p = urlsplit(url.strip())
    host = (p.hostname or "").lower()
    port = f":{p.port}" if p.port and p.port not in (80, 443) else ""
    path = p.path.rstrip("/") or "/"
    return f"{host}{port}{path}" + (f"?{p.query}" if p.query else "")


def fold_name(name: str) -> str:
    t = unicodedata.normalize("NFKD", name)
    t = "".join(c for c in t if not unicodedata.combining(c)).casefold()
    return re.sub(r"[^a-z0-9+\u0080-￿]+", "", t)


def identity_key(ch: Channel) -> tuple[str, str]:
    if ch.epg_id:
        return (ch.country, "epg:" + ch.epg_id.casefold())
    return (ch.country, "name:" + fold_name(ch.name))


def find_duplicates(channels: list[Channel]) -> dict[str, str]:
    """Map each duplicate channel id to the id it duplicates (first in id order wins), by stream or identity."""
    dup: dict[str, str] = {}
    streams: dict[str, str] = {}
    idents: dict[tuple[str, str], str] = {}
    for ch in sorted(channels, key=lambda c: c.id):
        sk, ik = stream_key(ch.stream.url), identity_key(ch)
        first = streams.get(sk) or idents.get(ik)
        if first:
            dup[ch.id] = first
            continue
        streams[sk] = ch.id
        idents[ik] = ch.id
    return dup
