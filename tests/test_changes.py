import json

import yaml

from nexonic import changes, generate
from nexonic.config import ChangesConfig, QuarantineConfig
from nexonic.records import load_records
from nexonic.status import CheckResult, Status

Q = QuarantineConfig()
CFG = ChangesConfig()
W, U = Status.VERIFIED_WORKING, Status.UNAVAILABLE


def res(cid, status, day, hour=3, run=None):
    when = f"2026-10-{day:02d}T{hour:02d}:00:00Z"
    return CheckResult(
        cid, status, when, level=5, details={"run_id": run or f"run-{day}"}, error="boom" if status is U else ""
    )


def rec(record, cid, name, url, **kw):
    return record(id=cid, name=name, epg_id=cid.title().replace("-", "") + ".de", **{"stream.url": url}, **kw)


def auto(record, cid, name, url):
    r = rec(record, cid, name, url, **{"source.method": "automated-domain-match"})
    return r


def load(dataset, approved, pending):
    """Like the ``dataset`` fixture, but automated records go to data/approved/auto/ as they do in the repository."""
    manual = [r for r in approved if r["source"].get("method") != "automated-domain-match"]
    data = dataset(manual, pending)
    autos = [r for r in approved if r not in manual]
    folder = data / "approved" / "auto"
    if folder.exists():
        for old in folder.glob("*.yaml"):
            old.unlink()
    if autos:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "de.yaml").write_text(yaml.safe_dump({"channels": autos}), encoding="utf-8")
    return load_records(data)


def step(dataset, approved, pending, history, state):
    records = load(dataset, approved, pending)
    previous = {
        c: e["restored_at"]
        for c, e in ((state.get("current") or {}).get("channels") or {}).items()
        if e.get("restored_at")
    }
    plan = generate.plan(records, history, Q, previous)
    current = changes.build_snapshot(records, plan, state.get("current"))
    plan.last_metadata_update = {
        c: e["meta_changed_at"] for c, e in current["channels"].items() if "meta_changed_at" in e
    }
    baseline, new_state = changes.advance(state, current)
    report = changes.build_report(records, plan, history, baseline, current, None, CFG)
    return report, new_state, plan


EMPTY = {"schema": 1, "current": None, "previous": None}
U1, U2, U3, U4 = (f"https://live.example-broadcaster.de/{n}.m3u8" for n in "abcd")


def day1(record):
    approved = [
        rec(record, "a-news", "A News", U1),
        rec(record, "b-news", "B News", U2),
        auto(record, "c-auto", "C Auto", U3),
    ]
    pending = [
        record(
            id="p-one",
            name="P One",
            **{"stream.url": "https://x.example-broadcaster.de/p.m3u8"},
            **{"review.status": "pending", "review.authorization_basis": "none"},
        )
    ]
    pending[0]["review"]["adult_screening"] = "uncertain"
    history = {"a-news": [res("a-news", W, 20)], "b-news": [res("b-news", W, 20)]}
    return approved, pending, history


def test_first_run_creates_a_baseline_without_inventing_changes(dataset, record):
    approved, pending, history = day1(record)
    rep, state, _ = step(dataset, approved, pending, history, EMPTY)
    assert rep["baseline_available"] is False
    assert all(v == 0 for k, v in rep["counts"].items() if k in changes.LIST_KEYS)
    assert rep["counts"]["published"] == 2 and rep["counts"]["pending_authorization"] == 1
    assert state["current"]["reference_time"] == "2026-10-20T03:00:00Z"
    assert "Baseline snapshot created" in changes.summary_markdown(rep)


def test_second_day_reports_every_kind_of_change(dataset, record):
    approved, pending, history = day1(record)
    _, state, _ = step(dataset, approved, pending, history, EMPTY)

    approved2 = [
        rec(record, "a-news", "A News", U1),
        rec(record, "b-news", "B News", "https://live.example-broadcaster.de/b2.m3u8"),  # url changed
        auto(record, "c-auto", "C Auto", U3),  # passes its first check today
        auto(record, "e-auto", "E Auto", U4),  # new candidate, not yet checked
        rec(record, "f-dup", "F Dup", U1.replace("https", "http")),  # duplicate of a-news
    ]
    pending2 = [
        *pending,
        record(
            id="q-two",
            name="Q Two",
            **{
                "stream.url": "https://y.example-broadcaster.de/q.m3u8",
                "review.status": "pending",
                "review.authorization_basis": "none",
            },
        ),
    ]
    pending2[1]["review"]["adult_screening"] = "uncertain"
    history2 = {
        "a-news": [res("a-news", W, 20), res("a-news", U, 21, 1), res("a-news", U, 21, 9), res("a-news", U, 22)],
        "b-news": [res("b-news", W, 20), res("b-news", W, 22)],
        "c-auto": [res("c-auto", W, 22)],
        "f-dup": [res("f-dup", W, 22)],
    }
    rep, state2, plan = step(dataset, approved2, pending2, history2, state)
    lists = {k: [x["id"] for x in v] for k, v in rep["lists"].items()}
    assert rep["baseline_available"] and rep["baseline_reference_time"] == "2026-10-20T03:00:00Z"
    assert lists["new_published"] == ["c-auto"]
    assert sorted(lists["new_candidates"]) == ["e-auto", "f-dup", "q-two"]
    assert lists["updated"] == ["b-news"]
    assert rep["lists"]["updated"][0]["url_changed"] is True and rep["lists"]["updated"][0]["fields"] == ["stream_url"]
    assert lists["duplicates_removed"] == ["f-dup"]
    assert lists["newly_failing"] == ["a-news"] and rep["lists"]["newly_failing"][0]["error"] == "boom"
    assert lists["newly_quarantined"] == ["a-news"]
    assert lists["restored"] == [] and lists["removed"] == []
    assert rep["counts"]["pending_authorization"] == 2
    assert any("newly quarantined" in a for a in rep["attention"])
    assert rep["integrity"]["ok"]
    # b-news changed today, the others keep their original date
    assert plan.last_metadata_update["b-news"] == "2026-10-22"
    assert state2["previous"]["reference_time"] == "2026-10-20T03:00:00Z"


def test_restored_channel_is_reported_with_its_timestamp(dataset, record):
    approved, pending, _ = day1(record)
    failing = [res("a-news", W, 18), res("a-news", U, 19), res("a-news", U, 20, 1), res("a-news", U, 20, 5)]
    base = {"a-news": failing, "b-news": [res("b-news", W, 20)]}
    _, state, plan = step(dataset, approved[:2], pending, base, EMPTY)
    assert plan.lifecycle["a-news"].quarantined
    back = {"a-news": [*failing, res("a-news", W, 21)], "b-news": [res("b-news", W, 20), res("b-news", W, 21)]}
    rep, state2, plan2 = step(dataset, approved[:2], pending, back, state)
    assert [x["id"] for x in rep["lists"]["restored"]] == ["a-news"]
    assert rep["lists"]["restored"][0]["restored_at"] == "2026-10-21T03:00:00Z"
    assert state2["current"]["channels"]["a-news"]["restored_at"] == "2026-10-21T03:00:00Z"
    # the timestamp is carried forward after the history no longer shows the quarantine
    later = {"a-news": [res("a-news", W, 24)], "b-news": [res("b-news", W, 24)]}
    _, _, plan3 = step(dataset, approved[:2], pending, later, state2)
    assert plan3.lifecycle["a-news"].restored_at == "2026-10-21T03:00:00Z"


def test_rerunning_the_same_inputs_is_idempotent(dataset, record):
    approved, pending, history = day1(record)
    _, state, _ = step(dataset, approved, pending, history, EMPTY)
    history2 = {**history, "c-auto": [res("c-auto", W, 22)], "a-news": [res("a-news", W, 20), res("a-news", W, 22)]}
    rep1, state2, _ = step(dataset, approved, pending, history2, state)
    rep2, state3, _ = step(dataset, approved, pending, history2, state2)
    rep3, state4, _ = step(dataset, approved, pending, history2, state3)
    assert json.dumps(rep1, sort_keys=True) == json.dumps(rep2, sort_keys=True) == json.dumps(rep3, sort_keys=True)
    assert state2 == state3 == state4
    assert [x["id"] for x in rep3["lists"]["new_published"]] == ["c-auto"]


def test_unchanged_day_has_empty_change_lists(dataset, record):
    approved, pending, history = day1(record)
    _, state, _ = step(dataset, approved, pending, history, EMPTY)
    history2 = {k: [*v, res(k, W, 21)] for k, v in history.items()}
    rep, _, _ = step(dataset, approved, pending, history2, state)
    assert all(rep["counts"][k] == 0 for k in changes.LIST_KEYS)
    assert rep["attention"] == []


def test_attention_for_budget_exhaustion_and_mass_failure(dataset, record):
    approved = [
        rec(record, f"x-{i:02d}", f"X {i:02d}", f"https://live.example-broadcaster.de/{i}.m3u8") for i in range(24)
    ]
    history = {a["id"]: [res(a["id"], U, 22, run="run-22")] for a in approved}
    history["x-00"] = [res("x-00", Status.NOT_TESTED, 22, run="run-22")]
    rep, _, _ = step(dataset, approved, [], history, EMPTY)
    text = " ".join(rep["attention"])
    assert "not tested" in text and "network may be impaired" in text


def test_markdown_and_summary(dataset, record):
    approved, pending, history = day1(record)
    _, state, _ = step(dataset, approved, pending, history, EMPTY)
    history2 = {**history, "c-auto": [res("c-auto", W, 22)]}
    rep, _, _ = step(dataset, approved, pending, history2, state)
    md = changes.to_markdown(rep)
    assert "## New channels published (1)" in md and "C Auto" in md and "Pending authorization" in md
    assert "## Integrity" in md and "Needs attention" in md
    summary = changes.summary_markdown(rep)
    assert "Changes since the previous run" in summary and "reports/changes.md" in summary


def test_lists_are_capped_but_counts_are_not(dataset, record):
    approved, pending, history = day1(record)
    _, state, _ = step(dataset, approved, pending, history, EMPTY)
    extra = [
        auto(record, f"n-{i:02d}", f"N {i:02d}", f"https://live.example-broadcaster.de/n{i}.m3u8") for i in range(5)
    ]
    history = {**history, "a-news": [*history["a-news"], res("a-news", W, 21)]}
    records = load(dataset, [*approved, *extra], pending)
    plan = generate.plan(records, history, Q)
    cur = changes.build_snapshot(records, plan, state["current"])
    baseline, _ = changes.advance(state, cur)
    rep = changes.build_report(records, plan, history, baseline, cur, None, ChangesConfig(max_listed=2))
    assert rep["counts"]["new_candidates"] == 5 and len(rep["lists"]["new_candidates"]) == 2
    assert rep["truncated"] == {"new_candidates": 3}


def test_history_keeps_30_days_and_one_entry_per_date(tmp_path, dataset, record):
    approved, pending, history = day1(record)
    rep, _, _ = step(dataset, approved, pending, history, EMPTY)
    path = tmp_path / "state" / "change-history.json"
    for day in range(1, 36):
        r = {
            **rep,
            "reference_time": f"2026-09-{day:02d}T03:00:00Z" if day <= 30 else f"2026-10-{day - 30:02d}T03:00:00Z",
        }
        changes.update_history(path, r, CFG)
    days = json.loads(path.read_text())["days"]
    assert len(days) == 30
    assert days[0]["date"] == "2026-09-06" and days[-1]["date"] == "2026-10-05"
    # a second run on the same date replaces that day's entry and leaves the file otherwise unchanged
    again = {**rep, "reference_time": "2026-10-05T09:00:00Z", "attention": ["x"]}
    assert changes.update_history(path, again, CFG)
    days = json.loads(path.read_text())["days"]
    assert len(days) == 30 and days[-1]["attention"] == ["x"] and days[-1]["reference_time"].endswith("09:00:00Z")
    assert not changes.update_history(path, again, CFG)  # identical: not rewritten
    assert not changes.update_history(path, {**rep, "reference_time": None}, CFG)


def test_write_json_if_changed_is_stable(tmp_path):
    p = tmp_path / "s.json"
    assert changes.write_json_if_changed(p, {"b": 1, "a": 2})
    stamp = p.stat().st_mtime_ns
    assert not changes.write_json_if_changed(p, {"a": 2, "b": 1})
    assert p.stat().st_mtime_ns == stamp
