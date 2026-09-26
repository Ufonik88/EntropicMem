"""Formation pipeline: entity linking and memory formation (v3 §3.6).

Modules here derive structure from memories — entities, aliases, relations.
They read and write through ``em.store`` and never touch the Hermes host.
"""
