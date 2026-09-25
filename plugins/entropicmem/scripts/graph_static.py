"""Hardened stdlib server behind ``entropicmem graph serve`` (EM-114).

The CLI serves an exported ``graph.html`` (which can embed note bodies) and
``graph.json`` without the optional FastAPI stack. It follows the same
exposure rules as the FastAPI graph server (``scripts/graph_server/server.py``):

* a non-loopback bind is refused unless ``ENTROPICMEM_GRAPH_EXPOSE=1``;
* the ``Host`` header must name a loopback host (or, when exposed, the bind
  host / an ``ENTROPICMEM_GRAPH_ALLOWED_HOSTS`` entry) on the port actually
  bound: DNS-rebinding guard;
* every response carries the same Content-Security-Policy, ``nosniff`` and
  ``no-referrer`` headers;
* only ``/``, ``/graph.html`` and ``/graph.json`` are served, never a
  directory listing or any other file in the export directory.

This static server has no token: exposing it serves the export to anyone
who can reach the address. For token-gated access use the FastAPI server.

The CSP and Host parsing are duplicated from the FastAPI server on purpose
(the plugin cannot import the repo-root server); tests/test_graph_static.py
fails if the two drift apart.
"""
from __future__ import annotations

import http.server
import os
from pathlib import Path
from typing import Optional, Set, Tuple

# Keep byte-identical with scripts/graph_server/server.py:CSP.
CSP = (
    "default-src 'none'; "
    "script-src 'self' 'unsafe-inline' https://d3js.org https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}

ROUTES = {
    "/": ("graph.html", "text/html; charset=utf-8"),
    "/graph.html": ("graph.html", "text/html; charset=utf-8"),
    "/graph.json": ("graph.json", "application/json"),
}

_LOOPBACK_NAMES = {"127.0.0.1", "localhost", "::1"}
_WILDCARD_HOSTS = {"0.0.0.0", "::", "*", ""}


def norm_host(host: str) -> str:
    return (host or "").strip().lower().strip("[]")


def is_loopback_host(host: str) -> bool:
    h = norm_host(host)
    return h in _LOOPBACK_NAMES or h.startswith("127.")


def expose_override() -> bool:
    return os.environ.get("ENTROPICMEM_GRAPH_EXPOSE", "").strip() == "1"


def split_host_header(value: str) -> Optional[Tuple[str, Optional[int]]]:
    """(hostname, port) from a Host header; None if malformed."""
    value = (value or "").strip()
    if not value:
        return None
    if value.startswith("["):
        end = value.find("]")
        if end < 0:
            return None
        host, rest = value[1:end], value[end + 1:]
        if rest and not rest.startswith(":"):
            return None
        port_s = rest[1:] if rest else ""
    elif value.count(":") == 1:
        host, port_s = value.split(":", 1)
    elif ":" in value:
        return None  # bare IPv6 must be bracketed
    else:
        host, port_s = value, ""
    if port_s and not port_s.isdigit():
        return None
    return norm_host(host), (int(port_s) if port_s else None)


def allowed_host_names(bind: str) -> Set[str]:
    names = set(_LOOPBACK_NAMES)
    b = norm_host(bind)
    if is_loopback_host(b):
        names.add(b)
    if expose_override():
        names.add(b)
        extra = os.environ.get("ENTROPICMEM_GRAPH_ALLOWED_HOSTS") or ""
        names |= {norm_host(h) for h in extra.split(",")}
    return names - _WILDCARD_HOSTS


def check_bind(bind: str) -> Optional[str]:
    """None if serving on ``bind`` is allowed, else the refusal message."""
    if is_loopback_host(bind) or expose_override():
        return None
    return (
        f"refusing to serve the graph on non-loopback address {bind!r}: graph.html "
        "can embed full note bodies and this static server has no token. Bind "
        "127.0.0.1, or set ENTROPICMEM_GRAPH_EXPOSE=1 to accept unauthenticated "
        "exposure (the FastAPI graph server offers token-gated access)."
    )


def make_handler(directory: Path, allowed: Set[str]):
    root = Path(directory).resolve()

    class GraphHandler(http.server.BaseHTTPRequestHandler):
        server_version = "EntropicMemGraph"
        sys_version = ""

        def _send(self, status: int, body: bytes, ctype: str, head: bool) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for name, value in SECURITY_HEADERS.items():
                self.send_header(name, value)
            self.end_headers()
            if not head:
                self.wfile.write(body)

        def _host_ok(self) -> bool:
            parsed = split_host_header(self.headers.get("Host", ""))
            if parsed is None or parsed[0] not in allowed:
                return False
            port = parsed[1] if parsed[1] is not None else 80
            return port == self.server.server_address[1]

        def _serve(self, head: bool) -> None:
            if not self._host_ok():
                self._send(400, b"invalid Host header\n", "text/plain; charset=utf-8", head)
                return
            route = ROUTES.get(self.path.split("?", 1)[0].split("#", 1)[0])
            path = root / route[0] if route else None
            if path is None or not path.is_file():
                self._send(404, b"not found\n", "text/plain; charset=utf-8", head)
                return
            self._send(200, path.read_bytes(), route[1], head)

        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            self._serve(head=False)

        def do_HEAD(self) -> None:  # noqa: N802
            self._serve(head=True)

    return GraphHandler


def make_server(directory: Path, bind: str, port: int) -> http.server.ThreadingHTTPServer:
    """Build (but do not start) the server; raises PermissionError on a
    refused bind. Port 0 picks a free port (see ``server_address``)."""
    refusal = check_bind(bind)
    if refusal:
        raise PermissionError(refusal)
    handler = make_handler(directory, allowed_host_names(bind))
    return http.server.ThreadingHTTPServer((bind, port), handler)
