"""Tokenized stream URLs never reach the community tier: the generation-time rules drop them from any catalogue."""

from nexonic import community as c


def _stream(sid, url):
    return c.CStream(f"{sid}~1", f"{sid}.de", "", sid, url, "de", ["de"], ["news"], 0, "", 0, "iptv-org")


def test_tokenized_urls_are_dropped_at_generation_time():
    ok = _stream("A", "https://a.test/i.m3u8?id=7")
    bad = _stream("B", "https://b.test/i.m3u8?auth_key=1-0-0-abc")
    jwt = _stream("C", "https://c.test/i.m3u8?akes=eyJ0eXAiOiJKV1Qi.eyJzdWIiOiIx.sig")
    kept, removed = c.apply_tier_rules([ok, bad, jwt], c.OfficialContext(), c.Exclusions())
    assert kept == [ok] and removed == {"url-policy-token": 2}


def test_plan_community_leaves_tokenized_streams_out_of_every_playlist():
    ok = _stream("A", "https://a.test/i.m3u8")
    bad = _stream("B", "https://b.test/i.m3u8?play_token=abc")
    cat = {"schema": 1, "built_at": "2026-10-28T00:00:00Z", "columns": c.COLUMNS, "streams": [list(ok), list(bad)]}
    cfg = c.CommunityConfig()
    plan = c.plan_community(cat, {}, c.OfficialContext(), c.Exclusions(), cfg)
    text = "".join(plan.files.values())
    assert ok.url in text and "play_token" not in text
    assert plan.stats["removed_at_generation"] == {"url-policy-token": 1}
