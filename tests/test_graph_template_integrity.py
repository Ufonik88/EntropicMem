"""
test_graph_template_integrity.py — the graph template must not call helpers
it doesn't define.

Regression guard for the missing-``nodeColor`` incident (2026-09-17): the
edge-overhaul template rewrite deleted ``function nodeColor(d)`` but kept its
call sites, so every exported ``graph.html`` threw a ``ReferenceError`` inside
``render()`` before the D3 simulation started — the loading overlay never
hid and the page showed an endless "Building graph…" spinner on every
browser/OS. Nothing in the Python layer noticed, because the export itself
succeeded.

These tests parse the inline JS of ``_HTML_TEMPLATE`` in ``graph_export.py``
and assert that every camelCase helper *called* in the template has a
definition (``function``, ``const``, ``let``, ``var`` or ``class``).
Single-word lowercase names are skipped: the template's comments and prose
contain plenty ("translate (…)", "pixel (…)" inside ``/* … */`` blocks) and
this viewer's JS style is camelCase for helpers.
"""

import re
from pathlib import Path

import pytest

_SRC = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "entropicmem"
    / "scripts"
    / "graph_export.py"
)

# Bare identifiers JS provides (called without a leading dot).
_BUILTINS = {
    "parseInt", "parseFloat", "isNaN", "isFinite",
    "setTimeout", "clearTimeout", "setInterval", "clearInterval",
    "requestAnimationFrame", "cancelAnimationFrame",
    "encodeURIComponent", "decodeURIComponent", "encodeURI", "decodeURI",
    "alert", "confirm", "prompt", "fetch",
    "Number", "String", "Boolean", "Array", "Object", "Date", "Error",
    "TypeError", "RegExp", "Set", "Map", "WeakMap", "Promise",
    "structuredClone", "queueMicrotask", "getComputedStyle", "matchMedia",
    "btoa", "atob", "Image", "URL", "URLSearchParams", "Intl", "Symbol",
    "Proxy", "XMLSerializer",
}

_KEYWORDS = {
    "if", "for", "while", "switch", "catch", "return", "typeof", "function",
    "new", "delete", "void", "in", "of", "do", "else", "try", "throw",
    "case", "await", "yield", "super", "this",
}

# Helpers the visual encodings must keep defining (incident set + neighbours).
_REQUIRED_HELPERS = (
    "nodeColor", "nodeRadius", "edgeWidth", "edgeColor", "edgeDash",
    "shapePath", "haloGradientRef", "computeLabelOpacity",
)

_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_CAMEL = re.compile(r"^[a-z][\w$]*[A-Z][\w$]*$")


@pytest.fixture(scope="module")
def template() -> str:
    src = _SRC.read_text(encoding="utf-8")
    m = re.search(r'_HTML_TEMPLATE = r"""(.*)"""\s*$', src, re.S)
    assert m, "could not locate _HTML_TEMPLATE in graph_export.py"
    return m.group(1)


@pytest.fixture(scope="module")
def inline_js(template: str) -> str:
    blocks = re.findall(r"<script>(.*?)</script>", template, re.S)
    assert blocks, "no inline <script> block in the template"
    js = max(blocks, key=len)
    # The payload placeholder is a single line; neutralise it so nothing in
    # it can ever be mistaken for code if it ever becomes non-trivial.
    return re.sub(r"const DATA = .*?;", "const DATA = {};", js, count=1, flags=re.S)


def _defined_names(js: str) -> set:
    defined = set(re.findall(r"function\s+([A-Za-z_$][\w$]*)\s*\(", js))
    defined |= set(re.findall(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", js))
    defined |= set(re.findall(r"class\s+([A-Za-z_$][\w$]*)", js))
    return defined


def _param_names(js: str) -> set:
    params = set()
    for plist in re.findall(r"function[^(]*\(([^()]*)\)", js):
        params |= {p.strip() for p in plist.split(",") if _IDENT.fullmatch(p.strip() or "")}
    for plist in re.findall(r"\(([^()]*)\)\s*=>", js):
        params |= {p.strip() for p in plist.split(",") if _IDENT.fullmatch(p.strip() or "")}
    return params


def test_every_called_helper_has_a_definition(inline_js: str):
    """A camelCase ``helper(`` call with no matching definition is the bug."""
    defined = _defined_names(inline_js) | _param_names(inline_js)
    missing = {}
    for mo in re.finditer(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(", inline_js):
        name = mo.group(1)
        if name in _KEYWORDS or name in _BUILTINS or name in defined:
            continue
        if not _CAMEL.match(name):
            # Single-word lowercase names only ever appear in comments/prose
            # in this template; helpers here are camelCase.
            continue
        missing[name] = missing.get(name, 0) + 1
    assert not missing, (
        "template calls helpers with no definition (would break rendering "
        f"with a ReferenceError): {sorted(missing)}"
    )


def test_visual_encoding_helpers_are_defined(template: str):
    """Belt and braces: the encoding helpers must exist even if a call site
    is dropped alongside the definition (then the first test sees no call)."""
    for helper in _REQUIRED_HELPERS:
        assert re.search(rf"function\s+{helper}\s*\(", template), (
            f"visual-encoding helper '{helper}' is not defined in the template"
        )
