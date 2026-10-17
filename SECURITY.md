# Security policy

## Reporting
Please report vulnerabilities, leaked secrets, or sensitive copyright/safety matters **privately** using GitHub's
[private vulnerability reporting](https://github.com/Shahrukhalid/nexonic-iptv/security/advisories/new).
Do not open a public issue for these. We aim to respond within 7 days.

## Scope
- The verifier (`nexonic/checker.py`, `nexonic/safety.py`): SSRF, redirect handling, resource exhaustion.
- Playlist generation: injection into M3U files, path traversal.
- The website: XSS from channel metadata.
- GitHub Actions: privilege escalation, secret exposure, untrusted PR execution.

## Design measures
- Only `http(s)`; credentials, internal hostnames, IP literals, non-standard ports and tokenised URLs are rejected.
- All resolved addresses must be public; connections are pinned to the validated address; redirects re-validated.
- Bounded response sizes, request budgets, timeouts, per-host rate limits.
- M3U attributes are sanitised; URLs with whitespace or control characters are refused.
- Astro escapes all rendered values; client scripts use `textContent`, not `innerHTML`.
- Workflows: explicit least-privilege permissions, actions pinned to commit SHAs, no `pull_request_target`, no secrets
  in any workflow (scheduled jobs use only the built-in `GITHUB_TOKEN`), live checks never run on PR code.
- Secret scanning: `scripts/scan_secrets.py` and gitleaks in CI.
- No API keys are needed to use or run the project. No viewer data is collected.
