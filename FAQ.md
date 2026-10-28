# FAQ

**Is it free?** Yes — no subscriptions, ads, accounts or paid tiers.

**Is it legal?** Nexonic links only to streams that broadcasters offer free to the public, with recorded evidence,
hosts no video and bypasses nothing. Laws differ by country; this is not legal advice. See [docs/LEGAL.md](docs/LEGAL.md).

**Why so few channels?** Only official free streams from broadcaster-controlled servers are accepted, and broken ones
are dropped. See [docs/COMPETITOR_ANALYSIS.md](docs/COMPETITOR_ANALYSIS.md).

**A channel doesn't play.** It may be limited to its home country, off-air, or changed. Check the status page; report
it if it stays broken.

**What does "Verified" mean?** Within the last 48 hours our checker fetched the playlist, a media playlist and real
video bytes from GitHub's servers. It does not guarantee playback where you are.

**What is the Nexonic Health Score?** A 0–100 score from recorded checks over 14 days; shows NOT ENOUGH DATA until there
are at least 3 scorable checks on 2 days. Formula: [docs/VERIFICATION.md](docs/VERIFICATION.md#nexonic-health-score).

**Are there adult channels?** No. Report anything inappropriate and it will be removed.

**Is it suitable for children?** Channels are screened and kids channels are grouped, but broadcasters choose their
programmes; we cannot review every broadcast.

**Can I add an EPG?** Playlists use iptv-org `tvg-id` values; point your player at a guide built with iptv-org/epg.

**Can I use the data?** Yes — data is CC0 and code is MIT.

**How do I suggest a channel?** Use the
[channel suggestion form](https://github.com/Shahrukhalid/nexonic-iptv/issues/new?template=2-suggest-channel.yml).
You must include official evidence: a page on the broadcaster's own website that plays the stream free of charge,
the stream URL, the country, language and category, and confirmation that the channel is not adult-oriented. Streams
from restreamers, IP addresses, tokens or logins are not accepted. See [CONTRIBUTING.md](CONTRIBUTING.md).

**How do I report a broken stream?** Use the
[broken channel form](https://github.com/Shahrukhalid/nexonic-iptv/issues/new?template=1-broken-channel.yml) with the
channel, the playlist, your country and player. First check that the channel is not limited to its home country and
whether it plays on the broadcaster's own site. Channels that keep failing are quarantined and leave `verified.m3u`
automatically, and they are restored after a successful check.

**How are suggestions reviewed and authorized?** Contributed channels go to `data/pending/`. A maintainer checks that
the evidence page is the broadcaster's own, that the stream host belongs to the broadcaster or its CDN, that the
stream is free without a login or DRM, and that the content is not adult-oriented. Only then is the record moved to
`data/approved/`. Streams are never merged automatically. Rights holders can ask for removal with the
[copyright form](https://github.com/Shahrukhalid/nexonic-iptv/issues/new?template=5-copyright-concern.yml).

**What is quarantine?** A channel that fails several checks in a row over at least two days is quarantined and removed
from `verified.m3u` until it works again. Details: [docs/AUTOMATION.md](docs/AUTOMATION.md).

**How often are streams checked?** Every day at 03:17 UTC. Catalog discovery from public data runs daily at 01:41 UTC.
