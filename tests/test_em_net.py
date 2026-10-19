"""Outbound endpoint policy for the optional embedding/formation backends."""

from __future__ import annotations

import pytest

from em.net import read_capped, validate_outbound_url


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
