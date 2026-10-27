#!/usr/bin/env python3
"""Lightweight secret scanner for tracked files (complements gitleaks in CI). Exit 1 on findings."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = {
    "GitHub token": re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{60,}\b"),
    "AWS access key": re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "Slack token": re.compile(r"\bxox[abprs]-[0-9A-Za-z-]{10,}\b"),
    "sk- style API key": re.compile(r"\bsk-(ant-)?[A-Za-z0-9_-]{32,}\b"),
    "Private key": re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY( BLOCK)?-----"),
    "Generic secret assignment": re.compile(
        r"(?i)\b(api[_-]?key|secret|passwd|password|access[_-]?token)\b\s*[:=]\s*['\"][A-Za-z0-9/+_\-]{16,}['\"]"
    ),
}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2"}


def files(explicit: list[str]) -> list[Path]:
    if explicit:
        return [Path(p) for p in explicit]
    try:
        out = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout
        return [ROOT / p for p in out.splitlines() if p]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return [p for p in ROOT.rglob("*") if p.is_file() and "node_modules" not in p.parts and ".git" not in p.parts]


def scan(paths: list[Path]) -> list[str]:
    findings = []
    for p in paths:
        if p.suffix.lower() in SKIP_SUFFIXES or not p.is_file() or p.name == "scan_secrets.py":
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for label, pat in PATTERNS.items():
                if pat.search(line):
                    findings.append(f"{p}:{n}: possible {label}")
    return findings


def main() -> int:
    found = scan(files(sys.argv[1:]))
    for f in found:
        print(f)
    print(f"{len(found)} possible secret(s) found.")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
