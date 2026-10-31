# Always-on Xtream Codes login

`xtream-worker.js` runs on Cloudflare Workers (free plan: 100,000 requests a day, no card) and gives IPTV apps a
permanent server address with the public login `nexonic` / `free`. It reads the static files that the website
deployment writes to `/xtream/` (`scripts/xtream_export.py`), so it always shows the current playlists, and every
stream is a redirect to the broadcaster's own URL.

Live address: `https://nexonic-iptv.shahrukhalid.workers.dev`

## How it is deployed

The Cloudflare account is linked to this GitHub repository (Workers & Pages > Create > Import a repository) with
**Path** `/cloud`, an empty build command and the deploy command `npx wrangler deploy`. Every push to `main` that
changes `cloud/` deploys again by itself; channel updates need no deployment, because the Worker reads the latest
files from the website. Keep "Protect with Cloudflare Access" off, or apps cannot log in.

## Settings

`wrangler.toml` holds the public login (`XTREAM_USER`, `XTREAM_PASSWORD`) and the address of the website that serves
the data (`DATA_URL`). To use your own domain, add it to the Worker in the Cloudflare dashboard.
