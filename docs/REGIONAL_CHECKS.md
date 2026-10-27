# Regional checks

The daily "Verify streams" run uses GitHub-hosted runners, which are in the United States. A stream that is limited to
another country answers there with `GEO_RESTRICTED` (or a 403 that is recorded as `UNKNOWN`). Those channels stay
`restricted` in `reports/channels.json` and are not in `verified.m3u`: from the main checker's location nothing is
known about them.

A **second location** closes part of that gap. It re-checks only the channels that could not be confirmed, using the
same checker, rate limits and safety rules as the main run, and records what it saw from there. Results describe
reachability **from that location, at that time**. They say nothing about any other place.

## What is recorded and published

| Item | Where | Rule |
|---|---|---|
| Raw results | `state/regional/<label>.json` | Same record shape as `state/history.json`, last 30 results per channel. Never mixed into `state/history.json`, so a regional result cannot change a channel's lifecycle, quarantine state or Health Score. |
| `works_in` | `reports/channels.json` | Added to a channel whose primary lifecycle is `restricted` and whose latest result from a location is `VERIFIED_WORKING` within the 48 hour freshness window. The lifecycle stays `restricted`. |
| Region playlist | `playlists/regions/<label>.m3u` | Channels verified working from that location in the window. Only written when such channels exist. Never added to `verified.m3u`. |
| Counts | `reports/statistics.json` (`regional`), `reports/changes.md`, `reports/changes.json` | "Restricted channels confirmed working elsewhere", per location. Absent until a location has reported. |

Labels are 2 to 32 characters of `a-z`, `0-9` and `-`, for example `asia-pk` or `eu-de`.

## Command line

```bash
python scripts/verify.py --location-label asia-pk --only GEO_RESTRICTED,UNKNOWN,TIMEOUT,restricted
python scripts/generate.py && python scripts/validate.py
```

`--only` takes statuses (upper case) and lifecycle states (lower case), comma or space separated, or `all`. A channel
is re-checked when its latest primary result has one of the statuses or its primary lifecycle is one of the states.
`--ids` can narrow it further. `--only` needs `--location-label`; without a label `verify.py` behaves as before.

## Option A: your own computer, one command

For a one-off run, or if you do not want a self-hosted runner. Needs git, Python 3.11 or newer and, to open the pull
request automatically, the GitHub CLI (`gh auth login` once).

```bash
git clone https://github.com/Shahrukhalid/nexonic-iptv && cd nexonic-iptv
bash scripts/verify_regional_local.sh asia-pk
```

The script creates a branch `regional/<label>-<date>` from `origin/main`, installs the requirements into
`.venv-regional/`, re-checks the restricted channels, commits only `state/regional/<label>.json`, pushes the branch and
opens a pull request. Without `gh` it pushes the branch and tells you to open the pull request on GitHub. A second
argument changes the selection, and `REGIONAL_LABEL` can replace the first. After you merge, the next daily "Verify streams" run
(or a manual "Generate playlists" run) regenerates `works_in`, `playlists/regions/<label>.m3u`, the reports and
`PLAYLISTS.md`.

## Option B: a self-hosted macOS runner, daily

1. In the repository open Settings, Actions, Runners, **New self-hosted runner**, choose macOS and run the shown
   commands on the Mac (download, `./config.sh --url ... --token ...`). When `config.sh` asks for additional labels,
   enter `nexonic-regional`. The runner must be on the network whose view you want to record.
2. Install it as a service so it survives restarts: `./svc.sh install`, then `./svc.sh start` (`./svc.sh status` to
   check). Python 3.12 must be installed on the Mac, and the Mac must be awake around 04:47 UTC.
3. Settings, Secrets and variables, Actions, tab **Variables**: add `REGIONAL_LABEL`, for example `asia-pk`.
4. Paste the workflow. The file is ready in `docs/workflows/verify-regional.yml`; copy it to
   `.github/workflows/verify-regional.yml` in the GitHub web editor (workflow files cannot be changed by the automation
   account).
5. Run it once: Actions, "Verify streams (regional)", Run workflow. The `label` input is pre-filled from
   `REGIONAL_LABEL`.

The workflow runs daily at 04:47 UTC, after the 03:17 UTC main run, so it sees that run's results. It selects the
restricted subset, checks it, runs `generate.py` and `validate.py`, and commits `state`, `reports`, `playlists`,
`PLAYLISTS.md` and `README.md` through the signed GitHub API (`scripts/commit_via_api.py`). It shares the
`data-writer` concurrency group with the other writers, so runs queue instead of overlapping.

## Security notes for a public repository

A self-hosted runner executes workflow code on your own computer. Treat it accordingly.

- Only the `schedule` and `workflow_dispatch` triggers are used. **Never** add `pull_request`, `pull_request_target`
  or `workflow_run` to a workflow that has `runs-on: [self-hosted, ...]`: code from a fork could then run on your Mac.
- Settings, Actions, General, "Fork pull request workflows from outside collaborators": choose **Require approval for
  all outside collaborators**.
- Keep the runner for this repository only (not an organisation-wide runner group) and run it under a normal user
  account, not an administrator. Do not store other credentials on that machine's runner account.
- The job has `contents: write` and nothing else, and checks out `main` without persisting credentials. The
  `github.repository_owner` condition keeps forks from using it.
- The checker's own protections apply on the runner: URL policy, public addresses only, bounded reads, one request at a
  time per host, an identifying user agent (see VERIFICATION.md). Do not run it behind a VPN that you are not allowed
  to use for this purpose.

## Troubleshooting

- "invalid location label": the label or `REGIONAL_LABEL` is not 2 to 32 characters of `a-z`, `0-9`, `-`.
- "No channels match --only": nothing in `state/history.json` has those statuses; nothing is written.
- A channel is still `restricted` with no `works_in`: it did not pass from that location, its regional result is older
  than 48 hours, or it has not been re-checked yet.
