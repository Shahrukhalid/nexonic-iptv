"""README dashboard: what the latest automatic update changed, and the last seven days.

Built from the change report (``reports/changes.json``) and its daily history (``state/change-history.json``), so it
is a pure function of committed data. ``scripts/generate.py`` places it at the end of the README numbers block.
"""

from __future__ import annotations

from .reference import countries

ROWS = (
    ("new_published", "New channels added"),
    ("restored", "Working again (back in the playlists)"),
    ("newly_quarantined", "Stopped working (taken out until they recover)"),
    ("removed", "Removed for good"),
)


def _names(items: list[dict], limit: int = 12) -> str:
    cn = countries()
    shown = []
    for e in items[:limit]:
        flag = cn.get(e.get("country") or "", {}).get("flag", "")
        shown.append(f"{flag} {e.get('name') or e.get('id')}".strip())
    more = len(items) - len(shown)
    return ", ".join(shown) + (f" and {more} more" if more > 0 else "")


def lines(report: dict | None, days: list[dict] | None) -> list[str]:
    if not report:
        return []
    lists, counts = report.get("lists") or {}, report.get("counts") or {}
    out = ["**Latest automatic update:**", "", "| Change | Channels | Which |", "|---|---:|---|"]
    for key, label in ROWS:
        n = counts.get(key, 0)
        out.append(f"| {label} | {n} | {_names(lists.get(key) or []) if n else '-'} |")
    recent = sorted(days or [], key=lambda d: d.get("date", ""))[-7:]
    if recent:
        out += [
            "",
            "**Last 7 days:**",
            "",
            "| Date | New | Working again | Stopped working | Official channels working |",
            "|---|---:|---:|---:|---:|",
        ]
        for d in reversed(recent):
            c = d.get("counts") or {}
            out.append(
                f"| {d.get('date')} | {c.get('new_published', 0)} | {c.get('restored', 0)} | "
                f"{c.get('newly_quarantined', 0)} | {(d.get('lifecycle_counts') or {}).get('working', 0)} |"
            )
    out += [
        "",
        "New channels are found every day, every channel is checked three times a day, and channels that stop "
        "working leave the playlists automatically. Full details: [change report](reports/changes.md).",
        "",
    ]
    return out


def insert(readme: str, block: list[str], end_marker: str) -> str:
    """Put the dashboard just before the end marker of the generated numbers block."""
    if not block or end_marker not in readme:
        return readme
    i = readme.index(end_marker)
    return readme[:i] + "\n".join(block) + "\n" + readme[i:]
