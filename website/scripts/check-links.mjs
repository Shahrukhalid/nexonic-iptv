// Fails if any internal link or asset in the built site points at a file that does not exist.
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const dist = join(dirname(fileURLToPath(import.meta.url)), "..", "dist");
const base = (process.env.NEXONIC_BASE ?? "/nexonic-iptv").replace(/\/$/, "");
const pages = [];
const walk = (d) => readdirSync(d).forEach((f) => {
  const p = join(d, f);
  if (statSync(p).isDirectory()) walk(p);
  else if (p.endsWith(".html")) pages.push(p);
});
walk(dist);

let broken = 0;
let checked = 0;
for (const page of pages) {
  const html = readFileSync(page, "utf8");
  for (const m of html.matchAll(/(?:href|src)="([^"]+)"/g)) {
    let url = m[1];
    if (/^(https?:|mailto:|data:|#|javascript:)/.test(url)) continue;
    url = url.split("#")[0].split("?")[0];
    if (!url) continue;
    if (!url.startsWith(base + "/") && url !== base) {
      console.error(`outside base: ${url} in ${page}`);
      broken++;
      continue;
    }
    const rel = decodeURIComponent(url.slice(base.length)) || "/";
    let target = join(dist, rel);
    if (rel.endsWith("/")) target = join(target, "index.html");
    checked++;
    if (!existsSync(target)) {
      console.error(`broken: ${url} in ${page.slice(dist.length)}`);
      broken++;
    }
  }
}
console.log(`${pages.length} pages, ${checked} internal links checked, ${broken} broken`);
process.exit(broken ? 1 : 0);
