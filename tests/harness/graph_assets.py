"""The assembled graph viewer template, read from its packaged assets.

EM-605 split ``graph_export.py``'s single ``_HTML_TEMPLATE`` raw string into
three files — ``em/graph/assets/graph.html`` (the shell, with
``__ENTROPICMEM_CSS__`` / ``__ENTROPICMEM_JS__`` / ``__ENTROPICMEM_FAVICON__``
placeholders), ``graph.css`` and ``graph.js``. The exporter inlines them into one
self-contained document, byte for byte the template the old monolith held.

The template-integrity, UX and XSS suites all parse that *assembled* text, so
they read it through here instead of regex-scraping a Python source file. Keeping
the reassembly in one place means a change to the placeholder names can only
break in one place.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "plugins" / "entropicmem" / "scripts" / "em" / "graph" / "assets"


def asset(name: str) -> str:
    """Read one viewer asset verbatim (``graph.html``, ``graph.css``, ``graph.js``)."""
    return (ASSETS / name).read_text(encoding="utf-8")


def template() -> str:
    """The viewer template exactly as the exporter assembles it into `graph.html`.

    The CSS and JS are inlined into the shell's placeholders; the data and
    favicon placeholders are left in place (they are substituted at export time).
    """
    html = asset("graph.html")
    return html.replace("__ENTROPICMEM_CSS__", asset("graph.css")).replace(
        "__ENTROPICMEM_JS__", asset("graph.js")
    )
