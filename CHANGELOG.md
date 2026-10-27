# Changelog

## Unreleased
- Pipeline (#4): channel lifecycle states (`working`, `intermittent`, `unreachable`, `invalid`, `restricted`,
  `unknown`), quarantine of repeatedly failing channels with automatic restore, a publication guard in
  `scripts/validate.py`, a daily change report (`reports/changes.md`, `reports/changes.json`), settings in
  `config/pipeline.toml` and documentation in `docs/AUTOMATION.md`.
- Catalog (#3): 35 new official free channels.
- Docs: README rewritten around playlist setup, how playlists are organised, verification and legal limits, with a
  contents list; FAQ and CONTRIBUTING explain how to suggest a channel, report a broken stream and how review and
  authorization work; new bug report issue form; issue template contact links to the FAQ and Discussions.
- Verifier: channels that share a stream host are now checked one at a time, so time spent waiting for a busy host
  no longer counts against the 60 s per-channel limit (this could produce false `TIMEOUT` results for CDNs that host
  many channels). DNS pre-check uses port 80 for `http://` URLs.
- Reference data: a missing or malformed `countries.csv` now fails with a clear `ReferenceDataError`.
- Website: Astro 5.18.2 -> 7.3.8 (fixes the npm audit advisories in Astro, esbuild, sharp and zod).
- Deploy workflow: `pages: write` / `id-token: write` granted to the deploy job only.
- LICENSE is the plain MIT text (so GitHub can detect it); the code/data licensing scope is in NOTICE.md.

## 1.1.0 — 2026-10-17
- **49 new hand-curated channels** (now 116 manual records in 27 countries), each with the broadcaster's official
  free live page as evidence and a manifest-plus-segment stream check run from a browser outside the
  broadcaster's country (geo-limited channels are labelled). Highlights: 3Cat
  (TV3, El 33, SX3, 3CatInfo, Esport3, Plats Bruts and event channels), SVT1/SVT2/SVT Barn, NRK Super, ZDFneo,
  ServusTV, Yle Teema & Fem, ORF Kids, PBS Kids (four time zones), WORLD Channel, FNX, Classic Arts Showcase, Kanal 7,
  GZT, Señal Colombia, Balapan, Abai TV, LTV7 and Star Channel International.
- **New `series` category** (`playlists/categories/series.m3u`) for channels that mainly air TV series, telenovelas
  and dramas. iptv-org's `series` category now maps to it during automated admission.
- **Fixes to existing channels:**
  - France 24 (4 channels): `master.m3u8` now returns HTTP 403; switched to the per-bitrate playlist on the same
    official host.
  - TRT Belgesel: moved off the failing `-dai` host.
  - RTP (6 channels) moved to `pending`: RTP now serves live streams only through signed, expiring URLs (`tk=`),
    which the source policy does not allow.
  - ABC News Live and CBS News 24/7 moved to `pending`: their stored URLs return HTTP 404.
  - NASA TV moved to `rejected` (the channel has been phased out); RTÉ News moved to `rejected` (DRM-protected).
- Catalog refresh workflow: validation now runs after the playlists are regenerated, so removals no longer fail
  the job.

## 1.0.0 — 2026-10-17
Initial release.
- Automated admission tier: 532 channels from 100 countries whose stream host is on the broadcaster's own domain
  (iptv-org data), excluding NSFW/DMCA-blocklisted, closed, shopping, religious and sanctioned broadcasters; each is
  published only after passing a live check. Monthly refresh workflow.
- Channel schema with provenance, authorization basis, review and adult-screening fields.
- 77 approved records across 20 countries (official broadcaster or broadcaster-CDN streams); 4 pending, 4 rejected
  examples kept to prevent re-adding.
- Layered verifier with SSRF protection, HLS parsing, media sniffing and optional FFprobe.
- Nexonic Health Score; deterministic generator for global, verified, country, language and category playlists.
- Five-layer adult-content moderation with iptv-org NSFW lists.
- Astro website (country hub, directory, status, guides) and SEO assets.
- CI, daily verification, generation and Pages deployment workflows.
- No live verification has run yet at release time; all channels start as `NOT_TESTED`.
