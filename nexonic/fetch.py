"""Polite HTTPS download with retries and exponential backoff, restricted to an allow-list of hosts.

Used to read the public iptv-org data straight from GitHub when no local clone is available. Only https URLs on
allowed hosts are fetched; redirects are followed manually and every hop is checked against the same rules. Timeouts,
connection errors, 429 and 5xx are retried (honouring ``Retry-After`` up to 60 s); other 4xx responses fail at once.
"""

from __future__ import annotations

import tarfile
import time
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlsplit

import httpx

from .config import DiscoveryConfig

USER_AGENT = "NexonicIPTV-Discovery/1.0 (+https://github.com/Shahrukhalid/nexonic-iptv; catalogue refresh)"
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_REDIRECTS = 5
DATABASE_FILES = ("channels.csv", "feeds.csv", "blocklist.csv")


class FetchError(RuntimeError):
    pass


def _check_url(url: str, allowed: list[str]) -> None:
    p = urlsplit(url)
    if p.scheme != "https" or (p.hostname or "").lower() not in {h.lower() for h in allowed}:
        raise FetchError(f"refusing to fetch {url}: only https URLs on {', '.join(allowed)} are allowed")


def backoff_delay(attempt: int, base: float, retry_after: str | None = None) -> float:
    delay = base * (2**attempt)
    if retry_after and retry_after.strip().isdigit():
        delay = max(delay, min(float(retry_after), 60.0))
    return delay


def _download(client: httpx.Client, url: str, dest, cfg: DiscoveryConfig) -> None:
    limit = cfg.max_archive_mb * 1024 * 1024
    for _hop in range(MAX_REDIRECTS + 1):
        _check_url(url, cfg.allowed_hosts)
        with client.stream("GET", url, headers={"User-Agent": USER_AGENT}, follow_redirects=False) as r:
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                url = urljoin(url, r.headers["location"])
                continue
            if r.status_code in RETRY_STATUS:
                raise _Retry(f"HTTP {r.status_code}", r.headers.get("retry-after"))
            if r.status_code != 200:
                raise FetchError(f"{url}: HTTP {r.status_code}")
            size = 0
            dest.seek(0)
            dest.truncate()
            for chunk in r.iter_bytes():
                size += len(chunk)
                if size > limit:
                    raise FetchError(f"{url}: larger than {cfg.max_archive_mb} MB")
                dest.write(chunk)
            return
    raise FetchError(f"too many redirects fetching {url}")


class _Retry(Exception):
    def __init__(self, msg: str, retry_after: str | None = None):
        super().__init__(msg)
        self.retry_after = retry_after


def download(
    url: str,
    dest,
    cfg: DiscoveryConfig,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Download ``url`` into the open binary file ``dest``, retrying transient failures with backoff."""
    own = client is None
    client = client or httpx.Client(timeout=cfg.timeout)
    try:
        for attempt in range(cfg.retries + 1):
            try:
                return _download(client, url, dest, cfg)
            except (_Retry, httpx.TransportError) as exc:
                if attempt >= cfg.retries:
                    raise FetchError(f"{url}: giving up after {attempt + 1} attempts ({exc})") from exc
                sleep(backoff_delay(attempt, cfg.backoff_base, getattr(exc, "retry_after", None)))
    finally:
        if own:
            client.close()


def archive_url(source: dict) -> str:
    return f"https://github.com/{source['repo']}/archive/refs/heads/{source['ref']}.tar.gz"


def extract(archive: Path, dest: Path, wanted) -> int:
    """Extract only the regular files ``wanted(parts)`` maps to a relative output path for; nothing else is read."""
    n = 0
    with tarfile.open(archive, "r:gz") as tar:
        for m in tar:
            if not m.isfile():
                continue
            parts = PurePosixPath(m.name).parts[1:]  # drop the archive's top-level directory
            rel = wanted(parts)
            if rel is None or m.size > 256 * 1024 * 1024:
                continue
            f = tar.extractfile(m)
            if f is None:
                continue
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(f.read())
            n += 1
    return n


def _streams(parts: tuple[str, ...]) -> str | None:
    if len(parts) == 2 and parts[0] == "streams" and parts[1].endswith(".m3u"):
        return f"streams/{parts[1]}"
    return None


def _database(parts: tuple[str, ...]) -> str | None:
    if len(parts) == 2 and parts[0] == "data" and parts[1] in DATABASE_FILES:
        return f"database/{parts[1]}"
    return None


def fetch_iptv_org(
    cfg: DiscoveryConfig,
    dest: Path,
    need: tuple[str, ...] = ("iptv", "database"),
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Path]:
    """Download the configured sources into ``dest``; returns {'streams': dir, 'database': dir} for those needed."""
    out: dict[str, Path] = {}
    for src in cfg.sources:
        if src["name"] not in need:
            continue
        path = dest / f"{src['name']}.tar.gz"
        dest.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as fh:
            download(archive_url(src), fh, cfg, client, sleep)
        if src["name"] == "iptv":
            if not extract(path, dest, _streams):
                raise FetchError("the iptv archive contains no streams/*.m3u files")
            out["streams"] = dest / "streams"
        else:
            if not extract(path, dest, _database):
                raise FetchError("the database archive contains none of the expected data/*.csv files")
            out["database"] = dest / "database"
        path.unlink()
    return out
