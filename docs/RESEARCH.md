# Research: the open-source IPTV ecosystem

**Research date:** 17 October 2026 (UTC+7)
**Method:** GitHub repository metadata (GitHub API via an authenticated client), raw source files fetched from
`raw.githubusercontent.com`, and programmatic analysis of the published playlists. All numbers below were
measured on the research date and will drift.

## 1. Reference projects

| Project | Stars | License | Last push (UTC) | Language | URL |
|---|---:|---|---|---|---|
| iptv-org/iptv | 141,130 | Unlicense (README shows CC0 badge) | 2026-10-17 | TypeScript | https://github.com/iptv-org/iptv |
| Free-TV/IPTV | 21,161 | **none declared** (no LICENSE file) | 2026-10-14 | Python | https://github.com/Free-TV/IPTV |
| iptv-org/epg | 3,388 | Unlicense | 2026-10-16 | TS/HTML | https://github.com/iptv-org/epg |
| iptv-org/database | 1,712 | Unlicense (README shows CC0 badge) | 2026-10-17 | JavaScript | https://github.com/iptv-org/database |
| iptv-org/api | 836 | Unlicense | 2026-10-17 | (generated JSON) | https://github.com/iptv-org/api |

Other active projects found by searching GitHub for `topic:iptv stars:>1000`:

| Project | Stars | What it is |
|---|---:|---|
| iptv-org/awesome-iptv | 12,680 | Curated list of IPTV apps and resources |
| Guovin/iptv-api | 25,604 | Chinese-language auto-collector/speed tester for live sources |
| fanmingming/live | 28,606 | Channel logo library and conversion tools (China-focused) |
| HerbertHe/iptv-sources | 9,027 | Auto-updated aggregations of other sources |
| 4gray/iptvnator | 7,395 | Cross-platform IPTV player (not a playlist) |
| tvheadend/tvheadend | 3,551 | TV streaming server for broadcast tuners |

## 2. Findings per reference

### 2.1 iptv-org/iptv
1. **Architecture.** Internal per-country source playlists in `streams/*.m3u`; TypeScript scripts (`scripts/commands/playlist/*`)
   generate public playlists; the output is deployed to a `gh-pages` branch and served at `https://iptv-org.github.io/iptv/`.
2. **Organization.** Grouped playlists by category, language, country, region, plus per-group files (`PLAYLISTS.md` lists
   1,282 playlist URLs). Stream IDs (`Channel.cc@Feed`) link each URL to a channel in iptv-org/database.
3. **Country/language classification.** Comes from the database (`country`, `broadcast_area`, `languages` on feeds).
4. **M3U generation.** `npm run playlist:generate` after `playlist:lint` (m3u-linter) and `playlist:validate`.
5. **Validation.** `playlist:test` exists, but stream liveness is mostly contributor-asserted; labels such as
   `[Geo-blocked]` and `[Not 24/7]` are added by hand. In the 32 country files sampled, **6,228** URLs carried 417
   `Geo-blocked` and 674 `Not 24/7` labels.
6. **Update frequency.** `update.yml` runs daily (`cron: '0 0 * * *'`) and on dispatch.
7. **Actions.** `check.yml` lints only changed files on PRs with `permissions: contents: read`; the update job uses a
   GitHub App token (secrets) and pins third-party actions to commit SHAs — a good practice we copy.
8. **Contribution.** Issue forms (add/edit/report/copyright claim) processed by a bot; PRs allowed. They reject Xtream
   Codes servers, tokenized links and unnecessary redirects.
9. **Licensing.** Code and data released to the public domain (Unlicense/CC0). Their README states that links are
   "user-submitted links to publicly available video stream URLs, which to the best of our knowledge have been
   intentionally made public by the copyright holders".
10. **Weaknesses.** Quantity-first: about **23 % (1,453 of 6,228)** of sampled URLs point at bare IP addresses, which
    in practice are frequently third-party restreams of commercial channels. No per-stream provenance or evidence
    field. No published health history. NSFW was only removed from distribution on 30 January 2024 (their PLAYLISTS.md).

### 2.2 Free-TV/IPTV
1. **Architecture.** Hand-edited Markdown tables in `lists/*.md`; `make_playlist.py` (≈175 lines) turns rows starting
   with `[>]` into `playlist.m3u8` and `playlists/playlist_<country>.m3u8`.
2. **Organization.** One group per Markdown file, country codes from a hard-coded map.
3. **Classification.** Manual; `Ⓖ` marks geo-blocking, `Ⓢ` SD, `Ⓨ` YouTube.
4. **Generation.** Simple string concatenation; no escaping beyond removing `"`.
5. **Validation.** None automated in the repo; reviewers test manually.
6. **Update frequency.** Merged PRs; last push 14 Oct 2026.
7. **Actions.** None needed for generation (playlist is committed).
8. **Contribution.** PR-only; "provide information to show that the channel is free"; TV licence fees do not count as
   a paid subscription.
9. **Licensing.** **No license file.** Its content therefore cannot be copied. Nexonic uses it only as a discovery
   pointer (facts such as which broadcasters run free streams), never copies its tables or text.
10. **Philosophy worth adopting.** "Quality over quantity", only officially free channels, no adult channels, one URL
    per channel. **Weaknesses:** of 2,013 URLs, 133 are YouTube pages, 22 go through a third-party redirect service
    (`mjh.nz`), and 201 come from FAST platforms (Pluto/Samsung/Roku/Wurl/Amagi) whose terms restrict use outside
    their own apps.

### 2.3 iptv-org/database
CSV files in `data/` (channels, feeds, categories, blocklist, …). `channels.csv` (31,631 rows) includes an `is_nsfw`
flag (374 rows `TRUE`). `blocklist.csv` lists 902 channel IDs: 367 with reason `nsfw`, 536 with reason `dmca`, each
with a reference link. The category taxonomy has 30 entries including `xxx`. Unlicense/CC0 — reusable with attribution
as a courtesy. Nexonic reuses the **nsfw blocklist IDs** as one layer of its adult-content defence and the channel IDs
as `tvg-id` values so players can match iptv-org/epg guides.

### 2.4 iptv-org/api
Static JSON published to `https://iptv-org.github.io/api/` (`channels.json`, `streams.json`, `blocklist.json`, …).
Stream objects carry `labels` (`Geo-blocked`, `Not 24/7`). Useful for discovery, but it does not record who checked a
stream, when, or from where.

### 2.5 iptv-org/epg
Node utilities that scrape program guides from hundreds of sites into XMLTV; daily workflow. Nexonic does not scrape
guides (site terms vary); it only stores `epg_id` so users can pair Nexonic playlists with a guide of their choice.

## 3. Conclusions that shaped Nexonic
- **Provenance is the gap.** None of the references stores *why* a stream is believed to be authorized. Nexonic
  requires an evidence URL, the broadcaster's site and an authorization basis for every published channel.
- **Host ownership is a cheap, strong signal.** Official streams live on the broadcaster's domain or a CDN hostname
  provisioned for it (for example `live.france24.com`, `tv-trtworld.medya.trt.com.tr`, `dwamdstream102.akamaized.net`).
  Bare IPs, unrelated CDNs and redirect services are excluded.
- **Verification must be recorded, not asserted.** Nexonic stores every check (timestamp, status, latency, level reached)
  and derives a transparent health score from that history.
- **Adult exclusion needs layers.** iptv-org's `is_nsfw` flag and blocklist plus our own lexicon, category checks,
  denylist and a quarantine path for uncertain records.
- **Pin actions, least privilege, no secrets on PRs** (from iptv-org's workflows).

## 4. Network limitation during the build session
The build sandbox's egress proxy did not allow connections to broadcaster stream hosts (requests were refused with
`403` at `CONNECT`). Live verification therefore runs in GitHub Actions; see `docs/VERIFICATION.md` and the current
state in `reports/verification.md`.
