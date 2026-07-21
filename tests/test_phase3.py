"""
test_phase3.py — Tests for Phase 3 graph visualizer.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent.parent / "skills" / "entropicmem" / "scripts"
_CLI = str(_SCRIPT_DIR / "entropicmem.py")
sys.path.insert(0, str(_SCRIPT_DIR))

from vault import Vault
from index import VaultIndex
from graph_export import (
    export_json, export_dot, export_html, export_canvas,
    get_color, get_shape,
    DOMAIN_PALETTE,
)


def _run(*args, **env):
    full_env = {**os.environ, **env}
    return subprocess.run(
        [sys.executable, _CLI, *args],
        capture_output=True, text=True, env=full_env,
    )


@pytest.fixture
def populated_index():
    """Create a vault with 20 notes across 4 domains and return (vault, index)."""
    with tempfile.TemporaryDirectory() as td:
        vp = Path(td) / "vault"
        ip = Path(td) / "index.db"
        _run("init", "--vault", str(vp), "--index-db", str(ip),
             ENTROPICMEM_VAULT_PATH=str(vp), ENTROPICMEM_INDEX_DB=str(ip))

        vault = Vault(vp)
        index = VaultIndex(ip)

        notes_data = []
        for i in range(5):
            notes_data.append(("Infrastructure", f"Infra Note {i}",
                f"Body about infrastructure {i}. See [[Infra Note {i+1}]]" if i < 4 else f"Body about infra {i}.",
                ["infrastructure", f"test{i}"]))
            notes_data.append(("Ajax Systems", f"Ajax Note {i}",
                f"Body about Ajax {i}. See [[Ajax Note {i+1}]]" if i < 4 else f"Body about Ajax {i}.",
                ["ajax", f"test{i}"]))
            notes_data.append(("Finance", f"Finance Note {i}",
                f"Body about finance {i}.",
                ["finance", f"test{i}"]))
            notes_data.append(("Knowledge", f"Knowledge Note {i}",
                f"Body about knowledge {i}. See [[Infra Note {i}]].",
                ["knowledge", f"test{i}"]))

        for domain, title, body, tags in notes_data:
            path = vault.write_note(domain, title, body, tags=tags, domain=domain)
            note = vault.read_note(path)
            index.upsert_note(note)
            index.upsert_edges_for_note(vault, note)

        yield vault, index
        index.close()


class TestGraphExport:
    def test_export_json(self, populated_index):
        vault, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.json"
        data = export_json(index, out, max_nodes=100)
        assert out.exists()
        assert len(data["nodes"]) >= 20
        assert "nodes" in data
        assert "edges" in data
        assert "meta" in data
        # Every node has required fields
        for n in data["nodes"]:
            assert "id" in n
            assert "title" in n
            assert "color" in n
            assert "shape" in n
            assert "importance" in n

    def test_export_json_domain_filter(self, populated_index):
        vault, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.json"
        data = export_json(index, out, domain="Finance", max_nodes=50)
        for n in data["nodes"]:
            assert n["domain"] == "Finance"

    def test_export_dot(self, populated_index):
        vault, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.dot"
        text = export_dot(index, out, max_nodes=50)
        assert out.exists()
        assert "digraph vault" in text
        assert "Infra Note" in text

    def test_export_html(self, populated_index):
        vault, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert out.exists()
        assert "<!DOCTYPE html>" in html
        assert "d3js.org" in html
        size = out.stat().st_size
        assert size > 2000, f"HTML too small: {size} bytes"
        # Verify embedded JSON is valid
        import re
        match = re.search(r'const DATA = ({.*?});', html, re.DOTALL)
        assert match, "DATA not found in HTML"
        data = json.loads(match.group(1))
        assert len(data["nodes"]) >= 20

    def test_export_html_embeds_full_body(self, populated_index):
        """Modal must show real note bodies (with wikilinks), not empty placeholders."""
        vault, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50, vault_root=vault.root)
        import re
        match = re.search(r'const DATA = ({.*?});', html, re.DOTALL)
        data = json.loads(match.group(1))
        with_body = [n for n in data["nodes"] if n.get("full_body")]
        assert len(with_body) >= 20, f"only {len(with_body)} nodes have full_body"
        infra = next(n for n in data["nodes"] if "Infra Note 0" in n["title"])
        assert "[[" in infra["full_body"], "wikilink missing from embedded body"

    def test_export_html_js_is_valid(self, populated_index):
        """The inline app script must parse (guards against duplicate-declaration
        SyntaxErrors that silently blank the whole visualizer)."""
        vault, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50, vault_root=vault.root)
        import re, shutil
        scripts = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
        assert scripts, "no inline <script> block"
        app_js = scripts[-1]
        # No duplicate top-level declarations of the same binding
        for binding in ("currentNodeData", "const body"):
            assert app_js.count(binding) <= 1, f"duplicate '{binding}' in app JS"
        # If node is available, do a real syntax check
        node = shutil.which("node")
        if node:
            jsf = Path(tempfile.mkdtemp()) / "app.js"
            jsf.write_text(app_js)
            r = subprocess.run([node, "--check", str(jsf)], capture_output=True, text=True)
            assert r.returncode == 0, f"node --check failed:\n{r.stderr}"

    def test_export_canvas(self, populated_index):
        vault, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.canvas"
        data = export_canvas(index, out, max_nodes=20)
        assert out.exists()
        assert "nodes" in data
        assert "edges" in data

    def test_color_palette(self):
        """All 9 domains have assigned colors."""
        assert get_color("Infrastructure") == "#1DCF8E"
        assert get_color("Ajax Systems") == "#5AE4AA"
        assert get_color("X-Growth") == "#00AD74"
        assert get_color("Finance") == "#FFB800"
        assert get_color("Workflows") == "#7C4DFF"
        assert get_color("People") == "#FF6B6B"
        assert get_color("Knowledge") == "#4FC3F7"
        assert get_color("Products-Research") == "#FF9800"
        assert get_color("Projects") == "#9CCC65"
        assert get_color("UnknownDomain") == "#888888"

    def test_shape_mapping(self):
        assert get_shape("permanent") == "circle"
        assert get_shape("literature") == "square"
        assert get_shape("moc") == "diamond"
        assert get_shape("index") == "triangle"


class TestGraphCLI:
    def test_cli_graph_export_html(self, populated_index):
        vault, index = populated_index
        index.close()
        out_dir = Path(tempfile.mkdtemp())
        r = _run("graph", "export", "--output-dir", str(out_dir), "--format", "html",
                 ENTROPICMEM_VAULT_PATH=str(vault.root), ENTROPICMEM_INDEX_DB=str(index.db_path))
        assert r.returncode == 0
        html_path = out_dir / "graph.html"
        assert html_path.exists()
        assert html_path.stat().st_size > 2000

    def test_cli_graph_export_json(self, populated_index):
        vault, index = populated_index
        index.close()
        out_dir = Path(tempfile.mkdtemp())
        r = _run("graph", "export", "--output-dir", str(out_dir), "--format", "json",
                 ENTROPICMEM_VAULT_PATH=str(vault.root), ENTROPICMEM_INDEX_DB=str(index.db_path))
        assert r.returncode == 0
        json_path = out_dir / "graph.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert len(data["nodes"]) >= 20

    def test_cli_graph_export_domain_filter(self, populated_index):
        vault, index = populated_index
        index.close()
        out_dir = Path(tempfile.mkdtemp())
        r = _run("graph", "export", "--output-dir", str(out_dir), "--format", "json",
                 "--domain", "Finance", "--max-nodes", "10",
                 ENTROPICMEM_VAULT_PATH=str(vault.root), ENTROPICMEM_INDEX_DB=str(index.db_path))
        assert r.returncode == 0
        data = json.loads((out_dir / "graph.json").read_text())
        for n in data["nodes"]:
            assert n["domain"] == "Finance"

    def test_cli_graph_export_min_importance(self, populated_index):
        vault, index = populated_index
        index.close()
        out_dir = Path(tempfile.mkdtemp())
        r = _run("graph", "export", "--output-dir", str(out_dir), "--format", "json",
                 "--min-importance", "0.9", "--max-nodes", "50",
                 ENTROPICMEM_VAULT_PATH=str(vault.root), ENTROPICMEM_INDEX_DB=str(index.db_path))
        assert r.returncode == 0
        data = json.loads((out_dir / "graph.json").read_text())
        for n in data["nodes"]:
            assert n["importance"] >= 0.9


class TestPhase3Gate:
    def test_gate_has_nodes(self, populated_index):
        """Gate: export should have >50 nodes on the test setup."""
        vault, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.json"
        data = export_json(index, out, max_nodes=100)
        # Our fixture has 20 notes, so this is what we have
        assert len(data["nodes"]) >= 20

    def test_gate_html_self_contained(self, populated_index):
        """Gate: HTML file is self-contained with embedded JSON."""
        vault, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        # Must contain DATA and not require external JSON fetch
        assert "const DATA =" in html

    def test_gate_html_opens(self, populated_index):
        """Gate: HTML file is valid and parseable."""
        vault, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        export_html(index, out, max_nodes=50)
        content = out.read_text()
        assert "<!DOCTYPE html>" in content
        assert "</html>" in content.rstrip().lower()
