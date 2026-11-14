#!/usr/bin/env python3
"""Brand the platform folders that `flutter create` generates in CI (they are not committed).

    python tool/prepare_platforms.py android|macos|windows

Android: app name, internet permission, plain-http streams allowed (many broadcasters still use http).
macOS:   app name and the outgoing-network entitlement the sandbox needs to load playlists and streams.
Windows: executable name, window title and file details.
Fails loudly when an expected line is missing, so a template change in Flutter cannot ship an unbranded app.
"""

import plistlib
import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
NAME = "Nexonic IPTV"


def edit(path: Path, pairs: list[tuple[str, str]], regex: bool = False) -> None:
    text = path.read_text(encoding="utf-8")
    for old, new in pairs:
        found = re.search(old, text) if regex else old in text
        if not found:
            sys.exit(f"{path}: expected {old!r}")
        text = re.sub(old, new, text, count=1) if regex else text.replace(old, new)
    path.write_text(text, encoding="utf-8")


def android() -> None:
    m = APP / "android/app/src/main/AndroidManifest.xml"
    text = m.read_text(encoding="utf-8")
    if "android.permission.INTERNET" not in text:
        text = re.sub(
            r"(<manifest[^>]*>)",
            r'\1\n    <uses-permission android:name="android.permission.INTERNET"/>',
            text,
            count=1,
        )
    text = re.sub(r'android:label="[^"]*"', f'android:label="{NAME}"', text, count=1)
    if "usesCleartextTraffic" not in text:
        text = text.replace("<application", '<application\n        android:usesCleartextTraffic="true"', 1)
    m.write_text(text, encoding="utf-8")


def macos() -> None:
    edit(APP / "macos/Runner/Configs/AppInfo.xcconfig", [(r"PRODUCT_NAME = .*", f"PRODUCT_NAME = {NAME}")], regex=True)
    for name in ("DebugProfile.entitlements", "Release.entitlements"):
        p = APP / "macos/Runner" / name
        data = plistlib.loads(p.read_bytes())
        data["com.apple.security.network.client"] = True
        p.write_bytes(plistlib.dumps(data))


def windows() -> None:
    edit(
        APP / "windows/CMakeLists.txt", [(r'set\(BINARY_NAME "[^"]*"\)', 'set(BINARY_NAME "NexonicIPTV")')], regex=True
    )
    edit(APP / "windows/runner/main.cpp", [(r'window\.Create\(L"[^"]*"', f'window.Create(L"{NAME}"')], regex=True)
    rc = APP / "windows/runner/Runner.rc"
    text = rc.read_text(encoding="utf-8")
    text = text.replace('"nexonic_iptv.exe"', '"NexonicIPTV.exe"').replace('"nexonic_iptv"', f'"{NAME}"')
    rc.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    {"android": android, "macos": macos, "windows": windows}[sys.argv[1]]()
    print(f"prepared {sys.argv[1]}")
