"""The viewer assets: ``graph.html`` (the shell), ``graph.css`` and ``graph.js``.

This is a package only so setuptools ships the three files with the wheel — the
data globs below are declared against it, and without the package declaration
setuptools warns that ``em.graph.assets`` is importable but absent from
``packages=`` (an ambiguous configuration that happened to work). Nothing imports
it; the exporter reads it through :mod:`importlib.resources`.
"""
