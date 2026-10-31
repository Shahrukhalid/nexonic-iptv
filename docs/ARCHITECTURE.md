# Architecture

```
data/approved|pending|rejected/*.yaml  ──►  nexonic.records (schema + cross-checks)
data/moderation/*                      ──►  nexonic.moderation (5-layer adult screening + publication gate)
                                              │
scripts/verify.py ── nexonic.checker ──► state/history.json (rolling, genuine results)
                     (safety + hls)          │
                                              ▼
scripts/generate.py ── nexonic.generate + health ──► playlists/**.m3u, playlists/index.json,
                                                     PLAYLISTS.md, reports/channels.json, reports/statistics.json
scripts/validate.py ──► reports/validation.json   (strict M3U parse, exclusion proofs, index counts)
website/ (Astro) ── sync-data.mjs copies reports + playlists ──► static site on GitHub Pages
```

## Separation of concerns
| Kind | Location | Edited by |
|---|---|---|
| Source records | `data/approved/<cc>.yaml`, `data/pending/`, `data/rejected/` | Maintainers (PR review) |
| Moderation lists | `data/moderation/` | Maintainers; iptv-org lists refreshed with `scripts/moderate.py --refresh-blocklist` |
| Verification state | `state/history.json` | Only `scripts/verify.py` (GitHub Actions) |
| Generated output | `playlists/`, `PLAYLISTS.md`, `reports/` | Only `scripts/generate.py` / `verify.py` |
| Website | `website/` | Contributors; data comes only from generated files |

## Package `nexonic/`
| Module | Responsibility |
|---|---|
| `models.py` | Pydantic schema; adult categories cannot be expressed; approved records need authorization basis and `adult_screening: pass` |
| `reference/` | ISO 3166-1 countries (from iptv-org/database), ISO 639-1 languages, categories |
| `records.py` | Load YAML, folder/status consistency, duplicate ids/URLs/names, history I/O |
| `safety.py` | URL policy, token detection, restream host denylist, public-IP resolution, DNS-pinning network backend |
| `moderation.py` | Lexicons, denylists, quarantine, `publication_gate` |
| `hls.py` | HLS/DASH manifest parsing, DRM detection, media sniffing |
| `checker.py` | Async layered verifier with politeness limits and budgets |
| `status.py` | Outcome enum and `CheckResult` |
| `health.py` | Nexonic Health Score and display status |
| `m3u.py` | Extended M3U writer (escaping) and strict parser |
| `generate.py` | Deterministic playlist plan and outputs |
| `reports.py` | Statistics and verification reports |

## Determinism
Generation depends only on records, moderation lists and history. Sorting is `(country, name.casefold(), id)`; the
freshness reference is the timestamp of the latest verification result, never the wall clock. CI runs
`scripts/generate.py --check` to prove committed output equals a fresh build, and a unit test shuffles input order.

## Workflows
- `ci.yml` (PRs, pushes): lint, tests, validation, moderation, determinism check, secret scan, website build + link
  check, actionlint, gitleaks. Read-only token, no secrets, no live network checks.
- `verify-streams.yml` (03:17, 11:17 and 19:17 UTC, manual, data changes on `main`): live checks, regenerate, validate, commit via
  the GitHub GraphQL API so bot commits are signed.
- `generate-playlists.yml`: regenerate when data or code changes on `main` (no-op when nothing changes).
- `deploy-pages.yml`: build site, check links and assets, deploy to GitHub Pages.
