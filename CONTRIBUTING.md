# Contributing to Nexonic IPTV

Thank you for helping! Quality and legality come first — please read [docs/SOURCE_POLICY.md](docs/SOURCE_POLICY.md)
and [docs/CONTENT_POLICY.md](docs/CONTENT_POLICY.md) before suggesting channels.

## Ways to help
- **Suggest a channel** with the issue form (evidence required) or a PR that adds a record to `data/pending/`.
- **Report problems**: broken stream, wrong metadata, adult content, copyright concern — use the issue forms.
- **Code**: verifier, generator, tests, website.

## Every suggested channel must include
Official name · country (ISO 3166-1 alpha-2) · language(s) (ISO 639-1) · category · stream URL · official broadcaster
website · evidence page showing the broadcaster offers it free · confirmation it is not adult-oriented.

## How to suggest a channel
1. Search [PLAYLISTS.md](PLAYLISTS.md) and `data/` to see if it is already listed, pending or rejected.
2. Open the [channel suggestion form](https://github.com/Shahrukhalid/nexonic-iptv/issues/new?template=2-suggest-channel.yml)
   and fill in every field. **Official evidence is required**: the broadcaster's own page that plays the stream free
   of charge. Third-party lists, restreams and screenshots are not evidence.
3. Or open a pull request that adds a record to `data/pending/` (see below).

## How to report a broken stream
Use the [broken channel form](https://github.com/Shahrukhalid/nexonic-iptv/issues/new?template=1-broken-channel.yml).
Say which country you are in and whether the stream plays on the broadcaster's own site; many streams are limited to
their home country and are labelled that way. For bugs in the scripts or website use the
[bug report form](https://github.com/Shahrukhalid/nexonic-iptv/issues/new?template=7-bug-report.yml).

## How review and authorization work
- New channels start in `data/pending/`. A maintainer reviews the evidence page, checks that the stream host belongs
  to the broadcaster or its CDN, that no login, token or DRM is involved, and that the content is not adult-oriented.
- Approved records move to `data/approved/` with their review details. Channels that do not qualify go to
  `data/rejected/` with a reason so they are not re-added.
- After approval a channel is published only once it passes a live check. Daily verification then keeps its
  lifecycle state up to date and quarantines it if it keeps failing ([docs/AUTOMATION.md](docs/AUTOMATION.md)).
- Stream additions are never auto-merged.

## Record format
See `nexonic/models.py` for the full schema and any file in `data/approved/` for examples. Unknown facts must be
written as `unknown` — never guessed. Do not add logos unless the owner allows reuse.

## Rules for pull requests
- Do not edit generated files (`playlists/`, `PLAYLISTS.md`, `reports/`, `state/`, README stats block) by hand; run
  `python scripts/generate.py`. CI fails if they are out of date.
- Contributors add new channels to `data/pending/`. Only maintainers move records to `data/approved/` after reviewing
  the source and the content. Stream additions are never auto-merged.
- CI runs with read-only permissions and never performs live network checks on URLs from pull requests.

## Development
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
ruff check . && ruff format --check .
pytest
python scripts/validate.py && python scripts/moderate.py && python scripts/generate.py --check
cd website && npm ci && npm run build && npm run check-links
```

By contributing you agree that code is licensed under MIT and data under CC0 1.0, and to follow the
[Code of Conduct](CODE_OF_CONDUCT.md).
