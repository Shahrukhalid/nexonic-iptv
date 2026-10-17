# Source policy

Nexonic IPTV publishes a link only when there is a **reasonable, documented basis** that the broadcaster or rights
holder intentionally offers the stream for free public viewing. A URL being reachable is not enough.

## 1. Accepted authorization bases
Every approved record sets `review.authorization_basis` to one of:

| Value | Meaning | Required evidence |
|---|---|---|
| `official-broadcaster-stream` | The broadcaster's own website or app plays this live stream to anyone, free of charge, without login. | `source.evidence_url` = the broadcaster's live page; stream host is on the broadcaster's domain. |
| `official-cdn-stream` | Same as above, but the host is a CDN hostname provisioned for the broadcaster (e.g. `dwamdstream102.akamaized.net`, `cdn-euronews.akamaized.net`). | Evidence URL + the CDN hostname must contain the broadcaster's name or be documented in `source.notes`. |
| `public-sector-stream` | A public body (parliament, government agency) publishes the stream for the public. | Evidence URL on the public body's domain. |

Public licence fees or taxes (for example a national TV licence) do not make a channel "paid"; a private paid
subscription does.

## 2. Always rejected
- Bare IP-address hosts, dynamic-DNS hosts, Xtream Codes / panel servers.
- Third-party restreams, re-encoders and redirect services (for example `*.pishow.tv`, `*.tangotv.in`, `mjh.nz`).
- FAST/aggregator app feeds (Pluto TV, Samsung TV Plus, Roku, Plex, Wurl/Amagi playouts) unless the channel owner
  itself publishes that URL for general use.
- Tokenized or signed URLs (`token=`, `hdnts=`, `wmsAuthSign=`, `sig=`, `exp=` …) and anything needing cookies,
  credentials or session values.
- Streams that require spoofed user agents, referers, or headers to play.
- DRM-protected streams (Widevine, PlayReady, FairPlay, SAMPLE-AES) — the checker marks them `UNSUPPORTED`.
- Pay-TV, PPV, premium sports and any adult-oriented channel.

## 2a. Automated admission tier
To cover as many legitimately free channels as possible, `scripts/expand_catalog.py` admits additional channels from
the public iptv-org data **only when all of these hold**:

1. **Owner domain** — the stream host's registrable domain equals the domain of the channel's official website in
   iptv-org/database, or shares its distinctive domain label (≥4 letters, e.g. `canli.tgrthaber.com` ↔
   `tgrthaber.com.tr`), or is a shared-CDN hostname named for that label (≥5 letters, e.g.
   `cdn-euronews.akamaized.net`). A broadcaster serving a stream from its own domain is publishing it itself.
2. The URL passes the URL policy (no IP hosts, tokens, credentials, restream/redirect hosts, odd ports).
3. No special headers (referrer / user agent) are required.
4. Not NSFW, not on iptv-org's NSFW or DMCA blocklist, not closed, not a shopping or religious channel.
5. Not a broadcaster under EU/UK/US broadcasting or entity sanctions, nor an outlet of an occupation authority, nor
   from a comprehensively sanctioned country (list in the script; such channels need a manual decision).
6. Nexonic's adult-content screening passes (uncertain → `data/pending/auto-quarantine.yaml`).
7. **It has passed at least one live verification** (`VERIFIED_WORKING`). Until then the generator does not publish it.

These records live in `data/approved/auto/`, carry `source.method: automated-domain-match`, are labelled
"Auto-admitted" on the website, and are not individually human-reviewed. Anyone can report one; maintainers can promote
it to the curated tier or reject it. The tier is refreshed monthly by `refresh-catalog.yml`.

## 3. Unclear cases
If ownership of the host, the free-to-view status, or the content classification cannot be established, the record
goes to `data/pending/` with a note. Pending records are never published.

## 4. Discovery sources
Maintainers may *discover* candidates anywhere (broadcaster sites, iptv-org/database, Free-TV lists), but discovery is
not evidence. Nothing is copied from sources whose license does not allow it (Free-TV/IPTV has no license; only facts
such as "broadcaster X runs a free stream" are used, then checked against the broadcaster's own site).

## 5. Metadata
- `tvg-id` values reuse iptv-org/database IDs (public domain) so players can match EPG guides.
- Logos are **not** included unless the owner permits reuse; the field stays empty.
- Unknown facts are written as `unknown`, never guessed.

## 6. Geographic restrictions
A broadcaster may limit a free stream to its own country. Nexonic labels these (`geo.restricted`) and does not try to
bypass them. A channel that is geo-restricted outside the checker's region is reported as `GEO_RESTRICTED`, not broken.

## 7. Removal
Rights holders can request removal through the "Copyright concern" issue form or privately via the contact in
[SECURITY.md](../SECURITY.md). See [MAINTENANCE.md](MAINTENANCE.md#fast-removal) — removal takes one commit and the next
generated playlist no longer contains the link.
