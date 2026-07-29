# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import ipaddress
import socket
import time
from collections.abc import Callable, Iterable, Iterator
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpcore
import httpx


Resolver = Callable[..., list[tuple[Any, ...]]]


def is_public_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    return (
        address.is_global
        and not address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
        and not getattr(address, "is_site_local", False)
    )


def canonicalize_lm_studio_url(value: str) -> str:
    """Return a loopback-only LM Studio base URL in canonical form."""

    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(ord(character) <= 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("LM Studio URL must be a non-empty URL without whitespace")
    if "?" in value or "#" in value:
        raise ValueError("LM Studio URL must not contain a query or fragment")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"invalid LM Studio URL: {exc}") from exc
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"}:
        raise ValueError("LM Studio URL must use http or https")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("LM Studio URL must not contain user information")
    if parsed.netloc.endswith(":"):
        raise ValueError("LM Studio URL contains an invalid empty port")
    if host is None:
        raise ValueError("LM Studio URL must include a loopback host")
    if host.casefold() == "localhost":
        address = ipaddress.ip_address("127.0.0.1")
    else:
        if "%" in host:
            raise ValueError("LM Studio URL must not contain an IPv6 zone identifier")
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError(
                "LM Studio URL host must be numeric loopback or localhost"
            ) from exc
    if not address.is_loopback:
        raise ValueError("LM Studio URL must use a loopback address")

    canonical_host = f"[{address}]" if address.version == 6 else str(address)
    authority = canonical_host if port is None else f"{canonical_host}:{port}"
    path = parsed.path.rstrip("/")
    return urlunsplit((scheme, authority, path, "", ""))


def resolve_public_addresses(
    host: str,
    port: int,
    resolver: Resolver | None = None,
) -> tuple[str, ...]:
    active_resolver = resolver or socket.getaddrinfo
    if "%" in host:
        raise httpcore.ConnectError(
            f"scoped IPv6 addresses are not public targets: {host}"
        )
    try:
        numeric = ipaddress.ip_address(host)
    except ValueError:
        try:
            records = active_resolver(host, port, type=socket.SOCK_STREAM)
        except (OSError, ValueError) as exc:
            raise httpcore.ConnectError(
                f"public DNS resolution failed for {host}"
            ) from exc
        addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
        for record in records:
            try:
                raw_address = str(record[4][0])
                if "%" in raw_address:
                    raise ValueError("scoped IPv6 addresses are not public targets")
                address = ipaddress.ip_address(raw_address)
            except (IndexError, TypeError, ValueError) as exc:
                raise httpcore.ConnectError(
                    f"public DNS returned an invalid address for {host}"
                ) from exc
            if address not in addresses:
                addresses.append(address)
    else:
        addresses = [numeric]

    if not addresses:
        raise httpcore.ConnectError(f"public DNS returned no addresses for {host}")
    if any(not is_public_address(address) for address in addresses):
        raise httpcore.ConnectError(
            f"refusing non-global or mixed DNS addresses for {host}"
        )
    return tuple(str(address) for address in addresses)


class PublicNetworkBackend(httpcore.NetworkBackend):
    """Resolve once, validate every answer, then connect to numeric IPs only."""

    def __init__(
        self,
        *,
        resolver: Resolver | None = None,
        backend: httpcore.NetworkBackend | None = None,
    ) -> None:
        self._resolver = resolver or socket.getaddrinfo
        self._backend = backend or httpcore.SyncBackend()

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        addresses = resolve_public_addresses(host, port, self._resolver)
        last_error: httpcore.ConnectError | httpcore.ConnectTimeout | None = None
        deadline = None if timeout is None else time.monotonic() + max(timeout, 0)
        for address in addresses:
            remaining = (
                None
                if deadline is None
                else max(0.0, deadline - time.monotonic())
            )
            if remaining == 0:
                raise httpcore.ConnectTimeout(
                    f"public connection timeout exhausted for {host}"
                )
            try:
                return self._backend.connect_tcp(
                    address,
                    port,
                    timeout=remaining,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        raise httpcore.ConnectError("UNIX sockets are not valid public crawl targets")

    def sleep(self, seconds: float) -> None:
        self._backend.sleep(seconds)


_HTTPCORE_EXCEPTIONS: dict[type[Exception], type[httpx.HTTPError]] = {
    httpcore.ConnectTimeout: httpx.ConnectTimeout,
    httpcore.ReadTimeout: httpx.ReadTimeout,
    httpcore.WriteTimeout: httpx.WriteTimeout,
    httpcore.PoolTimeout: httpx.PoolTimeout,
    httpcore.ConnectError: httpx.ConnectError,
    httpcore.ReadError: httpx.ReadError,
    httpcore.WriteError: httpx.WriteError,
    httpcore.ProxyError: httpx.ProxyError,
    httpcore.LocalProtocolError: httpx.LocalProtocolError,
    httpcore.RemoteProtocolError: httpx.RemoteProtocolError,
    httpcore.ProtocolError: httpx.ProtocolError,
    httpcore.NetworkError: httpx.NetworkError,
    httpcore.TimeoutException: httpx.TimeoutException,
}


class _ResponseStream(httpx.SyncByteStream):
    def __init__(
        self,
        stream: Iterable[bytes],
        request: httpx.Request,
    ) -> None:
        self._stream = stream
        self._request = request

    def __iter__(self) -> Iterator[bytes]:
        try:
            yield from self._stream
        except tuple(_HTTPCORE_EXCEPTIONS) as exc:
            _raise_mapped_httpcore_error(exc, self._request)

    def close(self) -> None:
        close = getattr(self._stream, "close", None)
        if close is not None:
            try:
                close()
            except tuple(_HTTPCORE_EXCEPTIONS) as exc:
                _raise_mapped_httpcore_error(exc, self._request)


def _raise_mapped_httpcore_error(
    exc: Exception,
    request: httpx.Request,
) -> None:
    mapped: type[httpx.HTTPError] | None = None
    for source, target in _HTTPCORE_EXCEPTIONS.items():
        if isinstance(exc, source) and (
            mapped is None or issubclass(target, mapped)
        ):
            mapped = target
    assert mapped is not None
    raise mapped(str(exc), request=request) from exc


class PublicHTTPTransport(httpx.BaseTransport):
    """An HTTP transport with no proxy path and a DNS-pinning backend."""

    def __init__(
        self,
        *,
        network_backend: httpcore.NetworkBackend | None = None,
    ) -> None:
        self._pool = httpcore.ConnectionPool(
            ssl_context=httpcore.default_ssl_context(),
            proxy=None,
            http1=True,
            http2=False,
            retries=0,
            network_backend=network_backend or PublicNetworkBackend(),
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if not isinstance(request.stream, httpx.SyncByteStream):
            raise TypeError("public crawler requires a synchronous request stream")
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        try:
            response = self._pool.handle_request(core_request)
        except tuple(_HTTPCORE_EXCEPTIONS) as exc:
            _raise_mapped_httpcore_error(exc, request)
        return httpx.Response(
            status_code=response.status,
            headers=response.headers,
            stream=_ResponseStream(response.stream, request),
            extensions=response.extensions,
        )

    def close(self) -> None:
        self._pool.close()
