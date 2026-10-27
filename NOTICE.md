# Notices and attribution

## Licensing scope
Nexonic IPTV is dual-licensed by content type:

| What | Where | License |
|---|---|---|
| Source code, workflows and website source | everything not listed below | [MIT](LICENSE) |
| Channel data, generated playlists, reports and verification history | `data/`, `playlists/`, `reports/`, `state/` | [CC0 1.0](data/LICENSE) (public-domain dedication) |

Channel names and marks belong to their respective owners. GitHub's licence badge can only show one licence, so it
shows MIT; the table above is authoritative.

## Third-party data
| Data | Source | License | Used for |
|---|---|---|---|
| Country names, ISO codes and flag emoji (`nexonic/reference/countries.csv`) | [iptv-org/database](https://github.com/iptv-org/database) `data/countries.csv` | Unlicense / CC0 (public domain) | Country names and flags |
| NSFW channel IDs and names (`data/moderation/iptv-org-*.txt`) | iptv-org/database `data/blocklist.csv`, `data/channels.csv` | Unlicense / CC0 | Adult-content denylist |
| `tvg-id` values in records | iptv-org/database channel and feed IDs | Unlicense / CC0 | EPG matching |

Retrieved 17 October 2026. Public-domain data needs no attribution; we credit it as a courtesy and thank the
iptv-org community.

## Automated admission source
`scripts/expand_catalog.py` reads stream lists from [iptv-org/iptv](https://github.com/iptv-org/iptv) `streams/`
(Unlicense / public domain) and admits only streams served from the broadcaster's own domain
([source policy §2a](docs/SOURCE_POLICY.md#2a-automated-admission-tier)).

## Discovery sources (no content copied)
Candidate stream URLs were *discovered* by reading iptv-org/iptv `streams/` and Free-TV/IPTV `lists/`. Free-TV/IPTV
publishes no license, so none of its text, tables or code is reproduced. Every published record was re-described from
the broadcaster's own site and is subject to Nexonic's [source policy](docs/SOURCE_POLICY.md).

## Software
Python: httpx (BSD-3-Clause), Pydantic (MIT), PyYAML (MIT), pytest (MIT), Ruff (MIT).
Website: Astro (MIT). Optional: FFmpeg/FFprobe (LGPL/GPL, invoked as an external program, not distributed).

## Trademarks
Channel and broadcaster names are trademarks of their owners and are used only to identify channels. No affiliation
or endorsement is implied. No logos are distributed.
