"""Xtream Codes compatible gateway for the generated playlists.

Many IPTV apps ask for a *server URL, username and password* instead of an M3U link. This module answers the
requests those apps make (``player_api.php``, ``get.php``, ``xmltv.php`` and the ``/live/``, ``/movie/`` and
``/series/`` stream paths) from the playlists in ``playlists/``. It never re-streams video: a stream request is
answered with a redirect to the broadcaster's own URL, and only URLs that are in the playlists can be reached.

The login is public and printed in the README (everything here is free); it only exists because the apps require
one. Start it with ``python scripts/xtream_server.py``.
"""

from __future__ import annotations

import hmac
import json
import re
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, quote

from . import m3u

DEFAULT_USER = "nexonic"
DEFAULT_PASSWORD = "free"
STREAM_PATH = re.compile(r"^/(live|movie|series)/([^/]+)/([^/]+)/(\d+)(?:\.([a-z0-9]{1,5}))?$")


def stable_id(key: str) -> int:
    """A positive id that stays the same between restarts and playlist updates."""
    return zlib.crc32(key.encode("utf-8")) & 0x7FFFFFFF or 1


def _ext(url: str, default: str) -> str:
    m = re.search(r"\.([a-z0-9]{2,5})(?:$|[?#])", url.lower())
    return m.group(1) if m else default


@dataclass
class Item:
    id: int
    name: str
    url: str
    category: str
    logo: str = ""
    epg_id: str = ""
    duration: int = 0
    year: str = ""


@dataclass
class Catalog:
    live: list[Item] = field(default_factory=list)
    movies: list[Item] = field(default_factory=list)
    episodes: list[Item] = field(default_factory=list)
    by_id: dict[tuple[str, int], Item] = field(default_factory=dict)

    @staticmethod
    def categories(items: list[Item]) -> list[dict]:
        names = sorted({i.category for i in items})
        return [{"category_id": str(stable_id(n)), "category_name": n, "parent_id": 0} for n in names]


def _items(path: Path, kind: str) -> list[Item]:
    if not path.exists():
        return []
    out, seen = [], set()
    for e in m3u.parse(path.read_text(encoding="utf-8", errors="replace")):
        a = e.attrs
        key = f"{kind}:{a.get('tvg-id') or ''}:{e.url}"
        if key in seen:
            continue
        seen.add(key)
        try:
            duration = max(0, int(float(e.duration)))
        except ValueError:
            duration = 0
        out.append(
            Item(
                id=stable_id(key),
                name=e.title,
                url=e.url,
                category=a.get("group-title") or "Other",
                logo=a.get("tvg-logo", ""),
                epg_id=a.get("tvg-id", ""),
                duration=duration,
                year=a.get("x-year", ""),
            )
        )
    return out


def load_catalog(playlists: Path) -> Catalog:
    cat = Catalog(
        live=_items(playlists / "all.m3u", "live"),
        movies=_items(playlists / "vod" / "movies.m3u", "movie"),
        episodes=_items(playlists / "vod" / "series.m3u", "series"),
    )
    for kind, items in (("live", cat.live), ("movie", cat.movies), ("series", cat.episodes)):
        for i in items:
            cat.by_id[(kind, i.id)] = i
    return cat


class Gateway:
    """Answers Xtream requests. ``handle`` returns (status, headers, body) so it can sit behind any HTTP server."""

    def __init__(self, playlists: Path, public_url: str, user: str = DEFAULT_USER, password: str = DEFAULT_PASSWORD):
        self.playlists = playlists
        self.public_url = public_url.rstrip("/")
        self.user, self.password = user, password
        self._catalog = Catalog()
        self._stamp: tuple = ()

    @property
    def catalog(self) -> Catalog:
        """Reloaded automatically when the playlists change on disk (e.g. after a git pull)."""
        files = [
            self.playlists / "all.m3u",
            self.playlists / "vod" / "movies.m3u",
            self.playlists / "vod" / "series.m3u",
        ]
        stamp = tuple(f.stat().st_mtime_ns if f.exists() else 0 for f in files)
        if stamp != self._stamp:
            self._catalog, self._stamp = load_catalog(self.playlists), stamp
        return self._catalog

    def _ok(self, user: str, password: str) -> bool:
        return hmac.compare_digest(user.encode(), self.user.encode()) and hmac.compare_digest(
            password.encode(), self.password.encode()
        )

    # ------------------------------------------------------------------ responses
    @staticmethod
    def _json(data, status: int = 200):
        return status, {"Content-Type": "application/json; charset=utf-8"}, json.dumps(data).encode()

    def _account(self) -> dict:
        now = int(time.time())
        host = self.public_url.split("://", 1)[-1].split("/", 1)[0]
        name, _, port = host.partition(":")
        https = self.public_url.startswith("https://")
        return {
            "user_info": {
                "username": self.user,
                "password": self.password,
                "message": "Nexonic IPTV: free-to-air channels, free for everyone.",
                "auth": 1,
                "status": "Active",
                "exp_date": None,
                "is_trial": "0",
                "active_cons": "0",
                "created_at": "1730419200",
                "max_connections": "100",
                "allowed_output_formats": ["m3u8", "ts"],
            },
            "server_info": {
                "url": name,
                "port": port or ("443" if https else "80"),
                "https_port": port or "443",
                "server_protocol": "https" if https else "http",
                "rtmp_port": "0",
                "timezone": "UTC",
                "timestamp_now": now,
                "time_now": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now)),
            },
        }

    def _live(self, items: list[Item]) -> list[dict]:
        return [
            {
                "num": n,
                "name": i.name,
                "stream_type": "live",
                "stream_id": i.id,
                "stream_icon": i.logo,
                "epg_channel_id": i.epg_id or None,
                "added": "0",
                "category_id": str(stable_id(i.category)),
                "custom_sid": "",
                "tv_archive": 0,
                "direct_source": "",
                "tv_archive_duration": 0,
            }
            for n, i in enumerate(items, 1)
        ]

    def _movies(self, items: list[Item]) -> list[dict]:
        return [
            {
                "num": n,
                "name": i.name,
                "stream_type": "movie",
                "stream_id": i.id,
                "stream_icon": i.logo,
                "rating": "",
                "added": "0",
                "category_id": str(stable_id(i.category)),
                "container_extension": _ext(i.url, "mp4"),
                "custom_sid": "",
                "direct_source": "",
            }
            for n, i in enumerate(items, 1)
        ]

    def _series_list(self, cat: Catalog) -> list[dict]:
        shows: dict[str, Item] = {}
        for e in cat.episodes:
            shows.setdefault(e.category, e)
        return [
            {
                "num": n,
                "name": name,
                "series_id": stable_id(f"show:{name}"),
                "cover": first.logo,
                "plot": "",
                "year": first.year,
                "category_id": str(stable_id("Series")),
                "last_modified": "0",
            }
            for n, (name, first) in enumerate(sorted(shows.items()), 1)
        ]

    def _series_info(self, cat: Catalog, series_id: str) -> dict:
        eps = [e for e in cat.episodes if str(stable_id(f"show:{e.category}")) == series_id]
        if not eps:
            return {"info": {}, "episodes": {}, "seasons": []}
        return {
            "info": {"name": eps[0].category, "cover": eps[0].logo, "year": eps[0].year},
            "seasons": [{"season_number": 1, "name": "Season 1", "episode_count": len(eps)}],
            "episodes": {
                "1": [
                    {
                        "id": str(e.id),
                        "episode_num": n,
                        "title": e.name,
                        "season": 1,
                        "container_extension": _ext(e.url, "mp4"),
                        "info": {"duration_secs": e.duration, "movie_image": e.logo},
                    }
                    for n, e in enumerate(eps, 1)
                ]
            },
        }

    def _player_api(self, q: dict[str, str]):
        cat = self.catalog
        action = q.get("action", "")
        cid = q.get("category_id")
        pick = lambda items: [i for i in items if not cid or str(stable_id(i.category)) == cid]  # noqa: E731
        if not action:
            return self._json(self._account())
        if action == "get_live_categories":
            return self._json(Catalog.categories(cat.live))
        if action == "get_live_streams":
            return self._json(self._live(pick(cat.live)))
        if action == "get_vod_categories":
            return self._json(Catalog.categories(cat.movies))
        if action == "get_vod_streams":
            return self._json(self._movies(pick(cat.movies)))
        if action == "get_vod_info":
            i = cat.by_id.get(("movie", int(q.get("vod_id", "0") or 0)))
            if i is None:
                return self._json({"info": {}, "movie_data": {}})
            return self._json(
                {
                    "info": {"name": i.name, "movie_image": i.logo, "duration_secs": i.duration, "releasedate": i.year},
                    "movie_data": {"stream_id": i.id, "name": i.name, "container_extension": _ext(i.url, "mp4")},
                }
            )
        if action == "get_series_categories":
            return self._json(
                [{"category_id": str(stable_id("Series")), "category_name": "Series", "parent_id": 0}]
                if cat.episodes
                else []
            )
        if action == "get_series":
            return self._json(self._series_list(cat))
        if action == "get_series_info":
            return self._json(self._series_info(cat, q.get("series_id", "")))
        if action in ("get_short_epg", "get_simple_data_table"):
            return self._json({"epg_listings": []})
        return self._json([])

    def _m3u(self, q: dict[str, str]):
        base, u, p = self.public_url, quote(self.user), quote(self.password)
        lines = ["#EXTM3U"]
        for i in self.catalog.live:
            lines.append(
                f'#EXTINF:-1 tvg-id="{m3u.clean_attr(i.epg_id)}" tvg-name="{m3u.clean_attr(i.name)}" '
                f'tvg-logo="{m3u.clean_attr(i.logo)}" group-title="{m3u.clean_attr(i.category)}",{m3u.clean_title(i.name)}'
            )
            lines.append(f"{base}/live/{u}/{p}/{i.id}.{'m3u8' if q.get('output') != 'ts' else 'ts'}")
        return 200, {"Content-Type": "audio/x-mpegurl; charset=utf-8"}, ("\n".join(lines) + "\n").encode()

    def handle(self, path: str, query: str):
        q = {k: v[0] for k, v in parse_qs(query, keep_blank_values=True).items()}
        if path in ("/", "/health"):
            return self._json({"service": "Nexonic IPTV Xtream gateway", "live": len(self.catalog.live)})
        m = STREAM_PATH.match(path)
        if m:
            kind, user, password, sid, _ext_ = m.groups()
            if not self._ok(user, password):
                return 401, {"Content-Type": "text/plain"}, b"invalid login\n"
            item = self.catalog.by_id.get((kind, int(sid)))
            if item is None:
                return 404, {"Content-Type": "text/plain"}, b"unknown stream\n"
            return 302, {"Location": item.url, "Cache-Control": "no-store"}, b""
        if path in ("/player_api.php", "/get.php", "/xmltv.php", "/panel_api.php"):
            if not self._ok(q.get("username", ""), q.get("password", "")):
                if path == "/player_api.php":
                    return self._json({"user_info": {"auth": 0}})
                return 401, {"Content-Type": "text/plain"}, b"invalid login\n"
            if path == "/get.php":
                return self._m3u(q)
            if path == "/xmltv.php":
                body = b'<?xml version="1.0" encoding="UTF-8"?>\n<tv generator-info-name="Nexonic IPTV"></tv>\n'
                return 200, {"Content-Type": "application/xml; charset=utf-8"}, body
            return self._player_api(q)
        return 404, {"Content-Type": "text/plain"}, b"not found\n"
