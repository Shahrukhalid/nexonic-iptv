# SEO plan

Goal: be found by people looking for **legal, free, family-friendly** live TV playlists — without keyword stuffing,
fake reviews or invented numbers.

## Search intent we serve
| Intent | Typical queries | Page |
|---|---|---|
| Get a playlist | "free iptv playlist m3u", "m3u live tv playlist", "iptv m3u url" | Home, /playlists/ |
| Country | "germany free tv m3u", "free live tv india playlist" | /countries/<cc>/ (one indexable page per country) |
| Reliability | "working iptv playlist", "verified iptv streams" | /status/, Verified playlist |
| Safety | "family friendly iptv", "iptv without adult channels" | Home, /about/, /faq/ |
| How-to | "how to add m3u to vlc", "kodi iptv simple client m3u" | /how-to-watch/ |
| Open source | "open source iptv list github" | README, GitHub topics |

We never describe pay-TV or premium sports as available; we do not target such queries.

## Implemented
- Unique `<title>` and meta description per page; canonical URLs (absolute, trailing slash).
- Open Graph and Twitter card tags with a 1200×630 `og.png`.
- Semantic HTML (one `h1`, ordered headings, landmarks, skip link, labelled controls).
- Structured data: `WebSite` + `Dataset` (home), `BreadcrumbList` (country pages), `FAQPage` (FAQ), `HowTo` (VLC).
- `sitemap.xml` with every page and country page; `lastmod` = latest verification run.
- `robots.txt` (effective only when the site has its own domain; see note below).
- Static HTML, no client framework, no third-party requests — fast and private.
- Internal linking: home → country hub → country pages → channel evidence; footer links to policies.

**Project-site note:** on `shahrukhalid.github.io/nexonic-iptv/` crawlers read robots.txt from the domain root, which
this repo does not control. Submit `sitemap.xml` directly in Google Search Console / Bing Webmaster Tools.

## Launch checklist
- [ ] Pages source set to GitHub Actions; site loads at the canonical URL.
- [ ] Verify the site in Google Search Console (HTML file or meta tag) and Bing Webmaster Tools; submit the sitemap.
- [ ] Repository description and topics set (see README "About this repository").
- [ ] Social preview image set to the built `og.png` (rendered from `website/assets/og.svg`) (Settings → General).
- [ ] Check pages with Lighthouse (performance, accessibility, SEO ≥ 90).
- [ ] Validate structured data with Google's Rich Results Test.
- [ ] Announce in relevant, rule-abiding communities (e.g. iptv-org/awesome-iptv PR) — no spam.
- [ ] Re-check numbers on the site match `reports/statistics.json` after the first verification run.
