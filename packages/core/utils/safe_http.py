"""SSRF-safe HTTP fetching built on the standard library.

The public policy platform lets callers point ingestion at an arbitrary URL
("crawl this document"). Without egress controls that is a Server-Side Request
Forgery primitive: on Azure Container Apps a caller could target the Instance
Metadata Service (``169.254.169.254``) to steal managed-identity tokens, or
reach loopback / RFC1918 internal services.

This module fetches URLs while enforcing, on every request and every redirect
hop:

* scheme is ``http`` or ``https`` only;
* the hostname's resolved A/AAAA addresses are all publicly routable
  (no loopback, link-local, private, reserved, multicast or unspecified);
* the socket connects to the exact IP that was validated (DNS pinning), so a
  rebinding attacker cannot swap in an internal address between the check and
  the connect;
* redirects are followed manually with re-validation, up to a small cap;
* the response body is bounded, and connect/read have a timeout.

The implementation is intentionally stdlib-only (``urllib`` + ``socket`` +
``ipaddress``) to avoid adding an HTTP dependency the project does not already
carry.
"""

from __future__ import annotations

import http.client
import ipaddress
import logging
import socket
import ssl
from dataclasses import dataclass
from typing import Callable
from urllib.error import HTTPError
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})

# Matches the ingestion pipeline's assumption that a single policy document is a
# reasonably sized file, not an unbounded stream. 25 MiB.
MAX_RESPONSE_BYTES: int = 25 * 1024 * 1024

# Split the 60s used previously into an explicit connect/read budget.
DEFAULT_TIMEOUT_SECONDS: float = 30.0

# A malicious server can 200 then redirect to the metadata IP (or vice versa);
# each hop is re-validated, but we still cap the chain length.
MAX_REDIRECTS: int = 3

_REDIRECT_STATUSES: frozenset[int] = frozenset({301, 302, 303, 307, 308})

# Resolver type: (host, port) -> list of raw address strings. Injectable so
# tests can exercise the validation logic without real DNS.
Resolver = Callable[[str, int], list[str]]

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class SsrfError(ValueError):
    """A URL was rejected because it targets a non-public / disallowed address.

    Subclasses ``ValueError`` so callers already catching ``ValueError`` around
    URL handling continue to work.
    """


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Result of a successful safe fetch."""

    content: bytes
    content_type: str
    final_url: str


def _default_resolver(host: str, port: int) -> list[str]:
    """Resolve a hostname to its A/AAAA addresses via ``getaddrinfo``.

    Raises ``socket.gaierror`` on resolution failure so the caller can fail
    closed.
    """

    infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    addresses: list[str] = []
    for info in infos:
        sockaddr = info[4]
        # IPv4 sockaddr is (ip, port); IPv6 is (ip, port, flowinfo, scopeid).
        addresses.append(str(sockaddr[0]))
    return addresses


def _normalize_ip(raw: str) -> IPAddress:
    """Parse an address, unwrapping IPv4-mapped/compat IPv6 forms.

    ``::ffff:169.254.169.254`` and similar must be judged by the embedded IPv4
    address, otherwise an attacker bypasses the v4 range checks.
    """

    addr = ipaddress.ip_address(raw)
    if isinstance(addr, ipaddress.IPv6Address):
        mapped = addr.ipv4_mapped
        if mapped is not None:
            return mapped
        # sixtofour / teredo embed a routable-looking v4 address; if present,
        # judge on that to be safe.
        if addr.sixtofour is not None:
            return addr.sixtofour
    return addr


def _assert_ip_is_public(addr: IPAddress, *, host: str) -> None:
    """Reject any non-publicly-routable address. Fails closed."""

    blocked_reason: str | None = None
    if addr.is_loopback:
        blocked_reason = "loopback"
    elif addr.is_link_local:
        # 169.254.0.0/16 — this is the Azure IMDS range.
        blocked_reason = "link_local"
    elif addr.is_private:
        blocked_reason = "private"
    elif addr.is_reserved:
        blocked_reason = "reserved"
    elif addr.is_multicast:
        blocked_reason = "multicast"
    elif addr.is_unspecified:
        blocked_reason = "unspecified"

    if blocked_reason is not None:
        logger.warning(
            "safe_http.blocked_address",
            extra={"host": host, "resolved_ip": str(addr), "reason": blocked_reason},
        )
        raise SsrfError(
            f"Refusing to connect to non-public address {addr} ({blocked_reason}) for host {host!r}"
        )


def _validate_and_resolve(url: str, resolver: Resolver) -> tuple[str, int, str]:
    """Validate scheme/host and resolve to a single vetted IP to pin.

    Returns ``(scheme, port, pinned_ip)``. Raises :class:`SsrfError` if the URL
    is disallowed, or ``socket.gaierror`` if DNS resolution fails.
    """

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        logger.warning("safe_http.blocked_scheme", extra={"url": url, "scheme": scheme})
        raise SsrfError(
            f"Unsupported URL scheme {scheme!r}; only http/https are allowed"
        )

    host = parsed.hostname
    if not host:
        raise SsrfError("URL has no host component")

    port = parsed.port or (443 if scheme == "https" else 80)

    # A literal IP host never touches DNS; validate it directly.
    try:
        literal = _normalize_ip(host)
    except ValueError:
        literal = None
    if literal is not None:
        _assert_ip_is_public(literal, host=host)
        return scheme, port, str(literal)

    raw_addresses = resolver(host, port)
    if not raw_addresses:
        logger.warning("safe_http.no_addresses", extra={"host": host})
        raise SsrfError(f"Host {host!r} did not resolve to any address")

    # Every resolved address must be public; then pin to the first one so the
    # socket connects to exactly what we validated (no re-resolution race).
    pinned: str | None = None
    for raw in raw_addresses:
        addr = _normalize_ip(raw)
        _assert_ip_is_public(addr, host=host)
        if pinned is None:
            pinned = raw
    assert pinned is not None  # non-empty list guaranteed above
    return scheme, port, pinned


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """HTTP connection that dials a pre-validated IP but keeps the SNI/Host name."""

    def __init__(self, host: str, pinned_ip: str, timeout: float) -> None:
        super().__init__(host, timeout=timeout)
        self._pinned_ip = pinned_ip

    def connect(self) -> None:  # pragma: no cover - thin socket glue
        self.sock = socket.create_connection(
            (self._pinned_ip, self.port), timeout=self.timeout
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS variant: dial the pinned IP, keep the original hostname for TLS/SNI."""

    def __init__(self, host: str, pinned_ip: str, timeout: float) -> None:
        # Default secure context: verifies the cert chain and hostname.
        self._ssl_context = ssl.create_default_context()
        super().__init__(host, timeout=timeout, context=self._ssl_context)
        self._pinned_ip = pinned_ip

    def connect(self) -> None:  # pragma: no cover - thin socket glue
        sock = socket.create_connection(
            (self._pinned_ip, self.port), timeout=self.timeout
        )
        self.sock = self._ssl_context.wrap_socket(sock, server_hostname=self.host)


def _read_capped(response: http.client.HTTPResponse, limit: int) -> bytes:
    """Read a response body, aborting past ``limit`` bytes."""

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise SsrfError(f"Response body exceeded the {limit}-byte limit")
        chunks.append(chunk)
    return b"".join(chunks)


def safe_fetch(
    url: str,
    *,
    user_agent: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = MAX_RESPONSE_BYTES,
    max_redirects: int = MAX_REDIRECTS,
    resolver: Resolver | None = None,
) -> FetchResult:
    """Fetch ``url`` with SSRF protections, following redirects safely.

    Every URL (initial and each redirect target) is validated: scheme must be
    http/https and all resolved IPs must be publicly routable. The socket is
    pinned to the vetted IP to defeat DNS rebinding. The body is size-capped.

    Args:
        url: The URL to fetch.
        user_agent: ``User-Agent`` header value to send.
        timeout: Connect/read timeout in seconds.
        max_bytes: Maximum response body size before aborting.
        max_redirects: Maximum number of redirect hops to follow.
        resolver: Optional DNS resolver override (mainly for tests).

    Returns:
        A :class:`FetchResult` with the body, content type and final URL.

    Raises:
        SsrfError: The URL (or a redirect target) is disallowed, or the body is
            too large.
        socket.gaierror: DNS resolution failed (fail closed).
        URLError / HTTPError / OSError: Transport-level failures.
    """

    resolve = resolver or _default_resolver
    current_url = url

    for _ in range(max_redirects + 1):
        scheme, port, pinned_ip = _validate_and_resolve(current_url, resolve)
        parsed = urlparse(current_url)
        host = parsed.hostname
        assert host is not None  # guaranteed by _validate_and_resolve

        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        conn: http.client.HTTPConnection
        if scheme == "https":
            conn = _PinnedHTTPSConnection(host, pinned_ip, timeout)
        else:
            conn = _PinnedHTTPConnection(host, pinned_ip, timeout)

        try:
            host_header = host if port in (80, 443) else f"{host}:{port}"
            conn.request(
                "GET",
                path,
                headers={
                    "Host": host_header,
                    "User-Agent": user_agent,
                    "Accept": "*/*",
                },
            )
            response = conn.getresponse()
            status_code = response.status

            if status_code in _REDIRECT_STATUSES:
                location = response.headers.get("Location")
                response.read()  # drain before reuse/close
                if not location:
                    raise SsrfError(
                        f"Redirect status {status_code} without a Location header"
                    )
                # Resolve relative redirects against the current URL, then loop
                # to re-validate the new target on the next iteration.
                current_url = _join_redirect(current_url, location)
                continue

            if status_code >= 400:
                raise HTTPError(
                    current_url,
                    status_code,
                    f"Server returned HTTP {status_code}",
                    response.headers,
                    None,
                )

            body = _read_capped(response, max_bytes)
            content_type = (
                response.headers.get("Content-Type", "application/octet-stream")
                .split(";")[0]
                .strip()
            )
            return FetchResult(
                content=body, content_type=content_type, final_url=current_url
            )
        finally:
            conn.close()

    logger.warning("safe_http.too_many_redirects", extra={"url": url})
    raise SsrfError(f"Exceeded the maximum of {max_redirects} redirects for {url!r}")


def _join_redirect(base_url: str, location: str) -> str:
    """Resolve a possibly-relative ``Location`` against the current URL."""

    from urllib.parse import urljoin

    return urljoin(base_url, location)


__all__ = [
    "FetchResult",
    "MAX_RESPONSE_BYTES",
    "Resolver",
    "SsrfError",
    "safe_fetch",
]
