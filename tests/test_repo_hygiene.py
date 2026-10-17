"""Workflow safety, secret scanning, and website build output."""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def load(p):
    data = yaml.safe_load(p.read_text())
    data["on"] = data.pop(True, data.get("on"))  # YAML 1.1 parses the key "on" as True
    return data


def test_expected_workflows_exist():
    names = {p.name for p in WORKFLOWS}
    assert {"ci.yml", "verify-streams.yml", "generate-playlists.yml", "deploy-pages.yml"} <= names


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_least_privilege(path):
    wf = load(path)
    assert "permissions" in wf, "top-level permissions must be explicit"
    assert "pull_request_target" not in (wf["on"] or {}), "pull_request_target is not allowed"
    perms = wf["permissions"]
    if "pull_request" in (wf["on"] or {}):
        assert perms == {"contents": "read"}, "PR workflows must be read-only"
    if perms.get("contents") == "write":
        assert "pull_request" not in wf["on"], "write-capable workflows must never run on PRs"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_actions_pinned_to_sha(path):
    for line in path.read_text().splitlines():
        m = re.search(r"uses:\s*([^\s#]+)", line)
        if m and not m.group(1).startswith("./"):
            assert re.search(r"@[0-9a-f]{40}$", m.group(1)), f"unpinned action: {m.group(1)}"


def test_no_secrets_in_verify_steps():
    text = (ROOT / ".github" / "workflows" / "verify-streams.yml").read_text()
    assert "secrets." not in text


@pytest.mark.skipif(shutil.which("actionlint") is None, reason="actionlint not installed")
def test_actionlint():
    subprocess.run(["actionlint", *map(str, WORKFLOWS)], check=True)


def test_secret_scanner_detects_and_repo_is_clean(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import scan_secrets
    finally:
        sys.path.remove(str(ROOT / "scripts"))
    bad = tmp_path / "leak.txt"
    bad.write_text("token = 'ghp_" + "A" * 36 + "'\n-----BEGIN OPENSSH " + "PRIVATE KEY-----\n")
    assert len(scan_secrets.scan([bad])) >= 2
    assert scan_secrets.scan(scan_secrets.files([])) == []


DIST = ROOT / "website" / "dist"


@pytest.mark.skipif(not DIST.exists(), reason="website not built (npm run build)")
def test_website_build_output():
    for rel in (
        "index.html",
        "countries/index.html",
        "channels/index.html",
        "status/index.html",
        "playlists/index.html",
        "how-to-watch/index.html",
        "faq/index.html",
        "sitemap.xml",
        "robots.txt",
        "playlists/all.m3u",
        "og.png",
    ):
        assert (DIST / rel).exists(), rel
    home = (DIST / "index.html").read_text()
    assert '<link rel="canonical"' in home and 'property="og:image"' in home
    sitemap = (DIST / "sitemap.xml").read_text()
    for cc in {p.stem for p in (ROOT / "playlists" / "countries").glob("*.m3u")}:
        assert f"/countries/{cc}/" in sitemap
        assert (DIST / "countries" / cc / "index.html").exists()


@pytest.mark.skipif(not DIST.exists() or shutil.which("node") is None, reason="website not built")
def test_website_internal_links():
    subprocess.run(["node", "scripts/check-links.mjs"], cwd=ROOT / "website", check=True)
