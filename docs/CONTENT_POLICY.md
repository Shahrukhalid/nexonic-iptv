# Content policy

## Never included
- Adult-oriented, pornographic or sexually explicit channels.
- Pirated premium TV, unauthorized sports or PPV feeds, stolen subscription feeds.
- Anything requiring credentials, tokens, DRM circumvention, paywall bypass or geo-restriction bypass.
- Unauthorized restreams or proxies.

## Moderation pipeline
Every candidate passes, in order:
1. **Source legitimacy** — broadcaster-controlled host and an evidence page ([SOURCE_POLICY.md](SOURCE_POLICY.md)).
2. **Channel identity** — official name, broadcaster, website.
3. **Category classification** — from a fixed list; adult categories do not exist in the schema.
4. **Adult-content screening** — automated (below) plus a named human reviewer setting `adult_screening: pass`.
5. **Duplicate detection** — ids, normalised URLs, names per country (`records.cross_check`).
6. **Playlist syntax validation** — strict M3U parser on every generated file.
7. **Stream availability** — layered checks ([VERIFICATION.md](VERIFICATION.md)).
8. **Metadata completeness** — schema with `unknown` for unknown facts.

## Automated adult screening (`nexonic/moderation.py`)
Applied to name, aliases, description, broadcaster, website, categories, source notes, review notes, EPG id and URL:
- **Reject**: `is_nsfw`, human screening `fail`, Nexonic denylist ids/names/host patterns, EPG ids on iptv-org's NSFW
  lists, strong multi-language terms (including compounds and simple leetspeak), `18+`/`+18` patterns.
- **Quarantine**: names identical to iptv-org NSFW channel names, ambiguous terms (e.g. "hot", "private", "after dark"),
  human screening `uncertain`.
- Weak terms can be overridden per channel in `data/moderation/allowlist.yaml` after human review; strong terms cannot.
- Nothing quarantined or rejected can reach a playlist: `generate.py` applies `publication_gate` to every record,
  including records in `data/approved/`, and `validate.py` proves no pending/rejected URL appears in any file.

Tests in `tests/test_moderation.py` and `tests/test_generate.py` assert that known adult-oriented sample records, and
pending and rejected records, never enter a generated playlist. CI runs them on every PR.

## Automated tier
Auto-admitted records pass the same moderation gate (uncertain ones are quarantined in
`data/pending/auto-quarantine.yaml`), exclude channels iptv-org marks as NSFW or blocklists, and are labelled
"Auto-admitted" on the website. They are not individually human-reviewed; reports are acted on with priority.

## Live programming caveat
A broadcaster can change what it airs after review. We screen channels, not each programme, and do not promise every
broadcast is suitable for children.

## Reporting and removal
- Public: "Report adult-oriented content" issue form (label `adult-content`, priority).
- Private: GitHub private vulnerability reporting (see [SECURITY.md](../SECURITY.md)).
- Maintainer action: move the record to `data/rejected/` with a `rejection_reason`, add the id to
  `data/moderation/denylist.yaml`, merge. The next generation removes it from every playlist (see
  [MAINTENANCE.md](MAINTENANCE.md#fast-removal)).
