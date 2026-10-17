# Changelog

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
