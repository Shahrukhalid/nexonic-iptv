# Maintenance

Everything runs on free GitHub features (Actions on a public repo, Pages). No paid services, API keys or servers.

## Routine
| When | What |
|---|---|
| Daily (automatic) | `verify-streams.yml` checks streams, regenerates playlists, commits signed results, site redeploys |
| Weekly | Read `reports/verification.md`; investigate channels in "currently failing"; triage issues |
| Daily (automatic) | `refresh-catalog.yml` refreshes NSFW lists and the auto-admitted tier from iptv-org, then verification runs |
| Monthly | Spot-check a sample of auto-admitted channels; promote good ones to `data/approved/<cc>.yaml`. Refresh iptv-org NSFW lists: `python scripts/moderate.py --refresh-blocklist <blocklist.csv> --channels <channels.csv>`; review `data/pending/` |
| Per new channel | Review a PR or issue against the source policy; set `source.evidence_checked` after opening the evidence page |

## Adding a channel
1. Add a record to `data/pending/<topic>.yaml` (or start from `python scripts/discover.py <m3u> --country xx`).
2. Open the broadcaster's live page; confirm it plays the stream free and that the stream host belongs to the
   broadcaster. Fill `source.evidence_url`, `evidence_summary`, `evidence_checked`.
3. Screen the content; set `review.adult_screening` and your name in `review.reviewer`.
4. Move the record to `data/approved/<country>.yaml`, set `review.status: approved` and `authorization_basis`.
5. `pytest && python scripts/validate.py && python scripts/moderate.py && python scripts/generate.py`, open a PR.

## Fixing a broken channel
Find the broadcaster's current official URL on its live page and update `stream.url`. If no official stream exists any
more, move the record to `data/rejected/` with a reason. Stale channels (3+ failures, no success for 7 days) are
already excluded from playlists automatically.

## Fast removal
For adult content or a rights-holder request:
1. Move the record from `data/approved/` to `data/rejected/rejected.yaml`, set `review.status: rejected` and a
   `rejection_reason` linking the issue.
2. Add the id to `data/moderation/denylist.yaml` (`channel_ids`).
3. Commit to `main` (or merge the PR). `generate-playlists.yml` regenerates every playlist and `deploy-pages.yml`
   redeploys — typically within minutes.

## Local development
```bash
python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
pytest
python scripts/verify.py --ids dw-english   # live check (needs internet)
python scripts/generate.py
cd website && npm ci && npm run dev         # http://localhost:4321/nexonic-iptv/
```

## One-time repository settings
- Settings → Pages → Build and deployment → Source: **GitHub Actions**.
- Settings → Actions → General → Workflow permissions: read (workflows request write themselves where needed).
- Settings → Code security → enable private vulnerability reporting and secret scanning.
- Branch protection on `main`: require the CI workflow and one review.
