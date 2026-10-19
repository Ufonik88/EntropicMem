"""Outbound HTTP endpoint validation shared by the optional network backends.

The CLI's ingest path already refuses non-http(s), internal hosts and DNS
rebinding; the embedding and formation sinks use the same policy here. Local
loopback endpoints stay usable for a model server on the same machine. A
private/LAN or plain-http non-loopback endpoint needs an explicit opt-in:

* ``ENTROPICMEM_ALLOW_PRIVATE_ENDPOINTS=1``
* ``ENTROPICMEM_ALLOW_INSECURE_ENDPOINTS=1``
"""

from __future__ import annotations

import ipaddress
import os
import socket
import urllib.parse
import urllib.request
from typing import Optional

__all__ = [
    "MAX_RESPONSE_BYTES",
    "open_validated",
    "read_capped",
    "validate_outbound_url",
]

#: Upper bound for a JSON response body (vectors, chat completions).
MAX_RESPONSE_BYTES = 8 * 1024 * 1024

_BLOCKED_HOSTS = {
    "metadata",
    "metadata.google.com",
    "metadata.google.internal",
    "instance-data",
}


def _env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _bad_address(ip: ipaddress._BaseAddress, *, allow_loopback: bool, allow_private: bool) -> bool:
    if ip.is_loopback:
        return not allow_loopback
    if ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
        return not allow_private
    return False


def validate_outbound_url(
    url: str,
    *,
    allow_loopback: bool = True,
    allow_private: Optional[bool] = None,
    allow_insecure_http: Optional[bool] = None,
) -> str:
    """Return the URL unchanged, or raise ``ValueError`` when it is refused.

    DNS is resolved and every answer is checked, so a public name cannot point
    at a private or link-local address. Redirects are re-checked by
    :func:`open_validated`.
    """
    if not url:
        raise ValueError("URL is required")
    if allow_private is None:
        allow_private = _env_flag("ENTROPICMEM_ALLOW_PRIVATE_ENDPOINTS")
    if allow_insecure_http is None:
        allow_insecure_http = _env_flag("ENTROPICMEM_ALLOW_INSECURE_ENDPOINTS")

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http/https URLs are allowed")
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise ValueError("URL hostname is required")
    if hostname in _BLOCKED_HOSTS or hostname.endswith(".local") or hostname.endswith(".internal"):
        raise ValueError("Internal hostname is not allowed")

    def _check_literal(ip: ipaddress._BaseAddress) -> bool:
        if _bad_address(ip, allow_loopback=allow_loopback, allow_private=allow_private):
            raise ValueError(f"Private/internal address {ip} is not allowed")
        return bool(ip.is_loopback)

    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None:
        loopback = _check_literal(literal)
    else:
        try:
            infos = socket.getaddrinfo(hostname, None)
        except socket.gaierror as exc:
            raise ValueError(f"DNS resolution failed for {hostname}") from exc
        if not infos:
            raise ValueError(f"DNS resolution returned no addresses for {hostname}")
        loopback = False
        for info in infos:
            address = info[4][0]
            try:
                ip = ipaddress.ip_address(address)
            except ValueError:
                continue
            loopback = _check_literal(ip) or loopback

    if parsed.scheme == "http" and not loopback and not allow_insecure_http:
        raise ValueError(
            "plain http to a non-loopback endpoint is refused "
            "(set ENTROPICMEM_ALLOW_INSECURE_ENDPOINTS=1 to opt in)"
        )
    return url


class _ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_outbound_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_validated(request: urllib.request.Request, *, timeout: float):
    """Open *request* after validating the URL and every redirect hop."""
    validate_outbound_url(request.full_url)
    opener = urllib.request.build_opener(_ValidatingRedirectHandler)
    return opener.open(request, timeout=timeout)


def read_capped(response, *, max_bytes: int = MAX_RESPONSE_BYTES) -> bytes:
    """Read at most *max_bytes*; a larger body is refused rather than buffered."""
    data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("response body is larger than the configured limit")
    return data
