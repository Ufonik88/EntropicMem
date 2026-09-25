"""EM-114: the stdlib server behind `entropicmem graph serve`.

Real sockets on an ephemeral loopback port; requests use http.client so the
Host header can be set exactly as a DNS-rebinding page or a LAN client would.
"""
import http.client
import re
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import graph_static

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def export_dir(tmp_path):
    d = tmp_path / "export"
    d.mkdir()
    (d / "graph.html").write_text("<html><title>EntropicMem</title>BODY-OF-NOTE</html>",
                                  encoding="utf-8")
    (d / "graph.json").write_text('{"nodes": []}', encoding="utf-8")
    (d / "secret.md").write_text("SECRET_MARKER_SHOULD_NOT_LEAK", encoding="utf-8")
    (d / "index.db").write_bytes(b"SQLite format 3\x00")
    return d


@pytest.fixture
def clean_env(monkeypatch):
    for var in ("ENTROPICMEM_GRAPH_EXPOSE", "ENTROPICMEM_GRAPH_ALLOWED_HOSTS"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def served(export_dir, clean_env):
    httpd = graph_static.make_server(export_dir, "127.0.0.1", 0)
    t = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    t.start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def _req(port, path="/", host=None, method="GET"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.putrequest(method, path, skip_host=True)
    if host is not None:
        conn.putheader("Host", host)
    conn.endheaders()
    r = conn.getresponse()
    body = r.read()
    conn.close()
    return r.status, dict((k.lower(), v) for k, v in r.getheaders()), body


def test_serves_graph_on_loopback_host_and_actual_port(served):
    for host in (f"127.0.0.1:{served}", f"localhost:{served}"):
        status, headers, body = _req(served, "/", host)
        assert status == 200 and b"BODY-OF-NOTE" in body, host
    status, headers, body = _req(served, "/graph.json", f"127.0.0.1:{served}")
    assert status == 200 and headers["content-type"] == "application/json"


@pytest.mark.parametrize("host", ["evil.example:{p}", "127.0.0.1:1", "127.0.0.1",
                                  "0.0.0.0:{p}", "a:b:c", ""])
def test_rejects_rebinding_and_wrong_port_hosts(served, host):
    status, headers, body = _req(served, "/", host.format(p=served))
    assert status == 400
    assert b"BODY-OF-NOTE" not in body


def test_rejects_missing_host_header(served):
    status, _, body = _req(served, "/", None)
    assert status == 400 and b"BODY-OF-NOTE" not in body


@pytest.mark.parametrize("path", ["/secret.md", "/index.db", "/../secret.md",
                                  "/%2e%2e/secret.md", "/export/", "/graph.html/.."])
def test_only_graph_artifacts_are_served(served, path):
    status, _, body = _req(served, path, f"127.0.0.1:{served}")
    assert status == 404, path
    assert b"SECRET_MARKER" not in body and b"SQLite" not in body


def test_security_headers_on_every_response(served):
    for path, host, expected in [("/", f"127.0.0.1:{served}", 200),
                                 ("/nope", f"127.0.0.1:{served}", 404),
                                 ("/", "evil.example", 400)]:
        status, headers, _ = _req(served, path, host)
        assert status == expected
        assert headers["content-security-policy"] == graph_static.CSP
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["referrer-policy"] == "no-referrer"


def test_head_and_unsupported_methods(served):
    status, headers, body = _req(served, "/", f"127.0.0.1:{served}", method="HEAD")
    assert status == 200 and body == b""
    status, _, _ = _req(served, "/", f"127.0.0.1:{served}", method="POST")
    assert status == 501


def test_non_loopback_bind_refused_without_expose(export_dir, clean_env):
    with pytest.raises(PermissionError, match="ENTROPICMEM_GRAPH_EXPOSE"):
        graph_static.make_server(export_dir, "0.0.0.0", 0)
    assert graph_static.check_bind("192.0.2.10")
    assert graph_static.check_bind("127.0.0.1") is None
    assert graph_static.check_bind("localhost") is None


def test_exposed_allowlist(clean_env, monkeypatch):
    assert graph_static.allowed_host_names("0.0.0.0") == {"127.0.0.1", "localhost", "::1"}
    monkeypatch.setenv("ENTROPICMEM_GRAPH_ALLOWED_HOSTS", "graph.example.org")
    assert "graph.example.org" not in graph_static.allowed_host_names("0.0.0.0")
    monkeypatch.setenv("ENTROPICMEM_GRAPH_EXPOSE", "1")
    names = graph_static.allowed_host_names("0.0.0.0")
    assert "graph.example.org" in names and "0.0.0.0" not in names
    assert "192.0.2.10" in graph_static.allowed_host_names("192.0.2.10")
    assert graph_static.check_bind("0.0.0.0") is None


def test_cli_serve_refuses_non_loopback_bind(export_dir, tmp_path, clean_env, monkeypatch, capsys):
    import entropicmem

    monkeypatch.setattr(entropicmem, "_resolve_env",
                        lambda: (tmp_path / "vault", tmp_path / "index.db"))
    args = SimpleNamespace(graph_command="serve", dir=str(export_dir), port=0, bind="0.0.0.0")
    assert entropicmem.cmd_graph(args) == 2
    assert "ENTROPICMEM_GRAPH_EXPOSE" in capsys.readouterr().err


def test_cli_serve_uses_hardened_server(export_dir, tmp_path, clean_env, monkeypatch, capsys):
    import entropicmem

    monkeypatch.setattr(entropicmem, "_resolve_env",
                        lambda: (tmp_path / "vault", tmp_path / "index.db"))
    built = {}
    real = graph_static.make_server

    def fake_make_server(directory, bind, port):
        httpd = real(directory, bind, port)
        built["handler"] = httpd.RequestHandlerClass
        httpd.serve_forever = lambda: None  # return immediately
        return httpd

    monkeypatch.setattr(graph_static, "make_server", fake_make_server)
    args = SimpleNamespace(graph_command="serve", dir=str(export_dir), port=0, bind="127.0.0.1")
    assert entropicmem.cmd_graph(args) == 0
    assert built["handler"].__name__ == "GraphHandler"
    assert re.search(r"http://127\.0\.0\.1:\d+/graph\.html", capsys.readouterr().out)


# ── drift guard against the FastAPI graph server ────────────────────────────

def _server_source() -> str:
    return (ROOT / "scripts" / "graph_server" / "server.py").read_text(encoding="utf-8")


def test_csp_matches_fastapi_server():
    src = _server_source()
    block = re.search(r"^CSP = \((.*?)^\)", src, re.S | re.M).group(1)
    server_csp = "".join(re.findall(r'"([^"]*)"', block))
    assert server_csp == graph_static.CSP


def test_host_parsing_matches_fastapi_server():
    pytest.importorskip("fastapi")
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import graph_server.server as server
    finally:
        sys.path.remove(str(ROOT / "scripts"))
    cases = ["127.0.0.1:8075", "[::1]:1", "[::1]", "LocalHost", "", "::1", "[::1]x",
             "host:port", "a:1:2", "evil.example:80", "[fe80::1]:99"]
    for c in cases:
        assert graph_static.split_host_header(c) == server._split_host_header(c), c
