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
