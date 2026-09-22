"""
test_graph_xss.py — Stored-XSS regression tests for the graph viewer template.

The modal renders note bodies with marked.parse() into innerHTML (marked passes
raw HTML straight through), so a stored note body like <img src=x
onerror=alert(1)> used to execute in the viewer. The fix is layered:

  * export_html() HTML-escapes every body it embeds into the template payload
  * the template routes every dynamic string through escapeHtml()
  * marked output additionally passes sanitizeRenderedHtml() (covers raw
    lazy-fetched bodies and hostile markdown links)
  * the Linked Mentions pane is built with addEventListener + data-attributes
    instead of string-concatenated inline onclick handlers

These tests render the template with a malicious note body and assert no raw
HTML event handler survives, plus structural checks on the template's sinks.
"""

import re
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent.parent / "plugins" / "entropicmem" / "scripts"
sys.path.insert(0, str(_SCRIPT_DIR))

from graph_export import export_html  # noqa: E402
from index import VaultIndex  # noqa: E402
from vault import Vault  # noqa: E402

_SRC = _SCRIPT_DIR / "graph_export.py"

XSS_BODY = (
    '<img src=x onerror=alert(1)>'
    '<svg onload=alert(2)>'
    '<script>window.__xss=3</script>'
    '<iframe src="javascript:alert(4)"></iframe>'
    '[click me](javascript:alert(5))'
)


class _TagCollector(HTMLParser):
    """Collects (tag, attr_name) for every parsed HTML attribute."""

    def __init__(self):
        super().__init__()
        self.attrs = []

    def handle_starttag(self, tag, attrs):
        for name, _value in attrs:
            self.attrs.append((tag, name))


@pytest.fixture
def rendered(tmp_path):
    """Render the template with a malicious note body embedded."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)
    vault = Vault(vault_root)
    good = vault.write_note("Knowledge", "Good Note", "Body with [[Good Note]].",
                            tags=["t"], domain="Knowledge")
    evil = vault.write_note("Knowledge", "Evil Note", XSS_BODY,
                            tags=["t"], domain="Knowledge")
    index = VaultIndex(tmp_path / "index.db")
    index.upsert_note(vault.read_note(good))
    index.upsert_note(vault.read_note(evil))
    out = tmp_path / "graph.html"
    html = export_html(index, out, max_nodes=50, vault_root=vault_root, include_bodies=True)
    index.close()
    return html


@pytest.fixture(scope="module")
def template() -> str:
    src = _SRC.read_text(encoding="utf-8")
    m = re.search(r'_HTML_TEMPLATE = r"""(.*)"""\s*$', src, re.S)
    assert m, "could not locate _HTML_TEMPLATE in graph_export.py"
    return m.group(1)


# ── rendered output: the malicious body must not survive as markup ─────────

def test_no_raw_event_handler_survives_in_rendered_template(rendered):
    """No tag anywhere in the rendered document may carry a raw on* handler
    attribute (belt-and-braces next to the payload-substring check below:
    every legitimate element of the template/export must be handler-free)."""
    collector = _TagCollector()
    collector.feed(rendered)
    offenders = sorted({(tag, attr) for tag, attr in collector.attrs
                        if attr.lower().startswith("on")})
    assert not offenders, f"raw HTML event handlers survived rendering: {offenders}"


def test_payload_markup_is_escaped_not_embedded(rendered):
    # The malicious body lands only in the embedded DATA payload, so the raw
    # payload markup must be absent there — only escaped (inert) text may
    # survive. This is the regression check for the export-side body escaping.
    assert "<img src=x onerror=alert(1)>" not in rendered
    assert "<svg onload=alert(2)>" not in rendered
    assert "<script>window.__xss=3</script>" not in rendered
    assert '<iframe src="javascript:alert(4)">' not in rendered
    # …and the body is still present, just inert (shown as literal text).
    assert "&lt;img src=x onerror=alert(1)&gt;" in rendered
    assert "&lt;svg onload=alert(2)&gt;" in rendered


def test_legit_body_still_embedded(rendered):
    assert "Body with [[Good Note]]." in rendered


# ── template sinks: dynamic text through escapeHtml(), no inline handlers ──

def test_markdown_rendering_is_sanitized(template):
    assert "function sanitizeRenderedHtml(" in template
    assert "function renderMarkdown(" in template
    assert "renderMarkdown(noteBody)" in template
    # sanitize pass must strip event handlers and script-scheme URLs
    assert 'name.startsWith("on")' in template
    assert "removeAttribute" in template
    assert re.search(r"\(\s*javascript\|vbscript\|data\s*\)", template), \
        "URL-scheme allowlist guard missing from sanitizeRenderedHtml"


def test_tooltip_routes_dynamic_text_through_escape_html(template):
    m = re.search(r"function showTooltip\(event, d\) \{(.*?)\n\}", template, re.S)
    assert m, "showTooltip not found"
    body = m.group(1)
    assert "escapeHtml(d.type)" in body, "tooltip leaks d.type raw"
    assert "escapeHtml(d.domain" in body, "tooltip leaks d.domain raw"
    assert "escapeHtml((d.tags" in body, "tooltip leaks tags raw"


def test_legend_escapes_domain_names(template):
    m = re.search(r"function buildLegend\(\) \{(.*?)\n\}", template, re.S)
    assert m, "buildLegend not found"
    assert "escapeHtml(domain)" in m.group(1), "buildLegend injects domain names raw"


def test_tag_suggestions_use_dom_not_html_strings(template):
    m = re.search(r"function buildTagSuggestions\(\) \{(.*?)\n\}", template, re.S)
    assert m, "buildTagSuggestions not found"
    body = m.group(1)
    assert 'createElement("option")' in body
    assert "opt.value = t" in body
    assert "<option value=" not in body, "tag suggestions build raw HTML again"


def test_linked_mentions_use_event_listeners_and_data_attributes(template):
    assert 'onclick="' not in template, "inline onclick handler string is back"
    assert "a.dataset.noteId" in template
    assert 'a.addEventListener("click"' in template
    assert "applyFocus(a.dataset.noteId)" in template
