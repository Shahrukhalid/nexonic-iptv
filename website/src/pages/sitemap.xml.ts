import type { APIRoute } from "astro";
import { absolute, countries, referenceTime } from "../lib/site";

export const GET: APIRoute = () => {
  const paths = [
    "/", "/countries/", "/channels/", "/playlists/", "/how-to-watch/", "/status/", "/about/", "/contribute/",
    "/report/", "/faq/",
    ...countries().map((c) => `/countries/${c.code}/`),
  ];
  const lastmod = referenceTime ? `<lastmod>${referenceTime.slice(0, 10)}</lastmod>` : "";
  const body = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${paths
    .map((p) => `  <url><loc>${absolute(p)}</loc>${lastmod}</url>`)
    .join("\n")}\n</urlset>\n`;
  return new Response(body, { headers: { "Content-Type": "application/xml" } });
};
