# Always-on Xtream Codes login

`xtream-worker.js` runs on Cloudflare Workers (free plan: 100,000 requests a day, no card) and gives IPTV apps a
permanent server address with the public login `nexonic` / `free`. It reads the static files that the website
deployment writes to `/xtream/` (`scripts/xtream_export.py`), so it always shows the current playlists, and every
stream is a redirect to the broadcaster's own URL.

## One-time setup (about 5 minutes)

1. Create a free Cloudflare account and open **Workers & Pages** once, so Cloudflare gives you a `workers.dev`
   subdomain.
2. Copy your **Account ID** (Workers & Pages overview, right-hand side).
3. Create an API token: **My Profile > API Tokens > Create Token > "Edit Cloudflare Workers"** template, then
   **Create Token** and copy it.
4. In this repository on GitHub: **Settings > Secrets and variables > Actions > New repository secret**. Add
   `CLOUDFLARE_API_TOKEN` (the token) and `CLOUDFLARE_ACCOUNT_ID` (the account id).
5. **Actions > Deploy Xtream login > Run workflow.** When it finishes, the login lives at
   `https://nexonic-iptv.<your-subdomain>.workers.dev`.

Later changes to `cloud/` deploy by themselves. Channel updates need no deployment at all: the Worker reads the
latest files from the website.

## Settings

`wrangler.toml` holds the public login (`XTREAM_USER`, `XTREAM_PASSWORD`) and the address of the website that serves
the data (`DATA_URL`). To use your own domain, add it to the Worker in the Cloudflare dashboard.
