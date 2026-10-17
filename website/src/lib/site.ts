import channelsData from "../data/channels.json";
import playlistsData from "../data/playlists.json";
import statsData from "../data/statistics.json";
import verificationData from "../data/verification.json";

export const SITE_NAME = "Nexonic IPTV";
export const TAGLINE = "Free Live TV. Verified Streams. Worldwide.";
export const REPO_URL = "https://github.com/Shahrukhalid/nexonic-iptv";
export const RAW_BASE = "https://raw.githubusercontent.com/Shahrukhalid/nexonic-iptv/main";

export type Health = {
  score: number | null;
  grade: string;
  display_status: string;
  last_checked: string | null;
  last_success: string | null;
  last_status: string;
  checks_in_window: number;
  success_rate: number | null;
  median_latency_ms: number | null;
};

export type Channel = {
  id: string;
  name: string;
  broadcaster: string;
  country: string;
  country_name: string;
  flag: string;
  languages: string[];
  language_names: string[];
  categories: string[];
  website: string;
  stream_url: string;
  protocol: string;
  epg_id: string | null;
  geo_restricted: boolean | "unknown";
  geo_regions: string[];
  evidence_url: string;
  authorization_basis: string;
  admission: "automated" | "curated";
  in_verified_playlist: boolean;
  health: Health;
};

export type PlaylistItem = { path: string; kind: string; key: string; name: string; count: number; url: string };

export const channels = (channelsData as { channels: Channel[] }).channels;
export const playlists = (playlistsData as { playlists: PlaylistItem[]; reference_time: string | null }).playlists;
export const referenceTime = (playlistsData as { reference_time: string | null }).reference_time;
export const stats = statsData as any;
export const verification = verificationData as any;

/** Prefix an internal path with the configured base path. */
export function url(path = "/"): string {
  const base = import.meta.env.BASE_URL.replace(/\/$/, "");
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${base}${p}`;
}

export function absolute(path = "/"): string {
  return new URL(url(path), import.meta.env.SITE).toString();
}

export function playlistUrl(rel: string): string {
  return absolute(`/${rel.replace(/^\//, "")}`);
}

export const CATEGORY_NAMES: Record<string, string> = {
  business: "Business", culture: "Culture", documentary: "Documentary", education: "Education",
  entertainment: "Entertainment", general: "General", kids: "Kids", legislative: "Legislative",
  lifestyle: "Lifestyle", movies: "Movies", music: "Music", news: "News", science: "Science",
  sports: "Sports", weather: "Weather",
};

export const STATUS_LABELS: Record<string, string> = {
  "verified-recently": "Verified recently",
  "previously-working": "Previously working",
  "currently-failing": "Currently failing",
  "geo-restricted": "Geo-restricted",
  "not-tested": "Not yet tested",
  unknown: "Unknown",
};

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "never";
  const d = new Date(iso);
  return d.toISOString().replace("T", " ").replace(/:\d\dZ$/, " UTC").replace(".000", "");
}

export function countries() {
  const map = new Map<string, { code: string; name: string; flag: string; count: number }>();
  for (const c of channels) {
    const e = map.get(c.country) ?? { code: c.country, name: c.country_name, flag: c.flag, count: 0 };
    e.count++;
    map.set(c.country, e);
  }
  return [...map.values()].sort((a, b) => a.name.localeCompare(b.name));
}

export function playlistFor(kind: string, key: string): PlaylistItem | undefined {
  return playlists.find((p) => p.kind === kind && p.key === key);
}

export const latestRun = verification?.latest_run ?? null;
