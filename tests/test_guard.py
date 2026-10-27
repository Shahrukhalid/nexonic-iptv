import json
import subprocess

import pytest
from conftest import load_script

from nexonic import guard
from nexonic.config import GuardConfig

validate = load_script("validate")


def index(published: int, verified: int | None = None) -> dict:
    items = [{"path": "playlists/all.m3u", "kind": "global", "count": published}]
    if verified is not None:
        items.append({"path": "playlists/verified.m3u", "kind": "verified", "count": verified})
    return {"playlists": items}


CFG = GuardConfig()


def test_small_changes_pass():
    assert guard.evaluate(index(500, 450), index(480, 440), CFG, override=False).ok
    assert guard.evaluate(index(500, 450), index(520, 450), CFG, override=False).ok


def test_drop_over_percentage_fails_with_clear_text():
    res = guard.evaluate(index(500), index(400), CFG, override=False)
    assert not res.ok
    assert "fell from 500 to 400" in res.violations[0] and "-20.0%" in res.violations[0]
    assert "limit 10%" in res.violations[0]


def test_drop_exactly_at_limit_passes():
    assert guard.evaluate(index(500), index(450), CFG, override=False).ok


def test_too_many_additions_fail():
    res = guard.evaluate(index(500), index(500 + CFG.max_added + 1), CFG, override=False)
    assert not res.ok and "added in one run" in res.violations[0]
    assert guard.evaluate(index(500), index(500 + CFG.max_added), CFG, override=False).ok


def test_verified_collapse_fails():
    res = guard.evaluate(index(500, 450), index(500, 100), CFG, override=False)
    assert not res.ok and "verified playlist fell" in res.violations[0]


def test_thresholds_are_configurable():
    loose = GuardConfig(max_drop_percent=50)
    assert guard.evaluate(index(500), index(300), loose, override=False).ok
    tight = GuardConfig(max_added=5)
    assert not guard.evaluate(index(500), index(510), tight, override=False).ok


def test_small_baselines_skip_percentage_rules():
    assert guard.evaluate(index(10), index(1), CFG, override=False).ok


def test_override_lets_it_through_but_keeps_the_violation():
    res = guard.evaluate(index(500), index(100), CFG, override=True)
    assert res.ok and res.overridden and res.violations


def test_override_from_config_and_environment(monkeypatch):
    monkeypatch.delenv("NEXONIC_GUARD_OVERRIDE", raising=False)
    assert guard.evaluate(index(500), index(100), GuardConfig(override=True)).ok
    assert not guard.evaluate(index(500), index(100), CFG).ok
    monkeypatch.setenv("NEXONIC_GUARD_OVERRIDE", "1")
    assert guard.evaluate(index(500), index(100), CFG).ok


def test_no_baseline_is_skipped_not_failed():
    res = guard.evaluate(None, index(1), CFG, override=False)
    assert res.ok and res.skipped


def test_baseline_from_env_file_and_git(tmp_path, monkeypatch):
    f = tmp_path / "base.json"
    f.write_text(json.dumps(index(7)), encoding="utf-8")
    monkeypatch.setenv("NEXONIC_GUARD_BASELINE", str(f))
    assert guard.counts_from_index(guard.baseline_index(tmp_path))["published"] == 7
    monkeypatch.delenv("NEXONIC_GUARD_BASELINE")
    assert guard.baseline_index(tmp_path / "missing") is None  # not a git repository

    repo = tmp_path / "repo"
    (repo / "playlists").mkdir(parents=True)
    (repo / "playlists" / "index.json").write_text(json.dumps(index(42, 40)), encoding="utf-8")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run([*git, "init", "-q"], cwd=repo, check=True)
    subprocess.run([*git, "add", "."], cwd=repo, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "base"], cwd=repo, check=True)
    (repo / "playlists" / "index.json").write_text(json.dumps(index(1)), encoding="utf-8")  # uncommitted change
    base = guard.baseline_index(repo)
    assert guard.counts_from_index(base) == {"published": 42, "verified": 40}


def test_validate_turns_a_violation_into_an_error_unless_overridden(tmp_path, monkeypatch):
    monkeypatch.delenv("NEXONIC_GUARD_OVERRIDE", raising=False)
    f = tmp_path / "base.json"
    f.write_text(json.dumps(index(500, 450)), encoding="utf-8")
    monkeypatch.setenv("NEXONIC_GUARD_BASELINE", str(f))
    errors, warnings, verdict = validate.check_guard(tmp_path, index(300, 290), CFG)
    assert not verdict.ok and errors and errors[0]["stage"] == "publication-guard"
    assert "NEXONIC_GUARD_OVERRIDE" in errors[0]["error"] and "reports/changes.md" in errors[0]["error"]
    monkeypatch.setenv("NEXONIC_GUARD_OVERRIDE", "1")
    errors, warnings, verdict = validate.check_guard(tmp_path, index(300, 290), CFG)
    assert verdict.ok and not errors and "override active" in warnings[0]["warning"]


@pytest.mark.parametrize("n", [0, 1])
def test_validate_main_exit_code_follows_the_guard(n, monkeypatch, tmp_path):
    """End to end on the real repository: a baseline far larger than the output must fail validate.py."""
    f = tmp_path / "base.json"
    f.write_text(json.dumps(index(100000, 100000)), encoding="utf-8")
    monkeypatch.setenv("NEXONIC_GUARD_BASELINE", str(f))
    monkeypatch.setenv("NEXONIC_GUARD_OVERRIDE", str(n))
    root = validate.ROOT
    keep = (root / "reports" / "validation.json").read_bytes()
    try:
        assert validate.main() == (0 if n else 1)
    finally:
        (root / "reports" / "validation.json").write_bytes(keep)
