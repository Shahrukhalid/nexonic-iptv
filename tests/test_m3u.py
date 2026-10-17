import pytest

from nexonic import m3u


def test_roundtrip():
    e = m3u.Entry('Ch "1"', "https://a.example.com/x.m3u8", {"tvg-id": "A.de", "group-title": "News, Germany"})
    text = m3u.render([e], {"x-nexonic-playlist": "Test"})
    assert text.startswith('#EXTM3U x-nexonic-playlist="Test"\n')
    parsed = m3u.parse(text)
    assert parsed[0].url == e.url and parsed[0].attrs["group-title"] == "News, Germany"


def test_control_characters_removed():
    e = m3u.Entry("Bad\nTitle", "https://a.example.com/x.m3u8", {"tvg-name": 'x"\r\ny'})
    text = m3u.render([e])
    assert text.count("\n") == 3  # header + extinf + url
    assert m3u.parse(text)[0].title == "Bad Title"


def test_refuses_bad_url():
    with pytest.raises(ValueError):
        m3u.Entry("x", "https://a.example.com/x\n#EXTINF:-1,evil", {}).render()


@pytest.mark.parametrize(
    "text",
    [
        "",
        "#EXTINF:-1,x\nhttps://a/x\n",
        "#EXTM3U\n#EXTINF:-1,x\n",
        "#EXTM3U\nhttps://a.example.com/x\n",
        "#EXTM3U\n#EXTINF:-1 no comma\nhttps://a.example.com/x\n",
        "#EXTM3U\n#EXTINF:abc,x\nhttps://a.example.com/x\n",
        "#EXTM3U\n#EXTINF:-1,x\nfile:///etc/passwd\n",
    ],
)
def test_malformed(text):
    with pytest.raises(m3u.M3UError):
        m3u.parse(text)


def test_repository_playlists_parse():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "playlists"
    files = list(root.rglob("*.m3u"))
    for f in files:
        assert m3u.parse(f.read_text(encoding="utf-8")), f
