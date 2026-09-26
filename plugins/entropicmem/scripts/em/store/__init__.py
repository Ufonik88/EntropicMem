"""``em.store`` — the v3 storage core: database access, locking, migrations.

Stdlib-only (plan §3.2). Modules here never import the Hermes host or the
provider layer, and never read ``os.environ["HERMES_HOME"]`` — paths are
passed in explicitly.
"""
