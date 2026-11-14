"""New free playlist sources: a weekly report for the owner's review. Nothing is ever added automatically.

A candidate is a public repository that holds an M3U playlist, carries an open licence, was updated in the last
``days`` days, is not already configured, and whose playlist passes basic checks: no credentials in addresses, no
paid, premium or adult wording, no relay/panel links, and enough entries to be worth reviewing. Reviewed candidates
are added by hand to ``[[discovery.extra_m3u]]`` in config/pipeline.toml, where every entry still goes through the
full admission rules and live checks. scripts/verify.py writes the report once a week (``due``/``find``/``write``).
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import time

import httpx

from .config import load_pipeline
from .records import ROOT

OPEN_LICENCES = {
    "mit",
    "unlicense",
    "cc0-1.0",
    "apache-2.0",
    "bsd-2-clause",
    "bsd-3-clause",
    "isc",
    "cc-by-4.0",
    "0bsd",
    "wtfpl",
}
QUERIES = ["iptv m3u free tv", "m3u playlist free channels", "free to air iptv playlist", "iptv legal free"]
BAD_WORDS = re.compile(
    r"\b(premium|vip|ppv|xxx|adult|18\+|sky ?sports|bein|dazn|netflix|hbo|disney\+|crack|restream)\b", re.I
)
BAD_URL = re.compile(r"(username=|password=|/get\.php|/player_api\.php|token=|\bauth=)", re.I)


def gh(client: httpx.Client, url: str, **params):
    for attempt in range(4):
        r = client.get(url, params=params)
        if r.status_code in (403, 429) or r.status_code >= 500:
            time.sleep(min(60, int(r.headers.get("retry-after", 10 * (attempt + 1)))))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()
    return None


def screen(text: str) -> tuple[int, list[str]]:
    entries = text.count("#EXTINF")
    problems = []
    if BAD_URL.search(text):
        problems.append("credentials or panel links")
    hits = {m.group(0).lower() for m in BAD_WORDS.finditer(text)}
    if hits:
        problems.append("paid/adult wording: " + ", ".join(sorted(hits)[:5]))
    if entries < 20:
        problems.append(f"only {entries} entries")
    return entries, problems


def find(token: str | None = None, days: int = 180, max_repos: int = 25, pause: float = 7.0) -> dict:
    """Search, screen and return {"candidates": [...], "skipped": [...]}. Works without a token (lower rate limits)."""
    cfg = load_pipeline()
    known = {s["repo"].lower() for s in cfg.discovery.sources + cfg.discovery.extra_m3u}
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "nexonic-iptv"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    found: dict[str, dict] = {}
    candidates, skipped = [], []
    with httpx.Client(base_url="https://api.github.com", headers=headers, timeout=30) as client:
        for q in QUERIES:
            try:
                body = gh(
                    client, "/search/repositories", q=f"{q} pushed:>{cutoff:%Y-%m-%d}", sort="updated", per_page=50
                )
            except httpx.HTTPError as exc:
                print(f"WARNING repository search failed: {exc}", file=sys.stderr)
                continue
            for item in (body or {}).get("items", []):
                if item["full_name"].lower() not in known:
                    found.setdefault(item["full_name"], item)
            time.sleep(pause)  # the search allows about ten requests a minute
        for repo, meta in sorted(found.items(), key=lambda kv: -kv[1].get("stargazers_count", 0))[:max_repos]:
            lic = ((meta.get("license") or {}).get("spdx_id") or "").lower()
            if meta.get("archived") or meta.get("fork"):
                skipped.append({"repo": repo, "reason": "archived or fork"})
                continue
            if lic not in OPEN_LICENCES:
                skipped.append({"repo": repo, "reason": f"no open licence ({lic or 'none'})"})
                continue
            ref = meta.get("default_branch", "main")
            try:
                tree = gh(client, f"/repos/{repo}/git/trees/{ref}", recursive=1) or {}
            except httpx.HTTPError:
                continue
            paths = [
                t["path"]
                for t in tree.get("tree", [])
                if t.get("type") == "blob" and t["path"].lower().endswith((".m3u", ".m3u8"))
            ]
            best = None
            for path in sorted(paths, key=lambda x: (x.count("/"), x))[:5]:
                raw = client.get(f"https://raw.githubusercontent.com/{repo}/{ref}/{path}", follow_redirects=True)
                if raw.status_code != 200 or len(raw.content) > 50 * 1024 * 1024:
                    continue
                entries, problems = screen(raw.text)
                if not problems and (best is None or entries > best["entries"]):
                    best = {"path": path, "entries": entries}
                time.sleep(1)
            if best is None:
                skipped.append({"repo": repo, "reason": "no playlist passed the checks"})
                continue
            candidates.append(
                {
                    "repo": repo,
                    "ref": ref,
                    "licence": meta["license"]["spdx_id"],
                    "stars": meta.get("stargazers_count", 0),
                    "pushed_at": meta.get("pushed_at") or "",
                    **best,
                }
            )
    candidates.sort(key=lambda c: (-c["entries"], c["repo"]))
    return {"candidates": candidates, "skipped": skipped}


def write(result: dict, root=ROOT) -> None:
    out = {"generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), **result}
    (root / "reports").mkdir(exist_ok=True)
    (root / "reports" / "source-candidates.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    lines = [
        "# Source candidates",
        "",
        f"Generated {out['generated_at']}. Review before adding any of these to config/pipeline.toml.",
        "",
        "| Repository | Licence | Playlist | Entries | Updated |",
        "|---|---|---|---:|---|",
    ]
    lines += [
        f"| {c['repo']} | {c['licence']} | `{c['path']}` | {c['entries']} | {c['pushed_at'][:10]} |"
        for c in out["candidates"]
    ]
    if not out["candidates"]:
        lines.append("| none this week | | | | |")
    (root / "reports" / "source-candidates.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def due(root=ROOT, days: int = 7) -> bool:
    """True when the last report is missing or at least ``days`` old (the daily run makes one a week)."""
    try:
        made = json.loads((root / "reports" / "source-candidates.json").read_text(encoding="utf-8"))["generated_at"]
    except (OSError, ValueError, KeyError):
        return True
    return dt.datetime.now(dt.UTC) - dt.datetime.fromisoformat(made) >= dt.timedelta(days=days)
