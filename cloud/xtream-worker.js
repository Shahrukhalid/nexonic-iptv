// Always-on Xtream Codes gateway for Nexonic IPTV (runs as a Cloudflare Worker).
//
// Apps log in with the server address, username `nexonic` and password `free`. Every answer comes from the static
// files the website deployment writes to <DATA_URL>/xtream/ (scripts/xtream_export.py), so this script only picks a
// file and follows redirects. Streams are redirects to the URLs in the playlists; no video passes through here.

const BUCKETS = 256;
const STREAM = /^\/(live|movie|series)\/([^/]+)\/([^/]+)\/(\d+)(?:\.[a-z0-9]{1,5})?$/;
const CACHE = { cf: { cacheTtl: 600, cacheEverything: true } };

const json = (data, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "access-control-allow-origin": "*" },
  });

const text = (body, status, type = "text/plain") =>
  new Response(body, { status, headers: { "content-type": type, "access-control-allow-origin": "*" } });

function sameText(a, b) {
  // constant-time comparison of two short strings
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

async function file(env, rel) {
  const base = (env.DATA_URL || "").replace(/\/$/, "");
  const r = await fetch(`${base}/xtream/${rel}`, CACHE);
  return r.ok ? r : null;
}

async function passJson(env, rel, fallback) {
  const r = await file(env, rel);
  if (!r) return json(fallback);
  return new Response(r.body, {
    headers: { "content-type": "application/json; charset=utf-8", "access-control-allow-origin": "*" },
  });
}

function account(env, url) {
  const now = Math.floor(Date.now() / 1000);
  const https = url.protocol === "https:";
  return {
    user_info: {
      username: env.XTREAM_USER,
      password: env.XTREAM_PASSWORD,
      message: "Nexonic IPTV: free-to-air channels, free for everyone.",
      auth: 1,
      status: "Active",
      exp_date: null,
      is_trial: "0",
      active_cons: "0",
      created_at: "1730419200",
      max_connections: "100",
      allowed_output_formats: ["m3u8", "ts"],
    },
    server_info: {
      url: url.hostname,
      port: url.port || (https ? "443" : "80"),
      https_port: url.port || "443",
      server_protocol: https ? "https" : "http",
      rtmp_port: "0",
      timezone: "UTC",
      timestamp_now: now,
      time_now: new Date(now * 1000).toISOString().replace("T", " ").slice(0, 19),
    },
  };
}

async function playerApi(env, url, q) {
  const action = q.get("action") || "";
  const cid = (q.get("category_id") || "").replace(/\D/g, "");
  const id = (name) => (q.get(name) || "").replace(/\D/g, "");
  switch (action) {
    case "":
      return json(account(env, url));
    case "get_live_categories":
      return passJson(env, "live_categories.json", []);
    case "get_live_streams":
      return passJson(env, cid ? `live/${cid}.json` : "live_streams.json", []);
    case "get_vod_categories":
      return passJson(env, "vod_categories.json", []);
    case "get_vod_streams":
      return passJson(env, cid ? `vod/${cid}.json` : "vod_streams.json", []);
    case "get_vod_info":
      return passJson(env, `vod_info/${id("vod_id") || 0}.json`, { info: {}, movie_data: {} });
    case "get_series_categories":
      return passJson(env, "series_categories.json", []);
    case "get_series":
      return passJson(env, "series.json", []);
    case "get_series_info":
      return passJson(env, `series_info/${id("series_id") || 0}.json`, { info: {}, episodes: {}, seasons: [] });
    case "get_short_epg":
    case "get_simple_data_table":
      return json({ epg_listings: [] });
    default:
      return json([]);
  }
}

async function handle(request, env) {
  const url = new URL(request.url);
  let q = url.searchParams;
  if (request.method === "POST") {
    const form = (await request.text()).slice(0, 4096);
    if (form) q = new URLSearchParams(form);
  }
  const user = env.XTREAM_USER;
  const pass = env.XTREAM_PASSWORD;
  const ok = (u, p) => sameText(u || "", user) && sameText(p || "", pass);
  const path = url.pathname;

  if (path === "/" || path === "/health") {
    const meta = await file(env, "meta.json");
    return json({ service: "Nexonic IPTV Xtream gateway", ...(meta ? await meta.json() : {}) });
  }
  const m = STREAM.exec(path);
  if (m) {
    const [, kind, u, p, sid] = m;
    if (!ok(decodeURIComponent(u), decodeURIComponent(p))) return text("invalid login\n", 401);
    const r = await file(env, `s/${kind}/${Number(sid) % BUCKETS}.json`);
    const target = r ? (await r.json())[sid] : null;
    if (!target || !/^https?:\/\//.test(target)) return text("unknown stream\n", 404);
    return new Response(null, { status: 302, headers: { location: target, "cache-control": "no-store" } });
  }
  if (["/player_api.php", "/get.php", "/xmltv.php", "/panel_api.php"].includes(path)) {
    if (!ok(q.get("username"), q.get("password"))) {
      return path === "/player_api.php" ? json({ user_info: { auth: 0 } }) : text("invalid login\n", 401);
    }
    if (path === "/get.php") {
      const r = await file(env, "m3u.txt");
      if (!r) return text("playlist not available\n", 503);
      const body = (await r.text())
        .replaceAll("__BASE__", url.origin)
        .replaceAll("__USER__", encodeURIComponent(user))
        .replaceAll("__PASS__", encodeURIComponent(pass));
      return text(body, 200, "audio/x-mpegurl; charset=utf-8");
    }
    if (path === "/xmltv.php") {
      return text('<?xml version="1.0" encoding="UTF-8"?>\n<tv generator-info-name="Nexonic IPTV"></tv>\n', 200, "application/xml");
    }
    return playerApi(env, url, q);
  }
  return text("not found\n", 404);
}

export default {
  async fetch(request, env) {
    try {
      return await handle(request, env);
    } catch (err) {
      return text("temporary error, please try again\n", 503);
    }
  },
};
