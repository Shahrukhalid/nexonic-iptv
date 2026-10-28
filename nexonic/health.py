"""Nexonic Health Score and display status, derived only from recorded verification results.

Score (0-100), computed over results from the last ``WINDOW_DAYS`` days that are *scorable* (geo-restricted,
rate-limited, unknown, unsupported and not-tested results are neutral and excluded):

    score = 100 x ( 0.45 x recent_success_rate      # last 10 scorable checks
                  + 0.20 x streak_factor            # consecutive successes, capped at 5 -> 1.0
                  + 0.15 x latency_factor           # median manifest latency: <=500 ms -> 1.0, >=3000 ms -> 0.0
                  + 0.10 x media_factor             # share of successes where a media segment was read
                  + 0.10 x freshness_factor )       # last success <=24 h -> 1.0, <=72 h -> 0.5, older -> 0.0

A score is shown only with at least ``MIN_CHECKS`` scorable checks on at least ``MIN_DAYS`` distinct UTC days;
otherwise the label is ``NOT ENOUGH DATA``. Freshness is measured against the time of the latest verification run,
not the wall clock, so the output is reproducible.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass

from .status import FAILURES, CheckResult, Status
from .timeutil import parse_iso

WINDOW_DAYS = 14
MIN_CHECKS = 3
MIN_DAYS = 2
RECENT_N = 10
VERIFIED_FRESH_HOURS = 48
NOT_ENOUGH = "NOT ENOUGH DATA"


@dataclass
class Health:
    score: int | None
    grade: str
    display_status: (
        str  # verified-recently | previously-working | currently-failing | geo-restricted | not-tested | unknown
    )
    last_checked: str | None
    last_success: str | None
    last_status: str
    checks_in_window: int
    success_rate: float | None
    median_latency_ms: int | None

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def grade_for(score: int | None) -> str:
    if score is None:
        return NOT_ENOUGH
    if score >= 85:
        return "Excellent"
    if score >= 70:
        return "Good"
    if score >= 50:
        return "Fair"
    return "Poor"


def compute(results: list[CheckResult], reference: dt.datetime | None) -> Health:
    results = sorted(results, key=lambda r: r.checked_at)
    tested = [r for r in results if r.status is not Status.NOT_TESTED]
    if not tested or reference is None:
        return Health(None, NOT_ENOUGH, "not-tested", None, None, Status.NOT_TESTED.value, 0, None, None)
    last = tested[-1]
    successes = [r for r in tested if r.status is Status.VERIFIED_WORKING]
    last_success = successes[-1].checked_at if successes else None

    window_start = reference - dt.timedelta(days=WINDOW_DAYS)
    window = [r for r in tested if parse_iso(r.checked_at) >= window_start]
    scorable = [r for r in window if r.status is Status.VERIFIED_WORKING or r.status in FAILURES]

    # display status
    age_h = (reference - parse_iso(last.checked_at)).total_seconds() / 3600
    if last.status is Status.VERIFIED_WORKING and age_h <= VERIFIED_FRESH_HOURS:
        display = "verified-recently"
    elif last.status is Status.GEO_RESTRICTED:
        display = "geo-restricted"
    elif last.status in FAILURES:
        display = "previously-working" if last_success else "currently-failing"
        if last_success and _consecutive_failures(tested) >= 3:
            display = "currently-failing"
    elif last_success:
        display = "previously-working"
    else:
        display = "unknown"

    days = {r.checked_at[:10] for r in scorable}
    lat = [r.latency_ms for r in scorable if r.status is Status.VERIFIED_WORKING and r.latency_ms is not None]
    median_lat = int(statistics.median(lat)) if lat else None
    recent = scorable[-RECENT_N:]
    rate = (sum(r.status is Status.VERIFIED_WORKING for r in recent) / len(recent)) if recent else None

    if len(scorable) < MIN_CHECKS or len(days) < MIN_DAYS:
        return Health(
            None, NOT_ENOUGH, display, last.checked_at, last_success, last.status.value, len(scorable), rate, median_lat
        )

    streak = 0
    for r in reversed(scorable):
        if r.status is Status.VERIFIED_WORKING:
            streak += 1
        else:
            break
    streak_f = min(streak, 5) / 5
    if median_lat is None:
        lat_f = 0.0
    else:
        lat_f = max(0.0, min(1.0, (3000 - median_lat) / 2500))
    succ_window = [r for r in scorable if r.status is Status.VERIFIED_WORKING]
    media_f = (sum(1 for r in succ_window if r.media_readable) / len(succ_window)) if succ_window else 0.0
    if last_success:
        since = (reference - parse_iso(last_success)).total_seconds() / 3600
        fresh_f = 1.0 if since <= 24 else 0.5 if since <= 72 else 0.0
    else:
        fresh_f = 0.0
    score = round(100 * (0.45 * (rate or 0) + 0.20 * streak_f + 0.15 * lat_f + 0.10 * media_f + 0.10 * fresh_f))
    return Health(
        score,
        grade_for(score),
        display,
        last.checked_at,
        last_success,
        last.status.value,
        len(scorable),
        rate,
        median_lat,
    )


def _consecutive_failures(results: list[CheckResult]) -> int:
    n = 0
    for r in reversed(results):
        if r.status in FAILURES:
            n += 1
        elif r.status is Status.VERIFIED_WORKING:
            break
    return n


def is_verified_fresh(
    results: list[CheckResult], reference: dt.datetime | None, fresh_hours: float = VERIFIED_FRESH_HOURS
) -> bool:
    tested = sorted((r for r in results if r.status is not Status.NOT_TESTED), key=lambda r: r.checked_at)
    if not tested or reference is None:
        return False
    last = tested[-1]
    age_h = (reference - parse_iso(last.checked_at)).total_seconds() / 3600
    return last.status is Status.VERIFIED_WORKING and age_h <= fresh_hours


def is_stale(results: list[CheckResult], reference: dt.datetime | None, days: int = 7) -> bool:
    """A channel is stale when it failed its last 3+ checks and has not worked for ``days`` days."""
    tested = sorted((r for r in results if r.status is not Status.NOT_TESTED), key=lambda r: r.checked_at)
    if not tested or reference is None or _consecutive_failures(tested) < 3:
        return False
    successes = [r for r in tested if r.status is Status.VERIFIED_WORKING]
    if not successes:
        first = parse_iso(tested[0].checked_at)
        return (reference - first).days >= days
    return (reference - parse_iso(successes[-1].checked_at)).days >= days
