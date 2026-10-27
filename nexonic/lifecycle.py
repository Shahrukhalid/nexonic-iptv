"""Per-channel lifecycle derived only from recorded verification results.

States (``Lifecycle``): working, intermittent, unreachable, invalid, restricted, unknown.

    restricted    last check was GEO_RESTRICTED or AUTH_REQUIRED (says nothing about the stream itself)
    working       VERIFIED_WORKING in the window, no failures in the window
    intermittent  both successes and failures inside the window (and not quarantined)
    unreachable   failing with UNAVAILABLE / TIMEOUT
    invalid       failing with INVALID_STREAM
    unknown       no scorable result in the window, or the last outcome was UNSUPPORTED

Quarantine: a channel is quarantined after ``consecutive_failures`` failed checks in a row (neutral outcomes such as
GEO_RESTRICTED or RATE_LIMITED neither count nor break the run) that span at least ``distinct_days`` UTC days. One
VERIFIED_WORKING result restores it and records ``restored_at``. A channel that is not quarantined keeps its place
in the verified playlist while it still has a success inside the 48 hour freshness window, so a single bad night
does not remove it.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum

from .config import QuarantineConfig
from .health import VERIFIED_FRESH_HOURS, is_verified_fresh
from .status import FAILURES, CheckResult, Status
from .timeutil import parse_iso


class Lifecycle(str, Enum):
    WORKING = "working"
    INTERMITTENT = "intermittent"
    UNREACHABLE = "unreachable"
    INVALID = "invalid"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


@dataclass
class LifecycleInfo:
    state: Lifecycle
    quarantined: bool = False
    quarantined_since: str | None = None
    restored_at: str | None = None
    last_validated: str | None = None
    consecutive_failures: int = 0
    failure_days: int = 0

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["state"] = self.state.value
        return d


def _tested(results: list[CheckResult]) -> list[CheckResult]:
    return sorted((r for r in results if r.status is not Status.NOT_TESTED), key=lambda r: r.checked_at)


def trailing_failures(tested: list[CheckResult]) -> tuple[int, int]:
    """(consecutive failures, distinct UTC days they span), ignoring neutral outcomes."""
    n, days = 0, set()
    for r in reversed(tested):
        if r.status in FAILURES:
            n += 1
            days.add(r.checked_at[:10])
        elif r.status is Status.VERIFIED_WORKING:
            break
    return n, len(days)


def _walk(tested: list[CheckResult], cfg: QuarantineConfig) -> tuple[bool, str | None, str | None]:
    """Replay the history: (quarantined now, quarantined_since, latest restored_at seen in the history)."""
    fails, days = 0, set()
    since = restored = None
    quarantined = False
    for r in tested:
        if r.status in FAILURES:
            fails += 1
            days.add(r.checked_at[:10])
            if not quarantined and fails >= cfg.consecutive_failures and len(days) >= cfg.distinct_days:
                quarantined, since = True, r.checked_at
        elif r.status is Status.VERIFIED_WORKING:
            if quarantined:
                restored = r.checked_at
            fails, days, quarantined, since = 0, set(), False, None
    return quarantined, since, restored


def is_quarantined(results: list[CheckResult], cfg: QuarantineConfig) -> bool:
    return _walk(_tested(results), cfg)[0]


def in_verified(results: list[CheckResult], reference: dt.datetime | None, cfg: QuarantineConfig) -> bool:
    """Membership of verified.m3u: working at the latest check, or a recent success and not yet quarantined."""
    if is_verified_fresh(results, reference):
        return True
    tested = _tested(results)
    if not tested or reference is None or tested[-1].status not in FAILURES:
        return False
    successes = [r for r in tested if r.status is Status.VERIFIED_WORKING]
    if not successes:
        return False
    age_h = (reference - parse_iso(successes[-1].checked_at)).total_seconds() / 3600
    return age_h <= VERIFIED_FRESH_HOURS and not is_quarantined(results, cfg)


def evaluate(
    results: list[CheckResult],
    reference: dt.datetime | None,
    cfg: QuarantineConfig,
    previous_restored_at: str | None = None,
) -> LifecycleInfo:
    tested = _tested(results)
    quarantined, since, restored = _walk(tested, cfg)
    restored_at = max(filter(None, (restored, previous_restored_at)), default=None)
    n, days = trailing_failures(tested)
    info = LifecycleInfo(
        Lifecycle.UNKNOWN,
        quarantined,
        since,
        restored_at,
        tested[-1].checked_at if tested else None,
        n,
        days,
    )
    if not tested or reference is None:
        return info
    last = tested[-1]
    if last.status in (Status.GEO_RESTRICTED, Status.AUTH_REQUIRED):
        info.state = Lifecycle.RESTRICTED
        return info
    if last.status is Status.UNSUPPORTED:
        return info
    start = reference - dt.timedelta(days=cfg.intermittent_window_days)
    window = [
        r
        for r in tested
        if parse_iso(r.checked_at) >= start and (r.status is Status.VERIFIED_WORKING or r.status in FAILURES)
    ]
    if not window:
        return info
    ok = any(r.status is Status.VERIFIED_WORKING for r in window)
    bad = [r for r in window if r.status in FAILURES]
    if ok and bad and not quarantined:
        info.state = Lifecycle.INTERMITTENT
    elif ok and not bad:
        info.state = Lifecycle.WORKING
    elif bad:
        info.state = Lifecycle.INVALID if bad[-1].status is Status.INVALID_STREAM else Lifecycle.UNREACHABLE
    return info
