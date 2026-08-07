from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

import pytest

from packages.core.utils import safe_http
from packages.core.utils.safe_http import (
    FetchResult,
    MAX_RESPONSE_BYTES,
    SsrfError,
    safe_fetch,
)

_UA = "test-agent/1.0"


def _resolver_returning(*addresses: str) -> safe_http.Resolver:
    def _resolve(host: str, port: int) -> list[str]:
        return list(addresses)

    return _resolve


class _FakeResponse:
    """Minimal stand-in for http.client.HTTPResponse."""

    def __init__(
        self,
        status: int,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.headers = headers or {}
        self._body = body
        self._read = False

    def read(self, amt: int | None = None) -> bytes:
        if self._read:
            return b""
        self._read = True
        return self._body


class _FakeConnection:
    """Records the request and returns a queued response; ignores real sockets."""

    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.requested: tuple[str, str, dict[str, str]] | None = None
        self.closed = False

    def request(self, method: str, path: str, headers: dict[str, str]) -> None:
        self.requested = (method, path, headers)

    def getresponse(self) -> _FakeResponse:
        return self._response

    def close(self) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# Scheme validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://host/x", "gopher://host"])
def test_non_http_scheme_rejected(url: str) -> None:
    with pytest.raises(SsrfError):
        safe_fetch(url, user_agent=_UA, resolver=_resolver_returning("1.2.3.4"))


# ---------------------------------------------------------------------------
# (a) Azure IMDS / link-local rejection
# ---------------------------------------------------------------------------


def test_azure_imds_ip_rejected_via_dns() -> None:
    resolver = _resolver_returning("169.254.169.254")
    with pytest.raises(SsrfError) as exc:
        safe_fetch(
            "http://metadata.example.com/token", user_agent=_UA, resolver=resolver
        )
    assert "link_local" in str(exc.value) or "169.254.169.254" in str(exc.value)


def test_azure_imds_literal_ip_rejected() -> None:
    with pytest.raises(SsrfError):
        safe_fetch(
            "http://169.254.169.254/metadata/identity/oauth2/token",
            user_agent=_UA,
            resolver=_resolver_returning("169.254.169.254"),
        )


def test_imds_via_ipv4_mapped_ipv6_rejected() -> None:
    # ::ffff:169.254.169.254 must be judged by its embedded IPv4 address.
    resolver = _resolver_returning("::ffff:169.254.169.254")
    with pytest.raises(SsrfError):
        safe_fetch("http://sneaky.example.com/", user_agent=_UA, resolver=resolver)


# ---------------------------------------------------------------------------
# (b) private / loopback rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # loopback
        "::1",  # loopback v6
        "10.0.0.5",  # RFC1918
        "172.16.0.1",  # RFC1918
        "192.168.1.1",  # RFC1918
        "0.0.0.0",  # unspecified/reserved
        "224.0.0.1",  # multicast
    ],
)
def test_private_and_loopback_ips_rejected(ip: str) -> None:
    with pytest.raises(SsrfError):
        safe_fetch(
            "http://internal.example.com/",
            user_agent=_UA,
            resolver=_resolver_returning(ip),
        )


def test_mixed_resolution_with_one_bad_ip_rejected() -> None:
    # If any resolved address is internal, fail closed.
    resolver = _resolver_returning("93.184.216.34", "127.0.0.1")
    with pytest.raises(SsrfError):
        safe_fetch("http://example.com/", user_agent=_UA, resolver=resolver)


# ---------------------------------------------------------------------------
# Fail-closed on DNS failure and empty resolution
# ---------------------------------------------------------------------------


def test_dns_failure_propagates_and_fails_closed() -> None:
    def _boom(host: str, port: int) -> list[str]:
        raise socket.gaierror("name resolution failed")

    with pytest.raises(socket.gaierror):
        safe_fetch("http://nope.example.com/", user_agent=_UA, resolver=_boom)


def test_empty_resolution_rejected() -> None:
    with pytest.raises(SsrfError):
        safe_fetch(
            "http://empty.example.com/", user_agent=_UA, resolver=_resolver_returning()
        )


# ---------------------------------------------------------------------------
# (c) a normal public URL passes validation and returns content
# ---------------------------------------------------------------------------


def test_public_url_succeeds() -> None:
    resolver = _resolver_returning("93.184.216.34")  # public
    response = _FakeResponse(
        200, body=b"hello world", headers={"Content-Type": "text/html; charset=utf-8"}
    )
    conn = _FakeConnection(response)
    with patch.object(safe_http, "_PinnedHTTPConnection", return_value=conn):
        result = safe_fetch(
            "http://example.com/page", user_agent=_UA, resolver=resolver
        )

    assert isinstance(result, FetchResult)
    assert result.content == b"hello world"
    assert result.content_type == "text/html"
    assert conn.requested is not None
    method, path, headers = conn.requested
    assert method == "GET"
    assert path == "/page"
    assert headers["Host"] == "example.com"
    assert headers["User-Agent"] == _UA
    assert conn.closed is True


def test_public_https_url_uses_https_connection() -> None:
    resolver = _resolver_returning("93.184.216.34")
    response = _FakeResponse(
        200, body=b"secure", headers={"Content-Type": "application/pdf"}
    )
    conn = _FakeConnection(response)
    with patch.object(
        safe_http, "_PinnedHTTPSConnection", return_value=conn
    ) as https_cls:
        result = safe_fetch(
            "https://example.com/doc.pdf", user_agent=_UA, resolver=resolver
        )

    https_cls.assert_called_once()
    assert result.content == b"secure"
    assert result.content_type == "application/pdf"


# ---------------------------------------------------------------------------
# (d) redirect to a blocked IP is rejected; redirect to public is followed
# ---------------------------------------------------------------------------


def test_redirect_to_blocked_ip_rejected() -> None:
    # First hop is public and returns a 302 to an internal host; the second hop
    # must be re-validated and rejected.
    def resolver(host: str, port: int) -> list[str]:
        if host == "public.example.com":
            return ["93.184.216.34"]
        if host == "internal.example.com":
            return ["169.254.169.254"]
        raise socket.gaierror("unknown host")

    redirect_response = _FakeResponse(
        302, headers={"Location": "http://internal.example.com/metadata"}
    )
    conn = _FakeConnection(redirect_response)
    with patch.object(safe_http, "_PinnedHTTPConnection", return_value=conn):
        with pytest.raises(SsrfError):
            safe_fetch(
                "http://public.example.com/start", user_agent=_UA, resolver=resolver
            )


def test_redirect_to_public_is_followed() -> None:
    def resolver(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]  # both hops public

    redirect_response = _FakeResponse(
        301, headers={"Location": "http://example.org/final"}
    )
    final_response = _FakeResponse(
        200, body=b"final body", headers={"Content-Type": "text/plain"}
    )
    conn_seq = [_FakeConnection(redirect_response), _FakeConnection(final_response)]
    factory = MagicMock(side_effect=conn_seq)

    with patch.object(safe_http, "_PinnedHTTPConnection", factory):
        result = safe_fetch(
            "http://example.com/start", user_agent=_UA, resolver=resolver
        )

    assert result.content == b"final body"
    assert result.final_url == "http://example.org/final"


def test_too_many_redirects_rejected() -> None:
    resolver = _resolver_returning("93.184.216.34")
    # Always redirect -> exhausts the hop budget.
    always_redirect = _FakeResponse(
        302, headers={"Location": "http://example.com/loop"}
    )
    factory = MagicMock(side_effect=lambda *a, **k: _FakeConnection(always_redirect))

    with patch.object(safe_http, "_PinnedHTTPConnection", factory):
        with pytest.raises(SsrfError):
            safe_fetch(
                "http://example.com/start",
                user_agent=_UA,
                resolver=resolver,
                max_redirects=2,
            )


# ---------------------------------------------------------------------------
# Response size cap
# ---------------------------------------------------------------------------


def test_oversized_response_rejected() -> None:
    resolver = _resolver_returning("93.184.216.34")

    class _BigResponse:
        status = 200
        headers = {"Content-Type": "application/octet-stream"}

        def read(self, amt: int | None = None) -> bytes:
            # Return a full chunk every call; safe_fetch must abort past the cap.
            return b"x" * (64 * 1024)

    conn = _FakeConnection(_BigResponse())  # type: ignore[arg-type]
    with patch.object(safe_http, "_PinnedHTTPConnection", return_value=conn):
        with pytest.raises(SsrfError):
            safe_fetch(
                "http://example.com/big",
                user_agent=_UA,
                resolver=resolver,
                max_bytes=128 * 1024,
            )


def test_default_max_bytes_is_25_mib() -> None:
    assert MAX_RESPONSE_BYTES == 25 * 1024 * 1024
