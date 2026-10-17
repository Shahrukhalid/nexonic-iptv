import type { APIRoute } from "astro";
import { absolute } from "../lib/site";

// Note: on a project site (user.github.io/repo/) crawlers read robots.txt from the domain root, which this
// repository does not control. This file still documents intent and is used if the site moves to its own domain.
export const GET: APIRoute = () =>
  new Response(`User-agent: *\nAllow: /\n\nSitemap: ${absolute("/sitemap.xml")}\n`, {
    headers: { "Content-Type": "text/plain" },
  });
