// @ts-check
import { defineConfig } from "astro/config";

// Public URL of the GitHub Pages site. Override with NEXONIC_SITE / NEXONIC_BASE when forking.
const site = process.env.NEXONIC_SITE ?? "https://shahrukhalid.github.io";
const base = process.env.NEXONIC_BASE ?? "/nexonic-iptv";

export default defineConfig({
  site,
  base,
  trailingSlash: "always",
  build: { format: "directory" },
  compressHTML: true,
});
