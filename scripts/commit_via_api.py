#!/usr/bin/env python3
"""Commit changed files through the GitHub GraphQL API (createCommitOnBranch).

Used by scheduled workflows instead of ``git push`` so that bot commits are signed by GitHub and show as Verified.
Only paths under the given prefixes are committed, and nothing is committed when nothing changed.

    python scripts/commit_via_api.py --message "Update verification results" state reports playlists PLAYLISTS.md

Requires GITHUB_TOKEN (contents: write) and GITHUB_REPOSITORY; branch defaults to GITHUB_REF_NAME.

GitHub's API sometimes answers 502/503/504 or drops the connection. Those calls are retried with growing pauses,
so a long verification run is not thrown away. A timed-out request may still have created the commit, so before
retrying the script checks whether the branch already holds exactly these changes and then reports success.
"""

from __future__ import annotations

import argparse
import base64
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 200 * 1024 * 1024  # the whole change; it is sent in parts of at most BATCH_BYTES
BATCH_BYTES = 30 * 1024 * 1024  # encoded contents per request (GitHub's limit is 45 MB per request)
RETRY_STATUS = {500, 502, 503, 504}
WAITS = (5, 15, 45, 90, 180)  # seconds between attempts after a server or network error


def changed(paths: list[str]) -> tuple[list[str], list[str]]:
    out = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *paths],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    adds, dels = [], []
    entries = out.split("\0")
    i = 0
    while i < len(entries):
        e = entries[i]
        i += 1
        if not e:
            continue
        code, path = e[:2], e[3:]
        if code.startswith("R"):
            dels.append(entries[i])  # old name follows a rename entry
            i += 1
        if "D" in code:
            dels.append(path)
        else:
            adds.append(path)
    return sorted(set(adds)), sorted(set(dels))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--message", required=True)
    ap.add_argument("paths", nargs="+")
    args = ap.parse_args()
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    branch = os.environ.get("COMMIT_BRANCH") or os.environ.get("GITHUB_REF_NAME", "main")
    if not token or not repo:
        print("GITHUB_TOKEN and GITHUB_REPOSITORY are required", file=sys.stderr)
        return 2
    adds, dels = changed(args.paths)
    if not adds and not dels:
        print("No changes to commit.")
        return 0
    total = sum(len((ROOT / p).read_bytes()) for p in adds)
    if total > MAX_BYTES:
        print("Refusing: commit too large", file=sys.stderr)
        return 1
    # GitHub refuses a request over 45 MB, and file contents travel base64-encoded (a third larger), so a big
    # verification run (history, playlists) is committed in several commits, each well under that limit.
    head = _git("rev-parse", "HEAD")
    batches = _batches(adds)
    for n, batch in enumerate(batches, 1):
        last = n == len(batches)
        message = args.message if len(batches) == 1 else f"{args.message} ({n}/{len(batches)})"
        result = _commit(token, repo, branch, message, head, batch, dels if last else [], args.paths)
        if result is None:
            return 1
        head = result
    return 0


def _batches(adds: list[str]) -> list[list[str]]:
    """Groups the changed files so each request's encoded contents stay under BATCH_BYTES (one file per group at least)."""
    groups: list[list[str]] = [[]]
    size = 0
    for p in adds:
        encoded = len((ROOT / p).read_bytes()) * 4 // 3 + 4
        if groups[-1] and size + encoded > BATCH_BYTES:
            groups.append([])
            size = 0
        groups[-1].append(p)
        size += encoded
    return groups


def _commit(
    token: str, repo: str, branch: str, message: str, head: str, adds: list[str], dels: list[str], paths: list[str]
) -> str | None:
    """One createCommitOnBranch call with retries; returns the new head, or None on failure."""
    additions = [{"path": p, "contents": base64.b64encode((ROOT / p).read_bytes()).decode()} for p in adds]
    query = """mutation($input: CreateCommitOnBranchInput!) {
      createCommitOnBranch(input: $input) { commit { oid url } } }"""
    stale_retries = 0
    server_retries = 0
    while True:
        variables = {
            "input": {
                "branch": {"repositoryNameWithOwner": repo, "branchName": branch},
                "message": {"headline": message},
                "expectedHeadOid": head,
                "fileChanges": {"additions": additions, "deletions": [{"path": p} for p in dels]},
            }
        }
        try:
            r = httpx.post(
                "https://api.github.com/graphql",
                json={"query": query, "variables": variables},
                headers={"Authorization": f"Bearer {token}"},
                timeout=180,
            )
            problem = f"HTTP {r.status_code}" if r.status_code in RETRY_STATUS else None
        except httpx.TransportError as exc:  # timeouts, resets, DNS hiccups
            r, problem = None, f"{type(exc).__name__}: {exc}"
        if problem:
            if _already_committed(branch, adds, dels, head):
                print(f"GitHub answered {problem}, but the branch already holds these changes; done.")
                return _remote_head(branch)
            if server_retries >= len(WAITS):
                print(f"GitHub kept failing ({problem}); giving up after {server_retries} retries.", file=sys.stderr)
                return None
            wait = WAITS[server_retries]
            server_retries += 1
            print(f"GitHub answered {problem}; retrying in {wait}s ({server_retries}/{len(WAITS)}).")
            time.sleep(wait)
            continue
        assert r is not None
        r.raise_for_status()
        body = r.json()
        errors = body.get("errors") or []
        if not errors:
            commit = body["data"]["createCommitOnBranch"]["commit"]
            print(f"Committed {len(adds)} added/changed and {len(dels)} deleted file(s): {commit['url']}")
            return commit["oid"]
        if not any(e.get("type") == "STALE_DATA" for e in errors) or stale_retries == 3:
            print(f"GraphQL errors: {errors}", file=sys.stderr)
            return None
        stale_retries += 1
        # The branch moved while this job ran. If an earlier attempt that timed out actually landed, we are done.
        # Otherwise retry on the new head only if nobody else changed the files we are about to write; else we
        # would silently overwrite their work.
        if _already_committed(branch, adds, dels, head):
            print("An earlier attempt already committed these changes; done.")
            return _remote_head(branch)
        new_head = _remote_head(branch)
        touched = _git("diff", "--name-only", head, new_head, "--", *paths).split()
        if touched:
            print(f"Branch moved and changed {len(touched)} of our files; refusing to overwrite.", file=sys.stderr)
            return None
        print(f"Branch moved ({head[:7]} -> {new_head[:7]}) without touching our files; retrying.")
        head = new_head


def _remote_head(branch: str) -> str:
    _git("fetch", "--quiet", "origin", branch)
    return _git("rev-parse", "FETCH_HEAD")


def _already_committed(branch: str, adds: list[str], dels: list[str], base: str) -> bool:
    """True when the remote branch already has exactly our version of every changed file."""
    try:
        head = _remote_head(branch)
    except subprocess.CalledProcessError:
        return False
    if head == base:
        return False  # nothing landed yet
    for p in adds:
        got = subprocess.run(["git", "show", f"{head}:{p}"], cwd=ROOT, capture_output=True)
        if got.returncode != 0 or got.stdout != (ROOT / p).read_bytes():
            return False
    for p in dels:
        if subprocess.run(["git", "cat-file", "-e", f"{head}:{p}"], cwd=ROOT, capture_output=True).returncode == 0:
            return False
    return True


def _git(*argv: str) -> str:
    return subprocess.run(["git", *argv], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


if __name__ == "__main__":
    sys.exit(main())
