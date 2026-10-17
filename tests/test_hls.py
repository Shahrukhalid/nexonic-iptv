import pytest

from nexonic import hls

MASTER = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2"
hi/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360
lo/index.m3u8
"""
MEDIA = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:6
#EXT-X-MEDIA-SEQUENCE:100
#EXTINF:6.0,
seg100.ts
#EXTINF:6.0,
https://cdn.example.com/seg101.ts
"""


def test_master_playlist():
    p = hls.parse_hls(MASTER, "https://live.example.com/x/master.m3u8")
    assert p.kind == "master" and len(p.variants) == 2
    v = hls.choose_variant(p.variants)
    assert v.uri == "https://live.example.com/x/lo/index.m3u8"
    assert hls.best_resolution(p.variants) == "1080p"


def test_media_playlist():
    p = hls.parse_hls(MEDIA, "https://live.example.com/x/lo/index.m3u8")
    assert p.kind == "media" and p.target_duration == 6
    assert p.segments == ["https://live.example.com/x/lo/seg100.ts", "https://cdn.example.com/seg101.ts"]
    assert not p.endlist and p.drm is None


@pytest.mark.parametrize(
    "body,msg",
    [
        ("<html>not a playlist</html>", "EXTM3U"),
        ("#EXTM3U\n#EXTINF:6,\nseg.ts\n", "TARGETDURATION"),
        ("#EXTM3U\n#EXT-X-TARGETDURATION:6\n", "no segments"),
        ("#EXTM3U\n#EXT-X-TARGETDURATION:abc\n#EXTINF:6,\na.ts\n", "TARGETDURATION"),
    ],
)
def test_invalid_manifests(body, msg):
    with pytest.raises(hls.ManifestError, match=msg):
        hls.parse_hls(body, "https://x.example.com/a.m3u8")


def test_drm_detection():
    body = MEDIA.replace(
        "#EXT-X-MEDIA-SEQUENCE:100",
        '#EXT-X-KEY:METHOD=SAMPLE-AES,URI="skd://k",KEYFORMAT="com.apple.streamingkeydelivery"',
    )
    p = hls.parse_hls(body, "https://x.example.com/a.m3u8")
    assert p.drm and p.encrypted


def test_aes128_is_encrypted_not_drm():
    body = MEDIA.replace("#EXT-X-MEDIA-SEQUENCE:100", '#EXT-X-KEY:METHOD=AES-128,URI="key.bin"')
    p = hls.parse_hls(body, "https://x.example.com/a.m3u8")
    assert p.encrypted and p.drm is None


def test_bom_and_crlf():
    p = hls.parse_hls("﻿" + MEDIA.replace("\n", "\r\n"), "https://x.example.com/a.m3u8")
    assert len(p.segments) == 2


def test_sniff_media():
    ts = bytes([0x47] + [0] * 187 + [0x47] + [0] * 10)
    assert hls.sniff_media(ts) == "mpeg-ts"
    assert hls.sniff_media(b"\x00\x00\x00\x18ftypiso6") == "fmp4"
    assert hls.sniff_media(b"ID3\x04") is not None
    assert hls.sniff_media(b"<html>") is None


def test_dash_rejects_entities():
    with pytest.raises(hls.ManifestError):
        hls.inspect_dash('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><MPD></MPD>')
    assert hls.inspect_dash('<MPD type="dynamic"><ContentProtection/></MPD>')["drm"]
