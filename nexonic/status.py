"""Verification outcomes and the result record."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class Status(str, Enum):
    VERIFIED_WORKING = "VERIFIED_WORKING"
    UNAVAILABLE = "UNAVAILABLE"
    GEO_RESTRICTED = "GEO_RESTRICTED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    INVALID_STREAM = "INVALID_STREAM"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"
    NOT_TESTED = "NOT_TESTED"


# Outcomes that count as a failed attempt for reliability scoring.
FAILURES = {Status.UNAVAILABLE, Status.TIMEOUT, Status.INVALID_STREAM, Status.AUTH_REQUIRED}
# Outcomes that say nothing about reliability from the checker's location.
NEUTRAL = {Status.GEO_RESTRICTED, Status.RATE_LIMITED, Status.UNKNOWN, Status.NOT_TESTED, Status.UNSUPPORTED}


@dataclass
class CheckResult:
    channel_id: str
    status: Status
    checked_at: str  # ISO 8601 UTC, e.g. 2026-10-17T03:17:00Z
    level: int = 0  # highest verification level passed (0-6)
    http_status: int | None = None
    latency_ms: int | None = None  # time to first manifest response
    error: str = ""
    media_readable: bool | None = None
    details: dict = field(default_factory=dict)
    method: str = "httpx"
    location: str = "unknown"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> CheckResult:
        d = dict(d)
        d["status"] = Status(d["status"])
        return cls(**d)
