"""URL safety: syntax policy, tokenized-link detection and SSRF protection.

Two layers protect the checker from being turned against internal networks:

1. ``check_url_policy`` — static checks on the URL text (scheme, credentials, host form, port, tokens).
2. ``resolve_public`` / ``SafeNetworkBackend`` — every hostname is resolved and *every* address must be globally
   routable; the TCP connection is then made to the validated address itself (DNS pinning), so a second DNS answer
   cannot redirect the socket to a private address. Redirect targets go through both layers again.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {None, 80, 443, 8080, 8443}
BLOCKED_HOST_SUFFIXES = (
    ".local",
    ".localhost",
    ".internal",
    ".lan",
    ".home",
    ".corp",
    ".intranet",
    ".arpa",
)
# Query parameters that indicate signed, tokenized or credentialed links.
TOKEN_PARAMS = {
    "token",
    "auth",
    "authtoken",
    "access_token",
    "hdnts",
    "hdnea",
    "wmsauthsign",
    "sig",
    "signature",
    "expires",
    "exp",
    "e",
    "st",
    "md5",
    "hash",
    "key",
    "apikey",
    "api_key",
    "password",
    "pass",
    "user",
    "username",
    "u",
    "p",
    "session",
    "sessionid",
    "policy",
    "key-pair-id",
}
# Hosts that are known restreamers / redirect services and never acceptable as a source of truth.
DENY_HOST_PATTERNS = [
    re.compile(p)
    for p in (
        r"(^|\.)pishow\.tv$",
        r"(^|\.)tangotv\.in$",
        r"(^|\.)smartplaytv\.in$",
        r"(^|\.)mjh\.nz$",
        r"(^|\.)freem3u\.xyz$",
        r"(^|\.)aynaott\.com$",
        r"(^|\.)cinerama\.uz$",
        r"(^|\.)mcquack\.net$",
        r"(^|\.)onrender\.com$",
        r"(^|\.)ddns\.net$",
        r"(^|\.)duckdns\.org$",
        r"(^|\.)dynu\.net$",
        r"(^|\.)gleeze\.com$",
        r"(^|\.)no-ip\.(org|com|biz)$",
        r"(^|\.)githubusercontent\.com$",
        r"(^|\.)youtube\.com$",
        r"(^|\.)youtu\.be$",
        r"(^|\.)twitch\.tv$",
    )
]


class UnsafeURLError(ValueError):
    """Raised when a URL violates the safety policy."""


@dataclass(frozen=True)
class PolicyResult:
    ok: bool
    reason: str = ""


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def is_public_ip(ip: str) -> bool:
    """True only for globally routable unicast addresses."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return bool(
        addr.is_global
        and not addr.is_multicast
        and not addr.is_reserved
        and not addr.is_loopback
        and not addr.is_link_local
        and not addr.is_private
        and not addr.is_unspecified
    )


def check_url_policy(url: str, *, allow_ip_literal: bool = False, check_tokens: bool = True) -> PolicyResult:
    """Static policy check of a URL string. Never performs network access."""
    if len(url) > 2048:
        return PolicyResult(False, "URL too long")
    if any(ch.isspace() or ord(ch) < 32 for ch in url):
        return PolicyResult(False, "URL contains whitespace or control characters")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        return PolicyResult(False, f"malformed URL: {exc}")
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        return PolicyResult(False, f"scheme {parts.scheme!r} not allowed")
    if parts.username or parts.password or "@" in parts.netloc:
        return PolicyResult(False, "credentials in URL are not allowed")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        return PolicyResult(False, "missing host")
    if port not in ALLOWED_PORTS:
        return PolicyResult(False, f"port {port} not allowed")
    if _is_ip_literal(host):
        if not allow_ip_literal:
            return PolicyResult(False, "IP-address hosts are not accepted (provenance requires a domain)")
        if not is_public_ip(host.strip("[]")):
            return PolicyResult(False, "non-public IP address")
    else:
        if "." not in host:
            return PolicyResult(False, "single-label hostnames are not allowed")
        if host == "localhost" or host.endswith(BLOCKED_HOST_SUFFIXES):
            return PolicyResult(False, f"internal hostname {host!r}")
        if not re.fullmatch(r"[a-z0-9.-]+", host) or ".." in host:
            return PolicyResult(False, "hostname has invalid characters")
    for pat in DENY_HOST_PATTERNS:
        if pat.search(host):
            return PolicyResult(False, f"host {host!r} is a known restream/redirect service")
    for key, _ in parse_qsl(parts.query, keep_blank_values=True) if check_tokens else []:
        if key.lower() in TOKEN_PARAMS:
            return PolicyResult(False, f"tokenized or credentialed query parameter {key!r}")
    return PolicyResult(True)


def resolve_public(host: str, port: int) -> list[str]:
    """Resolve ``host`` and return its addresses, raising if *any* address is non-public."""
    host = host.strip("[]")
    if _is_ip_literal(host):
        if not is_public_ip(host):
            raise UnsafeURLError(f"non-public address {host}")
        return [host]
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise OSError(f"DNS resolution failed for {host}: {exc}") from exc
    addrs = sorted({info[4][0] for info in infos})
    if not addrs:
        raise OSError(f"no addresses for {host}")
    bad = [a for a in addrs if not is_public_ip(a)]
    if bad:
        raise UnsafeURLError(f"{host} resolves to non-public address(es): {', '.join(bad)}")
    return addrs


class SafeNetworkBackend:
    """httpcore async network backend that pins connections to validated public IPs.

    Connections to explicitly configured proxy endpoints are allowed (the proxy, not this process, then connects to
    the target, which has already been checked by ``resolve_public``).
    """

    def __init__(self, allowed_proxies: set[tuple[str, int]] | None = None, resolver=resolve_public):
        import httpcore

        self._inner = httpcore.AnyIOBackend()
        self._allowed_proxies = allowed_proxies or set()
        self._resolver = resolver

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        import anyio

        if (host, port) in self._allowed_proxies:
            target = host
        else:
            addrs = await anyio.to_thread.run_sync(self._resolver, host, port)
            target = addrs[0]
        return await self._inner.connect_tcp(
            target, port, timeout=timeout, local_address=local_address, socket_options=socket_options
        )

    async def connect_unix_socket(self, *args, **kwargs):  # pragma: no cover - never allowed
        raise UnsafeURLError("unix sockets are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)
