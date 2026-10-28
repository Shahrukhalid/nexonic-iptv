"""Quality buckets (4k, 1080p, 720p, sd) from a resolution height, shared by the official and community tiers.

The official tier uses only the resolution the checker measured (master playlist variants, or the probed rendition of
a single-rendition stream). The community tier uses the measured value when there is one and otherwise the label the
source list carries.
"""

from __future__ import annotations

from .status import CheckResult, Status

QUALITY_BUCKETS = ("4k", "1080p", "720p", "sd")
BUCKET_LABELS = {"4k": "4K / 2160p", "1080p": "1080p", "720p": "720p", "sd": "SD (below 720p)"}


def quality_bucket(height: int) -> str | None:
    """Bucket of a height in pixels; None when the height is unknown (0)."""
    if height <= 0:
        return None
    if height >= 2160:
        return "4k"
    if height >= 1080:
        return "1080p"
    if height >= 720:
        return "720p"
    return "sd"


def height_of(label: str | None) -> int:
    """Height from a label such as ``720p``, ``1080i`` or ``1920x1080`` (0 when there is none)."""
    if not label:
        return 0
    digits = "".join(ch for ch in str(label).lower().split("x")[-1] if ch.isdigit())
    return int(digits) if digits and 100 <= int(digits) <= 4320 else 0


def measured_height(results: list[CheckResult]) -> int:
    """Height the checker recorded at the latest working check that recorded one (0 when it never did).

    ``max_resolution`` is the best variant of a master playlist. ``ffprobe_height`` is only trusted for streams
    without a master playlist, because FFprobe reads the lowest-bandwidth variant of a master.
    """
    for r in sorted(results, key=lambda r: r.checked_at, reverse=True):
        if r.status is not Status.VERIFIED_WORKING:
            continue
        h = height_of(r.details.get("max_resolution"))
        if not h and "variants" not in r.details:
            h = height_of(str(r.details.get("ffprobe_height") or ""))
        if h:
            return h
    return 0
