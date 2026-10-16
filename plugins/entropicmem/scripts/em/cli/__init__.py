"""EM-408: the entropicmem CLI surface's shared pieces (stdlib-only).

``parser.py`` is the argparse tree both entry points mount: the standalone
``scripts/entropicmem.py`` and the host-discovered ``plugins/entropicmem/cli.py``
(``hermes entropicmem ...``). Modules under ``em.*`` never import the host.
"""
