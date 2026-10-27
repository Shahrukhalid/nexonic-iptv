"""generate.py --check: strict by default, lenient about stale committed outputs on pull requests."""

import shutil

import pytest
from conftest import ROOT, load_script

gen = load_script("generate")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A copy of the committed outputs and state that generate.py treats as the repository root."""
    for name in ("playlists", "reports", "state"):
        shutil.copytree(ROOT / name, tmp_path / name)
    for name in ("README.md", "PLAYLISTS.md"):
        shutil.copy(ROOT / name, tmp_path / name)
    monkeypatch.setattr(gen, "ROOT", tmp_path)
    return tmp_path


def make_stale(repo):
    (repo / "playlists" / "all.m3u").write_text("#EXTM3U\n", encoding="utf-8")
    (repo / "reports" / "statistics.json").write_text("{}\n", encoding="utf-8")


def test_strict_passes_when_outputs_are_current(repo, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    assert gen.main(["--check"]) == 0
    assert "up to date" in capsys.readouterr().out


def test_strict_fails_on_stale_outputs(repo, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    make_stale(repo)
    assert gen.main(["--check"]) == 1
    err = capsys.readouterr().err
    assert "out of date" in err and "playlists/all.m3u" in err and "reports/statistics.json" in err


@pytest.mark.parametrize("event", ["push", "workflow_dispatch", ""])
def test_other_events_stay_strict(repo, monkeypatch, event):
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    make_stale(repo)
    assert gen.main(["--check"]) == 1


def test_pull_request_lists_but_tolerates_stale_outputs(repo, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    make_stale(repo)
    assert gen.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "will change after merge: playlists/all.m3u" in out
    assert "will change after merge: reports/statistics.json" in out
    assert "deterministic" in out


def test_pull_request_current_outputs(repo, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    assert gen.main(["--check"]) == 0
    assert "nothing will change" in capsys.readouterr().out


def test_pull_request_fails_when_generation_is_not_deterministic(repo, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    real_build, calls = gen.build, []

    def flaky(root):
        rc = real_build(root)
        calls.append(root)
        (root / "reports" / "changes.md").write_text(f"run {len(calls)}\n", encoding="utf-8")
        return rc

    monkeypatch.setattr(gen, "build", flaky)
    assert gen.main(["--check"]) == 1
    assert "not deterministic" in capsys.readouterr().err


def test_pull_request_fails_when_generation_fails(repo, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setattr(gen, "build", lambda root: 2)
    assert gen.main(["--check"]) == 2


def test_pull_request_fails_on_validation_errors(repo, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setattr(
        gen.validation,
        "collect",
        lambda base: {"errors": [{"stage": "schema", "error": "boom"}], "warnings": []},
    )
    assert gen.main(["--check"]) == 1
    assert "boom" in capsys.readouterr().err


def test_normal_mode_does_not_need_a_flag(monkeypatch):
    called = []
    monkeypatch.setattr(gen, "build", lambda root: called.append(root) or 0)
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    assert gen.main([]) == 0 and called
