"""CLI ``ingest``: every redirect hop is re-validated (SSRF via redirect).

``validate_url`` checked only the first URL. ``urlopen`` then followed any
redirect, so a public page answering ``302 Location: http://169.254.169.254/``
(cloud metadata) or ``http://127.0.0.1:…`` reached the internal address anyway.
Reported by the Hermes catalog maintainer in the 2.8.0 catalog review.
"""

from __future__ import annotations

import ast
import http.server
import sys
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import entropicmem  # noqa: E402


class _Redirector(http.server.BaseHTTPRequestHandler):
    routes: dict = {}

    def do_GET(self):  # noqa: N802 - stdlib API
        target = self.routes.get(self.path)
        if target is None:
            body = b"<html><body>final page from Acme</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(302)
        self.send_header("Location", target)
        self.end_headers()

    def log_message(self, *args):  # keep test output clean
        pass


@pytest.fixture
def server(monkeypatch):
    """A local server, reachable only because the *first hop* validator is
    relaxed for exactly this host:port. Every other URL goes through the real
    validator, which is what the redirect handler must call."""
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Redirector)
    port = httpd.server_address[1]
    base = f"http://127.0.0.1:{port}"
    real = entropicmem.validate_url

    def validate(url):
        if url.startswith(base + "/"):
            return url
        return real(url)

    monkeypatch.setattr(entropicmem, "validate_url", validate)
    # The sandbox/CI may route HTTP through a proxy; never for this loopback test.
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    _Redirector.routes = {}
    try:
        yield base
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_redirect_to_cloud_metadata_is_refused(server):
    _Redirector.routes = {"/start": "http://169.254.169.254/latest/meta-data/"}
    with pytest.raises(ValueError, match="(?i)internal|private|blocked|not allowed"):
        entropicmem.safe_fetch(server + "/start")


def test_redirect_to_loopback_elsewhere_is_refused(server):
    _Redirector.routes = {"/start": "http://127.0.0.1:1/admin"}
    with pytest.raises(ValueError):
        entropicmem.safe_fetch(server + "/start")


def test_redirect_to_a_non_http_scheme_is_refused(server):
    _Redirector.routes = {"/start": "file:///etc/passwd"}
    with pytest.raises((ValueError, OSError)):
        entropicmem.safe_fetch(server + "/start")


def test_an_allowed_redirect_is_followed(server):
    _Redirector.routes = {"/start": server + "/final"}
    assert "final page from Acme" in entropicmem.safe_fetch(server + "/start")


def test_redirect_chains_are_bounded(server):
    _Redirector.routes = {f"/r{i}": f"{server}/r{i + 1}" for i in range(20)}
    with pytest.raises(OSError):
        entropicmem.safe_fetch(server + "/r0")


def test_the_cli_never_calls_urlopen_directly():
    """Drift guard: any new fetch must go through safe_fetch."""
    tree = ast.parse((SCRIPTS / "entropicmem.py").read_text(encoding="utf-8"))
    direct = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "urlopen"
    ]
    assert not direct, f"urllib urlopen used directly at lines {direct}; use safe_fetch"
