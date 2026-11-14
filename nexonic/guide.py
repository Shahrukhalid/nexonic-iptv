"""TV guide: XMLTV feeds merged and trimmed to the channels Nexonic publishes.

Feeds come from ``[guide] feeds`` (https, hosts in ``allowed_hosts``) and should only be ones whose publisher allows
reuse. Each feed is streamed and parsed without loading it whole; only ``<channel>`` and ``<programme>`` elements for
published tvg-ids inside the time window are kept. The result is ``playlists/guide.xml.gz``, which the playlists
name in their ``x-tvg-url`` header so players fill their guide automatically. A failed feed is skipped; when no
feed works the previous guide stays until its programmes run out.
"""

from __future__ import annotations

import datetime as dt
import gzip
import io
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

from .config import DiscoveryConfig, playlist_url
from .extras_config import GuideConfig
from .fetch import FetchError, download
from .records import ROOT
from .timeutil import utc_now

GUIDE_REL = "playlists/guide.xml.gz"
GUIDE_FILE = ROOT / GUIDE_REL


def guide_url() -> str:
    return playlist_url(GUIDE_REL)


def parse_time(value: str) -> dt.datetime | None:
    """XMLTV time ``20261114183000 +0100`` (offset optional) as UTC."""
    v = (value or "").strip()
    try:
        base = dt.datetime.strptime(v[:14], "%Y%m%d%H%M%S")
    except ValueError:
        return None
    off = v[14:].strip()
    delta = dt.timedelta()
    if len(off) == 5 and off[0] in "+-" and off[1:].isdigit():
        delta = dt.timedelta(hours=int(off[1:3]), minutes=int(off[3:5])) * (1 if off[0] == "+" else -1)
    return (base - delta).replace(tzinfo=dt.UTC)


def _open(raw: bytes) -> io.BufferedIOBase:
    return gzip.GzipFile(fileobj=io.BytesIO(raw)) if raw[:2] == b"\x1f\x8b" else io.BytesIO(raw)


def merge(feeds: list[bytes], ids: set[str], now: dt.datetime, cfg: GuideConfig) -> tuple[bytes, dict]:
    """Merged XMLTV document (bytes) and counts. The first feed that describes a channel wins for that channel."""
    lo, hi = now - dt.timedelta(hours=cfg.hours_behind), now + dt.timedelta(hours=cfg.hours_ahead)
    folded = {i.casefold(): i for i in ids}
    channels: dict[str, ET.Element] = {}
    owner: dict[str, int] = {}
    programmes: list[ET.Element] = []
    for n, raw in enumerate(feeds):
        try:
            stream = _open(raw)
            if b"<!ENTITY" in stream.read(65536):
                continue  # entity definitions are never needed in a guide; refusing them rules out expansion attacks
            stream.seek(0)
            # Safe here: entity declarations were refused above and expat never loads external resources.
            for _ev, el in ET.iterparse(stream, events=("end",)):  # noqa: S314
                if el.tag == "channel":
                    cid = folded.get((el.get("id") or "").casefold())
                    if cid and cid not in channels:
                        el.set("id", cid)
                        el.tail = None
                        channels[cid] = el
                        owner[cid] = n
                    else:
                        el.clear()
                elif el.tag == "programme":
                    cid = folded.get((el.get("channel") or "").casefold())
                    start, stop = parse_time(el.get("start", "")), parse_time(el.get("stop", ""))
                    if cid and owner.get(cid, n) == n and start and start < hi and (stop or start) > lo:
                        owner.setdefault(cid, n)
                        el.set("channel", cid)
                        el.tail = None
                        programmes.append(el)
                    else:
                        el.clear()
        except (ET.ParseError, OSError, EOFError):
            continue
    root = ET.Element("tv", {"generator-info-name": "Nexonic IPTV"})
    for cid in sorted(channels):
        root.append(channels[cid])
    for p in sorted(programmes, key=lambda e: (e.get("channel"), e.get("start"))):
        root.append(p)
    body = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return body, {"channels": len({p.get("channel") for p in programmes}), "programmes": len(programmes)}


def build(
    cfg: GuideConfig,
    ids: set[str],
    *,
    now: dt.datetime | None = None,
    out: Path | None = None,
    fetch: Callable[[str], bytes] | None = None,
    log: Callable[[str], None] = print,
) -> dict:
    out = out or GUIDE_FILE
    if not cfg.enabled or not cfg.feeds or not ids:
        return {"enabled": cfg.enabled, "feeds": len(cfg.feeds), "programmes": 0}
    now = now or utc_now()
    disc = DiscoveryConfig(
        timeout=cfg.timeout, retries=cfg.retries, backoff_base=cfg.backoff_base, allowed_hosts=list(cfg.allowed_hosts)
    )

    def default_fetch(url: str) -> bytes:
        with tempfile.TemporaryFile() as f:
            download(url, f, disc, limit_mb=cfg.max_feed_mb)
            f.seek(0)
            return f.read()

    fetch = fetch or default_fetch
    raws, failed = [], []
    for url in cfg.feeds:
        try:
            raws.append(fetch(url))
        except FetchError as exc:
            failed.append(url)
            log(f"guide: {url} failed ({exc})")
    body, counts = merge(raws, ids, now, cfg)
    if counts["programmes"] == 0:
        log("guide: no programmes found; keeping the previous guide")
        return {"enabled": True, "feeds": len(cfg.feeds), "failed": len(failed), **counts}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(gzip.compress(body, mtime=0))
    log(f"guide: {counts['channels']} channels, {counts['programmes']} programmes")
    return {"enabled": True, "feeds": len(cfg.feeds), "failed": len(failed), **counts}


def available(path: Path | None = None) -> bool:
    return (path or GUIDE_FILE).exists()
