#!/usr/bin/env python3
"""Commit changed files through the GitHub GraphQL API (createCommitOnBranch).

Used by scheduled workflows instead of ``git push`` so that bot commits are signed by GitHub and show as Verified.
Only paths under the given prefixes are committed, and nothing is committed when nothing changed.

    python scripts/commit_via_api.py --message "Update verification results" state reports playlists PLAYLISTS.md

Requires GITHUB_TOKEN (contents: write) and GITHUB_REPOSITORY; branch defaults to GITHUB_REF_NAME.
"""

from __future__ import annotations

import argparse
import base64
import os
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 40 * 1024 * 1024


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
    total = 0
    additions = []
    for p in adds:
        data = (ROOT / p).read_bytes()
        total += len(data)
        additions.append({"path": p, "contents": base64.b64encode(data).decode()})
    if total > MAX_BYTES:
        print("Refusing: commit too large", file=sys.stderr)
        return 1
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    query = """mutation($input: CreateCommitOnBranchInput!) {
      createCommitOnBranch(input: $input) { commit { oid url } } }"""
    variables = {
        "input": {
            "branch": {"repositoryNameWithOwner": repo, "branchName": branch},
            "message": {"headline": args.message},
            "expectedHeadOid": head,
            "fileChanges": {"additions": additions, "deletions": [{"path": p} for p in dels]},
        }
    }
    r = httpx.post(
        "https://api.github.com/graphql",
        json={"query": query, "variables": variables},
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("errors"):
        print(f"GraphQL errors: {body['errors']}", file=sys.stderr)
        return 1
    commit = body["data"]["createCommitOnBranch"]["commit"]
    print(f"Committed {len(adds)} added/changed and {len(dels)} deleted file(s): {commit['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
