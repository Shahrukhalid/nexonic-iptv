"""Adult-content exclusion: known adult-oriented sample records must never pass."""

import pytest

from nexonic.models import Channel
from nexonic.moderation import Decision, publication_gate, screen


def ch(record, **kw):
    return Channel.model_validate(record(**kw))


ADULT_SAMPLES = [
    {"name": "XXX Hot Channel"},
    {"name": "P0rn TV"},  # leetspeak
    {"name": "Erotik Kanal"},
    {"name": "Canal Adulto"},
    {"name": "Sexy Nights TV"},
    {"name": "Late Show 18+"},
    {"name": "Club +18"},
    {"alt_names": ["Playboy TV Latin"]},
    {"description": "Hardcore programming for adults"},
    {"broadcaster": "Brazzers Media"},
    {"epg_id": "21Sextury.us"},  # on iptv-org's NSFW blocklist
    {"epg_id": "40Plus.uk"},
    {"name": "HotSex Live"},  # compound word
    {"stream.url": "https://cdn.adult.example.com/live/master.m3u8"},
    {"stream.url": "https://live.example.xxx/master.m3u8"},
]


@pytest.mark.parametrize("override", ADULT_SAMPLES)
def test_adult_samples_rejected(record, override):
    res = screen(ch(record, **override))
    assert res.decision is Decision.REJECT, res.reasons
    ok, _ = publication_gate(ch(record, **override))
    assert not ok


@pytest.mark.parametrize("name", ["Hot Movies", "Private Lounge", "Passion TV", "After Dark TV", "Babes Channel"])
def test_ambiguous_names_quarantined(record, name):
    res = screen(ch(record, name=name))
    assert res.decision is Decision.QUARANTINE, res.reasons
    assert not publication_gate(ch(record, name=name))[0]


def test_nsfw_name_from_iptv_org_quarantined(record):
    # "Brazzers TV Europe" style exact names in the iptv-org list are quarantined even without strong terms
    res = screen(ch(record, name="Silk"))
    assert res.decision is Decision.QUARANTINE


@pytest.mark.parametrize(
    "name",
    [
        "BBC Sussex",
        "Essex Live",
        "Middlesex News",
        "Deutsche Welle",
        "Red Bull TV",
        "France 24",
        "3sat",
        "KiKA",
        "TRT Çocuk",
    ],
)
def test_innocent_names_pass(record, name):
    assert screen(ch(record, name=name)).decision is Decision.PASS


def test_uncertain_human_screening_blocks(record):
    rec = record()
    rec["review"]["status"] = "pending"
    rec["review"]["adult_screening"] = "uncertain"
    c = Channel.model_validate(rec)
    assert screen(c).decision is Decision.QUARANTINE
    assert not publication_gate(c)[0]


def test_strong_terms_cannot_be_allowlisted(record, monkeypatch):
    from nexonic import moderation

    lists = dict(moderation._local_lists())
    lists["weak_allow"] = {"example-news": {"porn", "hot"}}
    monkeypatch.setattr(moderation, "_local_lists", lambda: lists)
    assert screen(ch(record, name="Porn Hot")).decision is Decision.REJECT


def test_weak_allowlist_override(record, monkeypatch):
    from nexonic import moderation

    lists = dict(moderation._local_lists())
    lists["weak_allow"] = {"example-news": {"love"}}
    monkeypatch.setattr(moderation, "_local_lists", lambda: lists)
    assert screen(ch(record, name="Love Island News")).decision is Decision.PASS


def test_every_repository_approved_record_passes():
    from nexonic.records import load_records

    for c in load_records().approved:
        ok, problems = publication_gate(c)
        assert ok, (c.id, problems)
