"""Project-wide public URLs. Override with environment variables when forking."""

import os

REPO = os.environ.get("NEXONIC_REPO", "Shahrukhalid/nexonic-iptv")
SITE_URL = os.environ.get("NEXONIC_SITE_URL", "https://shahrukhalid.github.io/nexonic-iptv").rstrip("/")
RAW_BASE = os.environ.get("NEXONIC_RAW_BASE", f"https://raw.githubusercontent.com/{REPO}/main").rstrip("/")
REPO_URL = f"https://github.com/{REPO}"


def playlist_url(rel_path: str) -> str:
    """Public URL of a generated playlist (served by GitHub Pages with the site)."""
    return f"{SITE_URL}/{rel_path.lstrip('/')}"
