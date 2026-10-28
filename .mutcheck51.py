#!/usr/bin/env python3
"""Chunk 51 mutation harness — each fix's test must catch its revert."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
FILES = {
    "mig": REPO / "plugins/entropicmem/scripts/em/store/migrations/__init__.py",
    "capsule": REPO / "plugins/entropicmem/scripts/entropicmem.py",
    "config": REPO / "plugins/entropicmem/scripts/em/config.py",
    "provider": REPO / "plugins/entropicmem/scripts/em/provider/provider.py",
}
TEST = "tests/unit/test_em51_cutover_correctness.py"
PY = str(REPO / ".venv311/bin/python")

MUTATIONS = [
    (
        "mig",
        "    if not pending:\n        # Nothing to do: return before the path guard.",
        "    if not pending:\n        assert_safe_db_path(_db_path_of(conn))  # mutated: the old unconditional shape\n        # Nothing to do: return before the path guard.",
        "guard_never_runs",
    ),
    (
        "mig",
        "    if not _store_is_empty(conn):\n        assert_safe_db_path(db_path)",
        "    if True:\n        assert_safe_db_path(db_path)",
        "guard_never_runs",
    ),
    (
        "capsule",
        "                if store_version > _LATEST:",
        "                if False and store_version > _LATEST:",
        "refuses_a_store_newer",
    ),
    (
        "capsule",
        "            if db_path.is_file():\n                from em.store.backup import BackupManager\n\n                BackupManager(db_path).snapshot(reason=\"pre-import\")",
        "            if False:\n                pass",
        "backs_the_target_up",
    ),
    (
        "provider",
        "        self._config[\"core_memory_writable\"] = self._typed_config.core.writable_by_agent\n        self._config_errors = loaded.errors",
        "        self._config_errors = loaded.errors",
        "typed_key",
    ),
    (
        "config",
        '    "core_memory_writable": "core.writable_by_agent",\n',
        "",
        "legacy_flat_key",
    ),
]


def purge_pycache():
    for base in (
        "plugins/entropicmem/scripts/em/store/migrations/__pycache__",
        "plugins/entropicmem/scripts/em/store/__pycache__",
        "plugins/entropicmem/scripts/em/provider/__pycache__",
        "plugins/entropicmem/scripts/__pycache__",
        "plugins/entropicmem/scripts/em/__pycache__",
    ):
        shutil.rmtree(REPO / base, ignore_errors=True)


def run_pytest(kexpr):
    proc = subprocess.run(
        [PY, "-m", "pytest", "-q", TEST, "-k", kexpr, "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True, env=os.environ.copy(),
    )
    return proc.returncode != 0, (proc.stdout + proc.stderr)[-300:]


def main():
    originals = {k: p.read_bytes() for k, p in FILES.items()}
    digests = {k: hashlib.sha256(b).hexdigest() for k, b in originals.items()}
    failures = 0
    for key, old, new, kexpr in MUTATIONS:
        text = originals[key].decode()
        assert text.count(old) == 1, f"anchor not unique in {key}: {old[:60]!r}"
        FILES[key].write_bytes(text.replace(old, new, 1).encode())
        purge_pycache()
        red, tail = run_pytest(kexpr)
        FILES[key].write_bytes(originals[key])
        purge_pycache()
        ok = hashlib.sha256(FILES[key].read_bytes()).hexdigest() == digests[key]
        print(f"{'RED' if red else 'SURVIVED':9} {old[:58]!r} (restore {'ok' if ok else 'FAILED'})", flush=True)
        if not red or not ok:
            failures += 1
            print(tail)
    print("all mutations red" if not failures else f"{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
