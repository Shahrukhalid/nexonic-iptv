"""Extended M3U writing and strict parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_ATTR = re.compile(r'([a-zA-Z0-9-]+)="([^"]*)"')
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def clean_attr(value: str) -> str:
    """Attribute values are quoted with ``"``; quotes and control characters cannot be escaped in M3U,
    so they are replaced."""
    return _CTRL.sub(" ", value).replace('"', "'").strip()


def clean_title(value: str) -> str:
    return _CTRL.sub(" ", value).strip()


@dataclass
class Entry:
    title: str
    url: str
    attrs: dict[str, str] = field(default_factory=dict)
    duration: str = "-1"

    def render(self) -> str:
        attr_text = "".join(f' {k}="{clean_attr(v)}"' for k, v in self.attrs.items() if v)
        url = self.url.strip()
        if _CTRL.search(url) or " " in url:
            raise ValueError(f"refusing to write URL with whitespace/control characters: {url!r}")
        return f"#EXTINF:{self.duration}{attr_text},{clean_title(self.title)}\n{url}\n"


def render(entries: list[Entry], header_attrs: dict[str, str] | None = None) -> str:
    head = "#EXTM3U" + "".join(f' {k}="{clean_attr(v)}"' for k, v in (header_attrs or {}).items()) + "\n"
    return head + "".join(e.render() for e in entries)


class M3UError(ValueError):
    pass


def _split_extinf(rest: str) -> tuple[str, str, str]:
    """Split ``duration attrs,title`` at the first comma that is not inside a quoted attribute value."""
    quoted = False
    for i, ch in enumerate(rest):
        if ch == '"':
            quoted = not quoted
        elif ch == "," and not quoted:
            return rest[:i], ",", rest[i + 1 :]
    return rest, "", ""


def parse(text: str) -> list[Entry]:
    """Parse an extended M3U strictly: header first, every #EXTINF followed by exactly one URL line."""
    lines = text.splitlines()
    if not lines or not lines[0].startswith("#EXTM3U"):
        raise M3UError("missing #EXTM3U header")
    entries: list[Entry] = []
    pending: Entry | None = None
    for n, raw in enumerate(lines[1:], start=2):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTINF:"):
            if pending is not None:
                raise M3UError(f"line {n}: #EXTINF without URL on previous entry")
            meta, sep, title = _split_extinf(line[len("#EXTINF:") :])
            if not sep:
                raise M3UError(f"line {n}: #EXTINF missing ',' before title")
            duration = meta.split(" ", 1)[0]
            if not re.fullmatch(r"-?\d+(\.\d+)?", duration):
                raise M3UError(f"line {n}: invalid duration {duration!r}")
            pending = Entry(title=title.strip(), url="", attrs=dict(_ATTR.findall(meta)), duration=duration)
            continue
        if line.startswith("#"):
            continue
        if pending is None:
            raise M3UError(f"line {n}: URL without #EXTINF")
        if not re.match(r"^https?://", line):
            raise M3UError(f"line {n}: entry URL must be http(s)")
        pending.url = line
        entries.append(pending)
        pending = None
    if pending is not None:
        raise M3UError("last #EXTINF has no URL")
    return entries
