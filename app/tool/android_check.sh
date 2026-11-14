#!/usr/bin/env bash
# Runs on the CI emulator: the self-test build must load the catalogue and play a channel, then the release build
# must install over it and start.
set -euo pipefail
selftest="$1"
release="$2"
pkg=com.nexonic.nexonic_iptv
adb install -r "$selftest"
adb logcat -c
adb shell am start -W -n "$pkg/.MainActivity"
result=""
for _ in $(seq 1 120); do
  result=$(adb logcat -d -s flutter:I | grep -o 'NEXONIC_SELF_TEST .*' | tail -1 || true)
  [ -n "$result" ] && break
  sleep 5
done
echo "$result"
[ -n "$result" ] || { echo "::error::no self-test result"; exit 1; }
echo "${result#NEXONIC_SELF_TEST }" | python3 -c "import json,sys; sys.exit(0 if json.load(sys.stdin)['ok'] else 1)"
adb install -r "$release"
adb shell am start -W -n "$pkg/.MainActivity"
sleep 20
adb shell pidof "$pkg" || { echo "::error::the app closed by itself"; adb logcat -d | tail -80; exit 1; }
echo "release build started"
