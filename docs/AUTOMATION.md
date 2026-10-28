# Automation

How the daily pipeline works, what it can be tuned with, and how to check on it. Results always describe
reachability **from the checker's network location at the time of the run**; nothing here claims a stream works
anywhere else.

## Pipeline stages

| # | Stage | Script / module | Output |
|---:|---|---|---|
| 1 | Discovery | `scripts/expand_catalog.py` (reads iptv-org data), `scripts/discover.py` (any M3U, candidates only) | `data/approved/auto/*.yaml`, `data/pending/auto-quarantine.yaml`, `state/discovery.json` |
| 2 | Normalisation | `expand_catalog.py` (ids, languages, categories, stable ordering) | records that pass the schema in `nexonic/models.py` |
| 3 | Authorization review | owner-domain rules, URL policy, sanctions and NSFW screening (`nexonic/moderation.py`); manual records in `data/pending/` wait for a maintainer | approved, pending or rejected records |
| 4 | Validation | `scripts/verify.py` (live checks), `nexonic/lifecycle.py` (state, quarantine) | `state/history.json`, `reports/verification.*` |
| 5 | Dedup | `nexonic/dedup.py`, used by discovery and by `nexonic/generate.py` | duplicates are never published |
| 6 | Tests | `pytest`, `ruff`, `scripts/moderate.py`, `scripts/validate.py` | CI |
| 7 | Publication | `scripts/generate.py`, `scripts/validate.py` (publication guard), `scripts/commit_via_api.py` | `playlists/`, `reports/`, `state/` |

Admission rules are unchanged: a stream is admitted automatically only when its host belongs to the broadcaster
(see [SOURCE_POLICY.md](SOURCE_POLICY.md) section 2a), passes the URL policy and the NSFW and sanctions screening, and
an automated record is published only after one successful live check.

### Lifecycle states
`reports/channels.json` carries, per published channel, `lifecycle` (derived from `state/history.json` only):

| State | Meaning |
|---|---|
| `working` | verified in the window (default 7 days) and no failures in it |
| `intermittent` | both successes and failures in the window |
| `unreachable` | failing with `UNAVAILABLE` / `TIMEOUT` |
| `invalid` | failing with `INVALID_STREAM` |
| `restricted` | last check was `GEO_RESTRICTED` or `AUTH_REQUIRED` |
| `unknown` | no scorable result in the window, or the last outcome was `UNSUPPORTED` |

Also exported: `quarantined`, `restored_at`, `last_validated` (time of the latest live check),
`last_metadata_update` (date the record's metadata last changed, tracked in `state/lifecycle.json`) and a
`provenance` object (source reference, evidence URL and summary, discovery method, first discovered, authorization
basis, review date). The earlier fields are unchanged.

### Quarantine
A channel is quarantined after `consecutive_failures` failed checks in a row spread over at least `distinct_days`
UTC days (defaults 3 and 2). `GEO_RESTRICTED`, `RATE_LIMITED`, `UNKNOWN` and `UNSUPPORTED` results neither count nor
break the run. A quarantined channel leaves `verified.m3u`; one `VERIFIED_WORKING` result restores it and sets
`restored_at`. Until it is quarantined, a channel that failed its latest check but worked within the last 48 hours
stays in `verified.m3u`. The older rule that removes a channel from every playlist (3+ failures and no success for 7
days) still applies and is reported as `stale`.

### Change report
Every `generate.py` run writes `reports/changes.md` and `reports/changes.json`: new candidates, newly published
channels, updated metadata or URLs, duplicates removed, newly failing, newly quarantined, restored, removed, pending
authorization count, integrity status and an "errors needing attention" list. The comparison baseline is
`state/lifecycle.json`; `state/change-history.json` keeps the last 30 daily summaries. A short version is appended to
`reports/verification.md`, which the workflow's Summary step already prints. Nothing reads the clock, so running
`generate.py` again on the same inputs changes no file.

### Publication guard
`scripts/validate.py` compares the new `playlists/index.json` with the version committed at `HEAD` (or the file named by
`NEXONIC_GUARD_BASELINE`) and exits non-zero when:
- the published channel count falls by more than `guard.max_drop_percent`,
- more than `guard.max_added` channels are added in one run, or
- the verified playlist falls by more than `guard.max_verified_drop_percent`.

Percentage rules are skipped when the previous count is below `guard.min_baseline`. When there is no committed
baseline the guard is skipped with a warning.

**Override** (after reading `reports/changes.md`): set `NEXONIC_GUARD_OVERRIDE=1` for one run, or commit
`override = true` under `[guard]` in `config/pipeline.toml` and revert it afterwards. With the workflow patch below, the
"Verify streams" workflow also offers a `guard_override` input on manual runs. An overridden violation is kept in
`reports/validation.json` as a warning.

## Configuration
All settings live in `config/pipeline.toml`; every value shown there is the built-in default, so deleting the file
changes nothing. `NEXONIC_PIPELINE_CONFIG` points at another file. Unknown keys and out-of-range values are rejected.
Command-line flags of `verify.py` (`--timeout`, `--concurrency`, `--budget-minutes`) override the file.

| Section.key | Default | Used by |
|---|---:|---|
| `verify.timeout` | 10.0 s | per-request timeout |
| `verify.concurrency` / `max_concurrency` | 12 / 16 | parallel channels |
| `verify.retries` | 1 | per request (timeouts, connection errors, 429, 5xx) |
| `verify.backoff_base` | 1.0 s | doubles per retry |
| `verify.per_host_interval` | 1.0 s | minimum gap between requests to one host |
| `verify.channel_timeout` | 60 s | hard cap per channel |
| `verify.budget_minutes` | 40 | no new checks after this |
| `quarantine.consecutive_failures` | 3 | N |
| `quarantine.distinct_days` | 2 | M |
| `quarantine.intermittent_window_days` | 7 | window for `intermittent` |
| `guard.max_drop_percent` | 10 | published channels |
| `guard.max_added` | 300 | channels added per run |
| `guard.max_verified_drop_percent` | 50 | verified playlist |
| `guard.min_baseline` | 50 | percentage rules need at least this many before |
| `guard.override` | false | publish anyway |
| `changes.history_days` / `max_listed` | 30 / 200 | change history, list length in `changes.json` |
| `discovery.timeout` / `retries` / `backoff_base` | 30 s / 4 / 2.0 s | downloads |
| `discovery.max_archive_mb` | 300 | download size cap |
| `discovery.allowed_hosts` | github.com, codeload.github.com, raw.githubusercontent.com | https only |
| `discovery.max_playlist_mb` | 50 | size cap of each downloaded extra M3U file |
| `[[discovery.sources]]` | iptv-org/iptv and iptv-org/database, `master` | `name`, `repo`, `ref` |
| `[[discovery.extra_m3u]]` | the public repositories listed in `config/pipeline.toml` | `name`, `repo`, `ref`, `paths`, `licence` |

## Discovery without a local clone
`python scripts/expand_catalog.py` with no arguments downloads the two repositories' archives over HTTPS, extracts only
`streams/*.m3u` and `data/{channels,feeds,blocklist}.csv`, and runs the same admission rules. Failures (timeouts,
429, 5xx) are retried with exponential backoff; a persistent failure exits non-zero and changes nothing. `--streams`
and `--database` still work and may be mixed with the download (only the missing half is fetched).
`python scripts/moderate.py --refresh-remote` refreshes the NSFW lists the same way and refuses to replace a list with
one less than half its size. Re-running discovery on unchanged input rewrites no file: records keep their dates, files
are written only when their content changes, and ordering is stable.

## Extra M3U sources from public repositories
`[[discovery.extra_m3u]]` lists plain M3U files published in public GitHub repositories (`name`, `repo`, `ref`,
`paths`, `licence`). `python scripts/expand_catalog.py` without `--streams` and `--database` downloads each file from
`raw.githubusercontent.com` through `nexonic/fetch.py` (https only, allowed hosts only, retries with backoff, size cap
`discovery.max_playlist_mb`) and treats it exactly like an `--extra-m3u` input. A playlist is only a pointer to
candidates: an entry is admitted only when its `tvg-id` exists in iptv-org/database **and** every rule of
[SOURCE_POLICY.md](SOURCE_POLICY.md) section 2a holds, so none of the admission rules differ by source. In addition,
entries that carry `#EXTHTTP`, `#KODIPROP` or a `|Header=value` suffix are refused as "needs special headers".

- **Order and duplicates.** Sources are read as iptv-org first, then `--extra-m3u` files, then the configured sources
  in file order. For one channel the first source offering an admissible stream wins; a second entry with the same
  normalised stream URL or the same channel identity is never admitted (reported as
  `duplicate-channel-in-other-source` or `duplicate-of-existing`).
- **Provenance.** `source.reference_url` of an admitted record is the exact file in the source repository
  (`https://github.com/<repo>/blob/<ref>/<path>`); it is internal and not shown on the website. The licence of each
  repository is recorded in the config.
- **Reports.** `state/discovery.json` keeps the same counters per source under `sources`; the script prints the entries
  read, admitted and quarantined per source.
- **Failures.** A file that no longer exists (404) is skipped with a warning; any other download failure exits non-zero
  and changes nothing. `--no-extra-sources` skips the extra downloads; with both `--streams` and `--database` no
  network access happens at all.
- **Choosing sources.** Add only repositories with an open licence, plain M3U files and no paid, premium, VOD,
  restream, Xtream or credential-bearing content. Lists without a licence are not used.
- Quarantined records that a maintainer annotated ("Quarantine reviewed: ...") stay in
  `data/pending/auto-quarantine.yaml` when discovery re-runs.

## Running each step locally
```bash
pip install -r requirements-dev.txt
python scripts/expand_catalog.py            # discovery (needs network) or --streams DIR --database DIR
python scripts/moderate.py                  # screening of every record
python scripts/verify.py --ids dw-english   # live checks (needs network; add --ffprobe if installed)
python scripts/generate.py                  # playlists, reports, changes report, state snapshot
python scripts/validate.py                  # schema, URL policy, M3U syntax, publication guard
python scripts/generate.py --check          # outputs are up to date (on pull requests: deterministic and valid)
python scripts/review.py list               # pending records; approve <id> / reject <id> --reason TEXT
python scripts/verify.py --location-label asia-pk --only restricted   # second location, see REGIONAL_CHECKS.md
pytest && ruff check . && ruff format --check .
```

## Verifying the next scheduled run
1. Open the "Verify streams" run for 03:17 UTC; the job summary starts with the change report.
2. Check the commit "Update verification results and playlists": `reports/changes.md`, `reports/changes.json`,
   `state/lifecycle.json` and `state/change-history.json` should be part of it.
3. Read the "Needs attention" list. A run that fails at "Validate before publishing" with `publication-guard` means the
   output was implausibly different; nothing was committed.
4. Manual run: Actions, "Verify streams", "Run workflow".

## Workflow patch
The workflow files cannot be changed from the automation account, so the pipeline works with the existing steps. For
daily discovery and a one-click guard override, apply `docs/automation-workflow.patch` with a
token that may edit workflows:

```bash
git apply docs/automation-workflow.patch && git add .github/workflows && git commit -m "Daily catalogue refresh"
```
It (1) makes "Refresh catalog" run daily at 01:41 UTC and download the iptv-org data itself instead of cloning,
(2) includes `state` in that workflow's commit, (3) drops the `workflow_run` trigger of "Verify streams" so the refresh
does not cause a second verification run (the 03:17 run follows it), (4) adds the `guard_override` manual input and (5)
prints `reports/changes.md` in the Summary step. Without the patch, discovery stays monthly and the change report is
still produced and committed by the existing steps.

## Pull request checks
`python scripts/generate.py --check` is strict by default: it exits 1 when committed outputs differ from a fresh build.
When `GITHUB_EVENT_NAME` is `pull_request` (the CI step for pull requests), the outputs are regenerated on `main` after
the merge, so a data-only pull request would always fail that comparison. In that mode the check instead requires that
generation succeeds, that two fresh builds into separate temporary directories are identical, and that the generated
files pass the rules of `scripts/validate.py`. It prints every output that will change after the merge and does not
fail for them.

## Reviewing pending records
`scripts/review.py list` shows the records in `data/pending`. `approve <id> [--reviewer NAME]` moves one to
`data/approved/<cc>.yaml` (automated records to `data/approved/auto/<cc>.yaml`) and `reject <id> --reason TEXT` to
`data/rejected/<cc>.yaml`. A record needs an authorization basis and a passed adult-content screening to be approved;
state them with `--basis` and `--confirm-screening` after checking the evidence. Only the moved record's text changes
in the files involved, the data is validated afterwards and the change is rolled back if that fails. Records suggested
by visitors carry `source.method: community-suggestion` and are published only after a maintainer approves them.

## Regional checks
See [REGIONAL_CHECKS.md](REGIONAL_CHECKS.md) for second-location verification (`state/regional/`, `works_in`,
`playlists/regions/`).
