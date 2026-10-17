"""Minimal, defensive HLS (RFC 8216) and DASH manifest inspection.

Only what the verifier needs: classify master vs media playlists, list variants, list segments, detect DRM.
Nothing from a manifest is ever executed or written to disk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

_ATTR_RE = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^",]*)')
DRM_KEYFORMATS = (
    "com.apple.streamingkeydelivery",  # FairPlay
    "urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed",  # Widevine
    "com.microsoft.playready",
    "urn:uuid:9a04f079-9840-4286-ab92-e65be0885f95",  # PlayReady
)


class ManifestError(ValueError):
    pass


@dataclass
class Variant:
    uri: str
    bandwidth: int = 0
    resolution: str | None = None
    codecs: str | None = None


@dataclass
class HlsPlaylist:
    kind: str  # "master" | "media"
    variants: list[Variant] = field(default_factory=list)
    segments: list[str] = field(default_factory=list)
    target_duration: float | None = None
    drm: str | None = None
    encrypted: bool = False
    endlist: bool = False


def parse_attributes(text: str) -> dict[str, str]:
    return {k: v.strip('"') for k, v in _ATTR_RE.findall(text)}


def looks_like_hls(body: str) -> bool:
    return body.lstrip("﻿ \r\n\t").startswith("#EXTM3U")


def parse_hls(body: str, base_url: str) -> HlsPlaylist:
    if not looks_like_hls(body):
        raise ManifestError("body does not start with #EXTM3U")
    lines = [ln.strip() for ln in body.lstrip("﻿").splitlines()]
    variants: list[Variant] = []
    segments: list[str] = []
    target: float | None = None
    drm = None
    encrypted = False
    endlist = False
    pending_variant: dict[str, str] | None = None
    pending_segment = False
    for ln in lines:
        if not ln:
            continue
        if ln.startswith("#EXT-X-STREAM-INF:"):
            pending_variant = parse_attributes(ln.split(":", 1)[1])
            continue
        if ln.startswith("#EXT-X-TARGETDURATION:"):
            try:
                target = float(ln.split(":", 1)[1])
            except ValueError as exc:
                raise ManifestError("invalid EXT-X-TARGETDURATION") from exc
            continue
        if ln.startswith(("#EXT-X-KEY:", "#EXT-X-SESSION-KEY:")):
            attrs = parse_attributes(ln.split(":", 1)[1])
            method = attrs.get("METHOD", "").upper()
            keyformat = attrs.get("KEYFORMAT", "").lower()
            if method and method != "NONE":
                encrypted = True
            if method.startswith("SAMPLE-AES") or method == "ISO-23001-7" or keyformat in DRM_KEYFORMATS:
                drm = f"{method or 'unknown'} {keyformat}".strip()
            continue
        if ln.startswith("#EXTINF:"):
            pending_segment = True
            continue
        if ln.startswith("#EXT-X-ENDLIST"):
            endlist = True
            continue
        if ln.startswith("#"):
            continue
        uri = urljoin(base_url, ln)
        if pending_variant is not None:
            try:
                bw = int(pending_variant.get("BANDWIDTH", "0"))
            except ValueError:
                bw = 0
            variants.append(Variant(uri, bw, pending_variant.get("RESOLUTION"), pending_variant.get("CODECS")))
            pending_variant = None
        elif pending_segment:
            segments.append(uri)
            pending_segment = False
    if variants:
        return HlsPlaylist("master", variants=variants, drm=drm, encrypted=encrypted)
    if target is None:
        raise ManifestError("media playlist without EXT-X-TARGETDURATION")
    if not segments:
        raise ManifestError("media playlist has no segments")
    return HlsPlaylist(
        "media", segments=segments, target_duration=target, drm=drm, encrypted=encrypted, endlist=endlist
    )


def choose_variant(variants: list[Variant]) -> Variant:
    """Pick the lowest-bandwidth variant: it is enough to prove the stream works and costs the host least."""
    with_bw = [v for v in variants if v.bandwidth > 0]
    if with_bw:
        return min(with_bw, key=lambda v: (v.bandwidth, v.uri))
    return variants[0]


def best_resolution(variants: list[Variant]) -> str | None:
    best = None
    best_px = 0
    for v in variants:
        if v.resolution and "x" in v.resolution:
            try:
                w, h = (int(x) for x in v.resolution.lower().split("x", 1))
            except ValueError:
                continue
            if w * h > best_px:
                best_px, best = w * h, f"{h}p"
    return best


def inspect_dash(body: str) -> dict:
    """Very small DASH check: MPD root, DRM detection. Returns details or raises ManifestError."""
    head = body.lstrip()[:4096]
    if "<MPD" not in head and "<mpd" not in head:
        raise ManifestError("not an MPD document")
    if "<!ENTITY" in body or "<!DOCTYPE" in body:
        raise ManifestError("MPD contains DTD/entities; refusing to process")
    drm = "ContentProtection" in body
    return {"drm": drm, "dynamic": 'type="dynamic"' in body}


def sniff_media(chunk: bytes) -> str | None:
    """Identify a media segment container from its first bytes."""
    if len(chunk) >= 189 and chunk[0] == 0x47 and chunk[188] == 0x47:
        return "mpeg-ts"
    if len(chunk) >= 1 and chunk[0] == 0x47 and len(chunk) < 189:
        return "mpeg-ts (short read)"
    if len(chunk) >= 8 and chunk[4:8] in (b"ftyp", b"styp", b"moof", b"sidx", b"emsg"):
        return "fmp4"
    if chunk[:3] == b"ID3":
        return "id3-tagged (packed audio or ts)"
    if len(chunk) >= 2 and chunk[0] == 0xFF and (chunk[1] & 0xF6) == 0xF0:
        return "adts-aac"
    return None
