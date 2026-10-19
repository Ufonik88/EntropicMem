"""The graph package (EM-605): model, renderers and the packaged viewer assets.

The 2,100-line ``graph_export.py`` monolith is split here into three concerns:
`em.graph.model` (what the graph *is* — nodes, edges, palettes, communities),
`em.graph.export` (what it *looks like* — json, dot, canvas and the
self-contained HTML) and ``em.graph/assets`` (the viewer itself: ``graph.html``,
``graph.css`` and ``graph.js``, read through :mod:`importlib.resources` and
inlined at export so a written ``graph.html`` stays one self-contained file).
"""

__all__ = ["model", "export"]
