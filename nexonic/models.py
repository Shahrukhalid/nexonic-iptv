"""Channel record schema (Pydantic v2).

Source records live in ``data/{approved,pending,rejected}/*.yaml``. Verification results are *not* stored here;
they live in ``state/history.json`` and are joined in when exports are generated.
"""

from __future__ import annotations

import datetime as dt
import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .reference import CATEGORIES, LANGUAGES, countries

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
EPG_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.&+-]*(@[A-Za-z0-9]+)?$")
UNKNOWN = "unknown"


class ReviewStatus(str, Enum):
    APPROVED = "approved"
    PENDING = "pending"
    REJECTED = "rejected"


class AuthorizationBasis(str, Enum):
    OFFICIAL_BROADCASTER_STREAM = "official-broadcaster-stream"
    OFFICIAL_CDN_STREAM = "official-cdn-stream"
    PUBLIC_SECTOR_STREAM = "public-sector-stream"
    NONE = "none"  # only allowed for pending/rejected records


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Stream(_Strict):
    url: str = Field(min_length=10, max_length=2048)
    protocol: Literal["hls", "dash", "http"] = "hls"
    quality: str = UNKNOWN  # e.g. "1080p" — only when verified, otherwise "unknown"

    @field_validator("url")
    @classmethod
    def _no_whitespace(cls, v: str) -> str:
        if any(ch.isspace() for ch in v) or any(ord(ch) < 32 for ch in v):
            raise ValueError("stream URL must not contain whitespace or control characters")
        return v


class Source(_Strict):
    reference_url: str  # where the maintainer discovered the stream
    evidence_url: str  # broadcaster page offering the free live stream
    evidence_summary: str = Field(min_length=10)
    evidence_checked: dt.date | None = None  # date a maintainer opened evidence_url and confirmed it
    notes: str = ""
    # "manual": researched and reviewed by a maintainer. "automated-domain-match": admitted by
    # scripts/expand_catalog.py under strict owner-domain rules; published only after a successful live check.
    method: Literal["manual", "automated-domain-match"] = "manual"


class Geo(_Strict):
    restricted: bool | Literal["unknown"] = UNKNOWN
    regions: list[str] = Field(default_factory=list)  # ISO alpha-2 where the stream is intended to work

    @field_validator("regions")
    @classmethod
    def _regions(cls, v: list[str]) -> list[str]:
        known = countries()
        out = []
        for code in v:
            code = code.lower()
            if code not in known:
                raise ValueError(f"unknown region code {code!r}")
            out.append(code)
        return out


class Review(_Strict):
    status: ReviewStatus
    reviewer: str = Field(min_length=2)
    reviewed_at: dt.date
    authorization_basis: AuthorizationBasis
    adult_screening: Literal["pass", "fail", "uncertain"]
    notes: str = ""
    rejection_reason: str = ""


class Channel(_Strict):
    id: str
    name: str = Field(min_length=1, max_length=120)
    alt_names: list[str] = Field(default_factory=list)
    broadcaster: str = Field(min_length=2)
    country: str
    languages: list[str] = Field(min_length=1)
    categories: list[str] = Field(min_length=1)
    description: str = ""
    website: str
    stream: Stream
    source: Source
    epg_id: str | None = None
    logo: str | None = None  # only when the owner permits reuse
    geo: Geo = Field(default_factory=Geo)
    is_nsfw: bool = False
    first_discovered: dt.date
    review: Review

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not ID_RE.match(v):
            raise ValueError("id must be 3-64 chars of a-z, 0-9 and '-', not starting/ending with '-'")
        return v

    @field_validator("country")
    @classmethod
    def _country(cls, v: str) -> str:
        v = v.lower()
        if v not in countries():
            raise ValueError(f"country {v!r} is not an ISO 3166-1 alpha-2 code")
        return v

    @field_validator("languages")
    @classmethod
    def _languages(cls, v: list[str]) -> list[str]:
        out = []
        for code in v:
            code = code.lower()
            if code not in LANGUAGES:
                raise ValueError(f"language {code!r} is not in nexonic.reference.LANGUAGES (ISO 639-1)")
            if code in out:
                raise ValueError(f"duplicate language {code!r}")
            out.append(code)
        return out

    @field_validator("categories")
    @classmethod
    def _categories(cls, v: list[str]) -> list[str]:
        out = []
        for c in v:
            c = c.lower()
            if c not in CATEGORIES:
                raise ValueError(f"category {c!r} is not allowed (see nexonic.reference.CATEGORIES)")
            if c in out:
                raise ValueError(f"duplicate category {c!r}")
            out.append(c)
        return out

    @field_validator("epg_id")
    @classmethod
    def _epg(cls, v: str | None) -> str | None:
        if v is not None and not EPG_ID_RE.match(v):
            raise ValueError("epg_id contains unsupported characters")
        return v

    @model_validator(mode="after")
    def _review_consistency(self) -> Channel:
        r = self.review
        if r.status is ReviewStatus.APPROVED:
            if r.authorization_basis is AuthorizationBasis.NONE:
                raise ValueError("approved records need an authorization_basis")
            if r.adult_screening != "pass":
                raise ValueError("approved records must have adult_screening: pass")
            if self.is_nsfw:
                raise ValueError("adult-oriented channels can never be approved")
        if r.status is ReviewStatus.REJECTED and not r.rejection_reason:
            raise ValueError("rejected records need a rejection_reason")
        return self

    @property
    def automated(self) -> bool:
        return self.source.method == "automated-domain-match"

    @property
    def primary_category(self) -> str:
        return self.categories[0]
