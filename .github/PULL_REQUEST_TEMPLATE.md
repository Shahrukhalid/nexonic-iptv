## What does this change?

<!-- Short description. -->

## If this adds or changes a channel

- [ ] Record added to `data/pending/` (new) or `data/approved/<cc>.yaml` (maintainers only)
- [ ] `source.evidence_url` is the broadcaster's own page that plays this stream free of charge
- [ ] Stream host belongs to the broadcaster or its CDN (no IP addresses, restreams, tokens or credentials)
- [ ] The channel is **not** adult-oriented and `review.adult_screening` reflects a real check
- [ ] Region limits are recorded in `geo` (or `unknown`)
- [ ] I did not edit generated files (`playlists/`, `PLAYLISTS.md`, `reports/`, `state/`) by hand

## Checks

- [ ] `pytest` passes
- [ ] `python scripts/validate.py` and `python scripts/moderate.py` pass
- [ ] `python scripts/generate.py` was run and its output committed (CI checks this)

New streams are never merged without maintainer review of the source and the content.
