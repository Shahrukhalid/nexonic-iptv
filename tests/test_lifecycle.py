from nexonic import generate, lifecycle
from nexonic.config import QuarantineConfig
from nexonic.lifecycle import Lifecycle
from nexonic.records import load_records
from nexonic.status import CheckResult, Status
from nexonic.timeutil import parse_iso

Q = QuarantineConfig()  # 3 failures over 2 distinct days
REF = parse_iso("2026-10-20T12:00:00Z")


def r(status: Status, when: str, cid: str = "c") -> CheckResult:
    return CheckResult(cid, status, when, level=5 if status is Status.VERIFIED_WORKING else 1, error="e")


W, U, T, V, G, X, N = (
    Status.VERIFIED_WORKING,
    Status.UNAVAILABLE,
    Status.TIMEOUT,
    Status.INVALID_STREAM,
    Status.GEO_RESTRICTED,
    Status.AUTH_REQUIRED,
    Status.RATE_LIMITED,
)


def seq(*pairs):
    return [r(s, f"2026-10-{d:02d}T{h:02d}:00:00Z") for s, d, h in pairs]


def state(results, ref=REF):
    return lifecycle.evaluate(results, ref, Q).state


def test_no_results_is_unknown():
    assert state([]) is Lifecycle.UNKNOWN
    assert state([r(Status.NOT_TESTED, "2026-10-19T00:00:00Z")]) is Lifecycle.UNKNOWN


def test_working_when_only_successes_in_window():
    assert state(seq((W, 18, 3), (W, 19, 3), (W, 20, 3))) is Lifecycle.WORKING


def test_intermittent_on_mixed_results_in_window():
    assert state(seq((W, 17, 3), (U, 18, 3), (W, 19, 3), (W, 20, 3))) is Lifecycle.INTERMITTENT


def test_old_failures_outside_the_window_do_not_count():
    assert state(seq((U, 1, 3), (W, 18, 3), (W, 19, 3))) is Lifecycle.WORKING


def test_unreachable_and_invalid():
    assert state(seq((U, 19, 3), (T, 20, 3))) is Lifecycle.UNREACHABLE
    assert state(seq((W, 5, 3), (V, 19, 3), (V, 20, 3))) is Lifecycle.INVALID


def test_restricted_for_geo_and_auth():
    assert state(seq((W, 18, 3), (G, 20, 3))) is Lifecycle.RESTRICTED
    assert state(seq((W, 18, 3), (X, 20, 3))) is Lifecycle.RESTRICTED


def test_neutral_last_result_falls_back_to_scorable_history():
    assert state(seq((W, 18, 3), (W, 19, 3), (N, 20, 3))) is Lifecycle.WORKING
    assert state(seq((N, 20, 3))) is Lifecycle.UNKNOWN
    assert state(seq((W, 19, 3), (Status.UNSUPPORTED, 20, 3))) is Lifecycle.UNKNOWN


def test_quarantine_needs_n_failures_across_m_days():
    same_day = seq((W, 17, 3), (U, 20, 1), (U, 20, 2), (U, 20, 3))
    assert not lifecycle.is_quarantined(same_day, Q)  # 3 failures but one day
    two_days = seq((W, 17, 3), (U, 19, 23), (U, 20, 1), (U, 20, 2))
    assert lifecycle.is_quarantined(two_days, Q)
    assert not lifecycle.is_quarantined(seq((W, 17, 3), (U, 19, 3), (U, 20, 3)), Q)  # only 2 failures


def test_neutral_results_neither_count_nor_break_a_failure_run():
    res = seq((W, 15, 3), (U, 18, 3), (G, 19, 3), (U, 19, 4), (N, 20, 1), (U, 20, 2))
    assert lifecycle.is_quarantined(res, Q)


def test_a_success_breaks_the_run_and_restores():
    failing = seq((W, 15, 3), (U, 17, 3), (U, 18, 3), (U, 19, 3))
    assert lifecycle.is_quarantined(failing, Q)
    back = failing + seq((W, 20, 3))
    info = lifecycle.evaluate(back, REF, Q)
    assert not info.quarantined
    assert info.restored_at == "2026-10-20T03:00:00Z"


def test_quarantined_state_is_not_reported_as_intermittent():
    res = seq((W, 15, 3), (U, 18, 3), (U, 19, 3), (U, 20, 3))
    info = lifecycle.evaluate(res, REF, Q)
    assert info.quarantined and info.state is Lifecycle.UNREACHABLE
    assert info.quarantined_since == "2026-10-20T03:00:00Z"


def test_restored_at_survives_history_trimming():
    res = seq((W, 19, 3), (W, 20, 3))
    assert lifecycle.evaluate(res, REF, Q, previous_restored_at="2026-10-10T03:00:00Z").restored_at == (
        "2026-10-10T03:00:00Z"
    )
    # a newer restore found in the history wins
    res = seq((U, 14, 3), (U, 15, 3), (U, 16, 3), (W, 17, 3))
    assert lifecycle.evaluate(res, REF, Q, previous_restored_at="2026-10-10T03:00:00Z").restored_at == (
        "2026-10-17T03:00:00Z"
    )


def test_verified_playlist_keeps_a_recently_working_channel_until_quarantined():
    one_miss = seq((W, 18, 3), (W, 19, 3), (U, 20, 3))
    assert lifecycle.in_verified(one_miss, REF, Q)
    quarantined = seq((W, 18, 20), (U, 19, 3), (U, 19, 9), (U, 20, 3))
    assert not lifecycle.in_verified(quarantined, REF, Q)
    too_old = seq((W, 10, 3), (U, 20, 3))
    assert not lifecycle.in_verified(too_old, REF, Q)
    assert not lifecycle.in_verified([], REF, Q)
    assert lifecycle.in_verified(seq((W, 20, 3)), REF, Q)


def test_old_behaviour_is_available_through_config():
    strict = QuarantineConfig(consecutive_failures=1, distinct_days=1)
    one_miss = seq((W, 18, 3), (W, 19, 3), (U, 20, 3))
    assert not lifecycle.in_verified(one_miss, REF, strict)


# ---- integration with the generator -------------------------------------------------------------------------------


def _plan(dataset, record, results):
    res = load_records(dataset([record(id="a-news", name="A News", epg_id="ANews.de")]))
    return generate.plan(res, {"a-news": results}, Q)


def test_generator_uses_quarantine_for_verified_membership(dataset, record):
    ok_then_miss = seq((W, 19, 3), (U, 20, 3))
    p = _plan(dataset, record, ok_then_miss)
    assert [c.id for c in p.published] == ["a-news"]
    assert "a-news" in p.verified_ids
    assert p.lifecycle["a-news"].state is Lifecycle.INTERMITTENT

    failing = seq((W, 17, 3), (U, 19, 3), (U, 19, 9), (U, 20, 3))
    p = _plan(dataset, record, failing)
    assert "a-news" not in p.verified_ids  # quarantined: left the verified playlist
    assert [c.id for c in p.published] == ["a-news"]  # still in the full playlist until it is stale
    assert p.lifecycle["a-news"].quarantined

    restored = failing + seq((W, 21, 3))
    p = _plan(dataset, record, restored)
    assert "a-news" in p.verified_ids
    assert p.lifecycle["a-news"].restored_at == "2026-10-21T03:00:00Z"


def test_existing_stale_exclusion_is_unchanged(dataset, record):
    stale = seq((W, 1, 3), (U, 17, 3), (U, 18, 3), (U, 19, 3), (U, 20, 3))
    p = _plan(dataset, record, stale)
    assert p.published == []
    assert p.excluded[0]["reasons"][0].startswith("stale")
    assert p.excluded[0]["lifecycle"] == "unreachable"


def test_channel_export_carries_lifecycle_and_provenance(dataset, record):
    p = _plan(dataset, record, seq((W, 19, 3), (W, 20, 3)))
    p.last_metadata_update = {"a-news": "2026-10-20"}
    row = generate.channel_export(p)[0]
    assert row["lifecycle"] == "working"
    assert row["quarantined"] is False and row["restored_at"] is None
    assert row["last_validated"] == "2026-10-20T03:00:00Z"
    assert row["last_metadata_update"] == "2026-10-20"
    prov = row["provenance"]
    assert prov["discovery_method"] == "manual"
    assert prov["authorization_basis"] == "official-broadcaster-stream"
    assert prov["source_reference"].startswith("https://") and prov["evidence_url"].startswith("https://")
    assert prov["first_discovered"] == "2026-10-17"
    # existing fields are untouched
    for key in ("evidence_url", "authorization_basis", "admission", "in_verified_playlist", "health", "stream_url"):
        assert key in row
