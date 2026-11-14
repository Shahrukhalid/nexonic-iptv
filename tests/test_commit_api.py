"""scripts/commit_via_api.py: server errors and dropped connections are retried, and a commit that landed despite
an error is not made twice. All network and git calls are mocked."""

from __future__ import annotations

import httpx
import pytest
from conftest import load_script

OK = {"data": {"createCommitOnBranch": {"commit": {"oid": "abc", "url": "https://example.org/c/abc"}}}}


@pytest.fixture
def mod(monkeypatch):
    m = load_script("commit_via_api")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("COMMIT_BRANCH", "main")
    monkeypatch.setattr(m, "changed", lambda paths: (["reports/x.md"], []))
    monkeypatch.setattr(m.Path, "read_bytes", lambda self: b"new")
    monkeypatch.setattr(m, "_git", lambda *a: "head0")
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    monkeypatch.setattr(m.sys, "argv", ["commit_via_api.py", "--message", "m", "reports"])
    return m


def _replies(monkeypatch, mod, replies):
    calls = []

    def post(*a, **kw):
        calls.append(kw)
        r = replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(mod.httpx, "post", post)
    return calls


def _resp(status, body=None):
    return httpx.Response(status, json=body or {}, request=httpx.Request("POST", "https://api.github.com/graphql"))


def test_retries_server_errors_then_commits(mod, monkeypatch):
    monkeypatch.setattr(mod, "_already_committed", lambda *a: False)
    calls = _replies(monkeypatch, mod, [_resp(504), httpx.ReadTimeout("slow"), _resp(502), _resp(200, OK)])
    assert mod.main() == 0
    assert len(calls) == 4


def test_error_after_the_commit_landed_is_success(mod, monkeypatch):
    monkeypatch.setattr(mod, "_already_committed", lambda *a: True)
    calls = _replies(monkeypatch, mod, [_resp(504)])
    assert mod.main() == 0
    assert len(calls) == 1  # no second commit


def test_gives_up_after_the_last_wait(mod, monkeypatch):
    monkeypatch.setattr(mod, "_already_committed", lambda *a: False)
    calls = _replies(monkeypatch, mod, [_resp(503)] * (len(mod.WAITS) + 1))
    assert mod.main() == 1
    assert len(calls) == len(mod.WAITS) + 1


def test_stale_after_a_landed_timeout_is_success(mod, monkeypatch):
    landed = iter([False, True])
    monkeypatch.setattr(mod, "_already_committed", lambda *a: next(landed))
    stale = _resp(200, {"errors": [{"type": "STALE_DATA", "message": "moved"}]})
    _replies(monkeypatch, mod, [httpx.ReadTimeout("slow"), stale])
    assert mod.main() == 0


def test_client_errors_are_not_retried(mod, monkeypatch):
    monkeypatch.setattr(mod, "_already_committed", lambda *a: False)
    _replies(monkeypatch, mod, [_resp(401)])
    with pytest.raises(httpx.HTTPStatusError):
        mod.main()


def test_large_changes_go_in_several_commits(mod, monkeypatch):
    # GitHub refuses requests over 45 MB: three 12 MB files (16 MB each once encoded) go one per request.
    monkeypatch.setattr(mod, "changed", lambda paths: (["a", "b", "c"], ["old"]))
    monkeypatch.setattr(mod.Path, "read_bytes", lambda self: b"x" * (12 * 1024 * 1024))
    second = {"data": {"createCommitOnBranch": {"commit": {"oid": "def", "url": "https://example.org/c/def"}}}}
    calls = _replies(monkeypatch, mod, [_resp(200, OK), _resp(200, OK), _resp(200, second)])
    assert mod.main() == 0
    assert len(calls) == 3
    first, _, last = (c["json"]["variables"]["input"] for c in calls)
    assert [a["path"] for a in first["fileChanges"]["additions"]] == ["a"]
    assert first["fileChanges"]["deletions"] == []
    assert last["expectedHeadOid"] == "abc"  # the second commit builds on the first
    assert last["fileChanges"]["deletions"] == [{"path": "old"}]
    assert last["message"]["headline"].endswith("(3/3)")
