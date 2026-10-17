// Copies generated project data into the site before every build. The site never invents numbers:
// everything it shows comes from reports/*.json and playlists/index.json produced by scripts/generate.py.
import { execFileSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const site = join(here, "..");
const repo = join(site, "..");
const dataDir = join(site, "src", "data");
mkdirSync(dataDir, { recursive: true });

const files = {
  "channels.json": join(repo, "reports", "channels.json"),
  "statistics.json": join(repo, "reports", "statistics.json"),
  "verification.json": join(repo, "reports", "verification.json"),
  "playlists.json": join(repo, "playlists", "index.json"),
};
for (const [name, src] of Object.entries(files)) {
  if (!existsSync(src)) throw new Error(`missing ${src}: run python scripts/generate.py first`);
  writeFileSync(join(dataDir, name), readFileSync(src));
}

// Serve the playlists with the site so URLs are https://<site>/<base>/playlists/...
const pub = join(site, "public", "playlists");
rmSync(pub, { recursive: true, force: true });
cpSync(join(repo, "playlists"), pub, { recursive: true });
// Social preview image: rendered from assets/og.svg with rsvg-convert (installed in the deploy workflow).
const ogOut = join(site, "public", "og.png");
try {
  execFileSync("rsvg-convert", ["-w", "1200", "-h", "630", "-o", ogOut, join(site, "assets", "og.svg")]);
} catch {
  if (!existsSync(ogOut)) console.warn("warning: rsvg-convert not available; og.png not rendered");
}
console.log("synced data and playlists into website/");
