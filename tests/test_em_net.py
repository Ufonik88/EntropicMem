"""Outbound endpoint policy for the optional embedding/formation backends."""

from __future__ import annotations

import socket
import urllib.request

import pytest

from em.net import (
    _ValidatingRedirectHandler,
    open_validated,
    read_capped,
    validate_outbound_url,
)


def test_loopback_http_stays_usable():
    assert validate_outbound_url("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434/v1"
    assert validate_outbound_url("http://localhost:1234/v1") == "http://localhost:1234/v1"


def test_non_http_schemes_are_refused():
    for url in ("file:///etc/passwd", "ftp://example.com/x", "gopher://example.com/"):
        with pytest.raises(ValueError):
            validate_outbound_url(url)


def test_link_local_and_metadata_addresses_are_refused():
    for url in (
        "http://169.254.169.254/latest/meta-data/",
        "https://metadata.google.internal/computeMetadata/v1/",
        "http://10.0.0.5/v1",
    ):
        with pytest.raises(ValueError):
            validate_outbound_url(url)


def test_private_and_plain_http_need_an_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("ENTROPICMEM_ALLOW_PRIVATE_ENDPOINTS", "1")
    monkeypatch.setenv("ENTROPICMEM_ALLOW_INSECURE_ENDPOINTS", "1")
    assert validate_outbound_url("http://10.0.0.5/v1") == "http://10.0.0.5/v1"


def test_oversized_response_is_refused():
    class _Response:
        def read(self, _n):
            return b"x" * 32

    with pytest.raises(ValueError, match="larger"):
        read_capped(_Response(), max_bytes=16)


def test_public_ip_literal_passes_validation():
    assert validate_outbound_url("https://8.8.8.8/v1") == "https://8.8.8.8/v1"


def test_empty_url_is_refused():
    with pytest.raises(ValueError, match="URL is required"):
        validate_outbound_url("")


def test_url_without_hostname_is_refused():
    with pytest.raises(ValueError, match="hostname is required"):
        validate_outbound_url("http://:80/x")


def test_dns_resolution_failure_is_refused(monkeypatch):
    def boom(*args, **kwargs):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    with pytest.raises(ValueError, match="DNS resolution failed"):
        validate_outbound_url("https://does-not-exist.example.invalid/v1")


def test_dns_returning_no_addresses_is_refused(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [])
    with pytest.raises(ValueError, match="no addresses"):
        validate_outbound_url("https://no-address.example.invalid/v1")


def test_non_ip_address_from_dns_is_skipped(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [("host", 0, 0, "", ("not.an.ip", 0))],
    )
    assert (
        validate_outbound_url("https://weird.example.invalid/v1")
        == "https://weird.example.invalid/v1"
    )


def test_plain_http_to_public_endpoint_is_refused_without_opt_in():
    with pytest.raises(ValueError, match="plain http"):
        validate_outbound_url("http://8.8.8.8/v1")


def test_redirect_to_blocked_host_is_refused():
    handler = _ValidatingRedirectHandler()
    req = urllib.request.Request("http://127.0.0.1:9/x")
    with pytest.raises(ValueError, match="Private/internal address"):
        handler.redirect_request(req, None, 302, "Found", {}, "http://169.254.169.254/y")


def test_redirect_to_allowed_host_proceeds():
    handler = _ValidatingRedirectHandler()
    req = urllib.request.Request("http://127.0.0.1:9/x")
    out = handler.redirect_request(req, None, 303, "See Other", {}, "http://127.0.0.1:9/y")
    assert out.full_url == "http://127.0.0.1:9/y"


def test_open_validated_returns_the_response_body(monkeypatch):
    class _FakeResponse:
        def read(self, _n=-1):
            return b'{"ok": true}'

    class _FakeOpener:
        def open(self, request, timeout=None):
            assert isinstance(request, urllib.request.Request)
            assert timeout == 2.5
            return _FakeResponse()

    monkeypatch.setattr("urllib.request.build_opener", lambda *handlers: _FakeOpener())
    resp = open_validated(urllib.request.Request("http://127.0.0.1:9/x"), timeout=2.5)
    assert resp.read() == b'{"ok": true}'


def test_read_capped_returns_body_under_the_limit():
    class _Response:
        def read(self, _n):
            return b"hi"

    assert read_capped(_Response(), max_bytes=16) == b"hi"
