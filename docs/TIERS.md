# Tiers: Official, Community and Free VOD

Nexonic publishes three kinds of lists. They use different admission rules, are verified differently and are never
mixed in one playlist or one number.

| | Official | Community live | Free VOD |
|---|---|---|---|
| What it is | Live channels streamed free by the broadcaster itself | Live streams from public lists | Films and TV from open collections |
| Source | `data/approved/` (curated and auto-admitted by owner domain) | iptv-org/iptv streams, iptv-org/database, the extra M3U lists in `config/pipeline.toml` | Internet Archive collections (public domain or Creative Commons items) |
| Authorization basis | Evidence that the rights holder publishes it | None. The stream is listed because it is in a public list and passes the filters below | The item's recorded licence |
| Verification | Daily, every channel, multi-level | Rotating budgeted slice per day; a stream is **verified** only after a check succeeded | Metadata re-read from the source; the file is not downloaded |
| Playlists | `playlists/*.m3u` | `playlists/community/` | `playlists/vod/` |
| Section in reports | `official` | `community` | `vod` |

The Official tier is unchanged by the other two. Community and VOD files are generated from separate state and cannot
overwrite an official file (the generator refuses a clash).

## Official

See [SOURCE_POLICY.md](SOURCE_POLICY.md). In addition to the existing playlists, `playlists/quality/{4k,1080p,720p,sd}.m3u`
group published official channels by the resolution the checker **measured** (best variant of an HLS master playlist,
or the probed rendition of a single stream). Channels with no measurement are in no quality playlist.

## Community live

A stream is admitted to the community catalogue only if **all** hold:

1. Not on the iptv-org blocklist (`nsfw` or `dmca`) and not marked closed.
2. Passes the adult-content screening used for the official tier (`nexonic/moderation.py`).
3. URL policy: `http` or `https`, no credentials, no token, signature or expiry parameter, no IP-literal host.
   Known restream or aggregator hosts are allowed only when the URL carries no token (`community.allow_restream_hosts`).
4. No special request headers (referrer or user agent) needed.
5. Not in `data/community-exclusions.yaml` (see [Takedown](#takedown)).
6. Not a duplicate: a stream is dropped when its normalised URL or its channel identity is already published in an
   earlier tier, or earlier in the community catalogue. The official tier always wins.

Metadata (name, id, country, languages, categories, `tvg-id`, quality label) comes from the source lists; categories
are normalised to the project's set. A logo is used only when the iptv-org database lists one.

### What "verified" and "untested" mean

- **Verified**: the latest check of the stream worked, within `community.verified_days` (7), or it worked recently and
  failed only once without being quarantined. Listed in `playlists/community/verified.m3u`.
- **Untested**: never checked, last check too old, inconclusive, or only reachable from some regions. Listed in
  `playlists/community/untested.m3u` with the group `Untested | <Country>`. These streams have **not** been confirmed
  working and are never described as working.
- **Failing**: the last check failed. Held back from every playlist until a later check succeeds.

Country, language, category and quality playlists under `playlists/community/` label each entry `| Verified` or
`| Untested` in its group (`x-status` attribute) and carry `x-tier="community"`.

### Daily validation

The daily `scripts/verify.py` run first verifies the official channels exactly as before. Then, inside the same
process and bounded by the same workflow, it:

1. refreshes the catalogue (when older than `community.refresh_max_age_hours`) from bounded downloads; a failed or
   implausibly small refresh keeps the last good snapshot in `state/community/catalog.json`;
2. checks a rotating slice: never-checked streams first, then the oldest-checked, at most `max_checks_per_run`, at most
   `max_per_host_per_run` per host, no new check after `run_budget_seconds` or after `total_deadline_minutes` since the
   run started. Failed streams wait `retry_failed_days`, quarantined ones `retry_quarantined_days`. No FFprobe is used;
3. records results in `state/community/history.json` (compact, last `history_per_stream` results) and derives the
   lifecycle with the same code as the official tier;
4. refreshes the free VOD cache.

Errors in steps 1 to 4 are reported as warnings and never change the official results. All knobs are in the
`[community]` and `[vod]` sections of `config/pipeline.toml`.

The very first run has no catalogue: it builds one, then checks the first slice. Until a stream is checked it is
untested.

## Free VOD

`scripts/vod.py` reads Internet Archive collections listed in `[[vod.collections]]` using the public advanced-search and
metadata endpoints (free, no key). An item is kept only when:

- its licence URL is a Creative Commons licence or public-domain dedication (`creativecommons.org` host), or its rights
  text says public domain without negation (the licence URL is decisive when both exist);
- it has no access restriction and is not excluded in `data/community-exclusions.yaml` (`vod:` list);
- it has a playable file, preferring h.264 MP4, then other MPEG4.

The licence is stored with every item and written to the playlist entry (`x-licence`), with the duration. The refresh
is incremental and cached in `state/vod/`: a few search pages and a limited number of metadata documents per day.
Playlists: `playlists/vod/movies.m3u`, `series.m3u`, `playlists/vod/genres/<genre>.m3u`, `playlists/vod/decades/<decade>.m3u`.
Streams are direct links to archive.org; Nexonic hosts nothing.

### Other free VOD sources considered

| Source | Status |
|---|---|
| Internet Archive (public domain and Creative Commons collections) | **Implemented** |
| NASA media library and NASA+ | Not implemented. NASA media is generally free to use, but there is no stable bulk metadata API for full programmes, and the live channels are already covered by the official tier |
| Wikimedia Commons video | Considered. Licences are per file and mostly short clips; the file list needs per-file licence parsing. A good contribution |
| Public broadcasters' free on-demand catalogues | Not implemented. Per-title rights and geo limits; suited to the channel-suggestion path with evidence |
| Open movies (for example Blender Foundation films) | Available through Internet Archive and Commons where uploaded, so covered when listed there |

## Legal notes

- Nexonic stores and serves no video. Playlists contain links.
- The community tier **does not claim** that the rights holder authorised the stream. It lists streams from openly
  published lists and removes anything on request. Players use these links at their own risk; see
  [DISCLAIMER.md](../DISCLAIMER.md) and [LEGAL.md](LEGAL.md).
- Public domain status varies by country. The VOD tier records the licence stated by the uploader; a record is not a
  legal opinion. Report mistakes through the copyright form.
- Third-party channel names and logos belong to their owners and are used only to identify streams.

## Takedown

A rights holder, or anyone who sees something inappropriate, can:

1. Open the [copyright form](https://github.com/Shahrukhalid/nexonic-iptv/issues/new?template=5-copyright-concern.yml)
   (or the [adult content form](https://github.com/Shahrukhalid/nexonic-iptv/issues/new?template=3-report-adult-content.yml))
   with the stream URL, host, channel id or Internet Archive identifier.
2. Or send a pull request adding it to `data/community-exclusions.yaml` (`urls`, `hosts`, `channels`, `vod`).

The file is applied when the catalogue is built **and** on every playlist generation, so a merged change removes the
entry from all community and VOD playlists on the next generation (the generate workflow runs on changes under
`data/`). A host entry also covers its sub-domains. Maintainers act on requests promptly and without requiring a reason.
