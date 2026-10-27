# Stream verification

`scripts/verify.py` checks every approved channel. An HTTP 200 is never treated as proof that a stream works.

## Levels
| Level | Check | Failing outcome |
|---:|---|---|
| 1 | URL syntax and policy: http(s) only, no credentials, allowed ports (80/443/8080/8443), no IP-literal or internal hosts, no tokens, no known restream hosts | `INVALID_STREAM` |
| 2 | DNS resolution; **every** resolved address must be globally routable | `UNAVAILABLE` / `INVALID_STREAM` (unsafe) |
| 3 | Bounded GET of the manifest (≤512 KiB), manual redirects (≤3), each hop re-validated (levels 1–2) | see table below |
| 4 | HLS parse: master → lowest-bandwidth variant → media playlist with `EXT-X-TARGETDURATION` and ≥1 segment; DASH MPD sanity; DRM detection | `INVALID_STREAM`, `UNSUPPORTED` |
| 5 | `Range` read of ≤188 KiB of the newest segment; must look like MPEG-TS, fMP4, ADTS or ID3. Optional FFprobe probe (`--ffprobe`) of the media playlist | `INVALID_STREAM` |
| 6 | Record status, level, HTTP code, latency to first manifest byte, error, UTC timestamp, checker location | — |

## HTTP outcomes
| Response | Outcome |
|---|---|
| 401, 407 | `AUTH_REQUIRED` (never retried, never "fixed") |
| 403 for a channel recorded as region-limited, or with geo hints in the body | `GEO_RESTRICTED` |
| 403 otherwise | `UNKNOWN` (could be regional limits or access control — not counted as broken) |
| 451 | `GEO_RESTRICTED` |
| 429 | `RATE_LIMITED` after bounded retries honouring `Retry-After` (≤30 s) |
| 404, 410, 5xx, connection errors | `UNAVAILABLE` |
| no response within the timeout (12 s) | `TIMEOUT` |
| DRM (SAMPLE-AES, FairPlay, Widevine, PlayReady, DASH ContentProtection) | `UNSUPPORTED` — we never attempt to decrypt |

`NOT_TESTED` is used when no check has run. Nothing is ever recorded as `VERIFIED_WORKING` without passing level 4.

## Politeness and resource limits
- Global concurrency 12 (`--concurrency`, max 16); one channel at a time per stream host, one in-flight request per
  host and ≥1 s between requests to the same host. Waiting for a busy host does not count against the 60 s
  per-channel limit.
- Per channel at most 5 requests and 1 MiB. Segment reads use `Range`. No full broadcasts are downloaded or stored.
- Retries: at most 1 per request, exponential backoff with jitter, only for timeouts, connection errors, 429 and 5xx.
- Identifying user agent: `NexonicIPTV-Verifier/1.0 (+repo URL)`. No cookies, credentials or spoofed headers.
- Daily schedule (one run per day) to respect broadcasters and GitHub Actions quotas.

## SSRF protection
The checker refuses private, loopback, link-local, CGNAT, multicast, reserved and unspecified addresses (IPv4 and
IPv6, including IPv4-mapped IPv6). The custom `SafeNetworkBackend` resolves the host itself and connects to the
validated address (TLS still verifies the certificate for the hostname), so DNS rebinding between check and connect is
not possible. Redirect targets and URLs inside manifests are validated the same way. Manifest content is parsed as text
only, never executed. FFprobe runs with `-protocol_whitelist https,http,tls,tcp,hls,crypto` and only on URLs that
passed all checks; it performs its own DNS lookups, which is a documented residual risk mitigated by running in an
isolated GitHub-hosted runner with no secrets.

## Location caveat
GitHub-hosted runners are mostly in the United States. A `GEO_RESTRICTED` or `UNKNOWN` (403) result for a channel
intended for another country is expected and is excluded from the Health Score. A second location can re-check those channels; see
[REGIONAL_CHECKS.md](REGIONAL_CHECKS.md). Its results are kept apart from `state/history.json` and only add `works_in`
to a channel that stays `restricted`.

## Nexonic Health Score
Computed by `nexonic/health.py` from results in the last 14 days, excluding neutral outcomes
(`GEO_RESTRICTED`, `RATE_LIMITED`, `UNKNOWN`, `UNSUPPORTED`, `NOT_TESTED`):

```
score = 100 × ( 0.45 × success rate of the last 10 scorable checks
              + 0.20 × min(consecutive successes, 5) / 5
              + 0.15 × latency factor   (median ≤500 ms → 1, ≥3000 ms → 0, linear between)
              + 0.10 × share of successes where media bytes were read
              + 0.10 × freshness        (last success ≤24 h → 1, ≤72 h → 0.5, else 0) )
```
Grades: ≥85 Excellent, ≥70 Good, ≥50 Fair, else Poor. With fewer than 3 scorable checks on 2 distinct UTC days the
score is `NOT ENOUGH DATA`. Display states: verified recently (working, ≤48 h), previously working, currently failing
(3+ consecutive failures), geo-restricted, not yet tested.

## Playlist policies
- `verified.m3u`: latest result `VERIFIED_WORKING` within 48 h of the latest run. Not generated when empty.
- All other playlists include approved channels except **stale** ones (3+ consecutive failures and no success for 7 days).
- Automated (auto-admitted) records are published only after at least one `VERIFIED_WORKING` result.

## Mocked vs live
`tests/test_checker.py` uses `httpx.MockTransport` and a stub resolver — no real requests. Live results come only from
`scripts/verify.py`, and are written to `state/history.json` and `reports/verification.*` with real UTC timestamps.
