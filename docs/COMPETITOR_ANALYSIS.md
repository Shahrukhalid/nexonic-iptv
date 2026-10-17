# Competitor analysis

**Date:** 17 October 2026. Sources: see [RESEARCH.md](RESEARCH.md).

| Capability | iptv-org/iptv | Free-TV/IPTV | **Nexonic IPTV** |
|---|---|---|---|
| Scale | ~10k+ streams | ~2,000 URLs | Small, curated (quality first) |
| Country playlists | Yes | Yes | Yes (ISO 3166-1 alpha-2 file names) |
| Language / category playlists | Yes | No | Yes (only non-empty ones) |
| Per-stream provenance & evidence | No | In PR text only | **Required field, validated in CI** |
| Host ownership rule | No | Informal | **Bare IPs, redirectors, restream hosts rejected** |
| Adult content | Removed since Jan 2024 | Excluded by policy | **Excluded by policy + 5 automated layers + tests** |
| Automated liveness checks | Partial | Manual | **Layered HLS checks + optional FFprobe, every day** |
| Check history | No | No | **Rolling history per channel** |
| Reliability score | No | No | **Nexonic Health Score (documented formula)** |
| Geo-restriction handling | Manual label | Manual mark | Label + check outcome `GEO_RESTRICTED`, never "broken" |
| "Verified" playlist | No | No | **`verified.m3u` = working in the last 48 h** |
| Deterministic output | Yes | Mostly | Yes (tested) |
| SSRF-safe checker | n/a | n/a | **Public-IP pinning, redirect re-validation** |
| Website | Directory site | No | Static site: countries, directory, status |
| License | Unlicense/CC0 | None | MIT (code) + CC0 (data) |

## Weaknesses we avoid
1. **Unauthorized restreams.** A large share of aggregator URLs point at bare IP addresses and resellers' servers.
   Nexonic's validator rejects IP-literal hosts and the source policy requires a broadcaster-controlled host.
2. **"HTTP 200 means working."** We parse the HLS manifest, follow one variant, and probe a small byte range of
   a media segment.
3. **Opaque reliability.** Users cannot tell whether a link worked yesterday. Nexonic publishes timestamps and history.
4. **Geo-blocked = broken.** Our checker records geo-restriction separately and the site explains it.
5. **Copy-paste licensing problems.** Free-TV has no license; we copy none of its content.

## Opportunities
- Be the family-safe, provenance-first playlist people can recommend without caveats.
- Offer an honest `verified.m3u` that changes daily.
- Provide a contributor experience built around evidence (issue forms that ask for it).

## Risks
- A small catalogue looks less impressive than aggregators. We accept this.
- Official streams change URLs; daily checks surface breakage quickly but someone must update records.
- Single-location checks (GitHub-hosted runners, mostly US) cannot see regional availability.
