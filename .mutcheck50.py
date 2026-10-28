#!/usr/bin/env python3
"""Chunk 50 mutation harness — the drills must catch the upgrade-path breaks."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
VAULT = REPO / "plugins/entropicmem/scripts/em_internal/vault.py"
MIG = REPO / "plugins/entropicmem/scripts/em/store/migrations/0002_v3_core.py"
TEST = "tests/unit/test_em901_upgrade_drills.py"
PY = str(REPO / ".venv311/bin/python")

MUTATIONS = [
    (
        "the old-vault list coercion dropped (null reaches Note.importance)",
        VAULT,
        'tags=_frontmatter_list(fm.get("tags")),',
        'tags=fm.get("tags", []),',
        "old_style_note or old_vault",
    ),
    (
        "the title null-coercion dropped (a null title reaches compute_entropic_id)",
        VAULT,
        'title=str(title),',
        'title=title,',
        "old_style_note",
    ),
    (
        "0002 stops copying the legacy id (legacy ids unresolvable after migration)",
        MIG,
        '"id, legacy_id, scope_profile, scope_user, scope_chat, visibility, kind, "',
        '"id, legacy_id, scope_profile, scope_user, scope_chat, visibility, kind, "',
        "SKIP",
    ),
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def purge_pycache() -> None:
    for base in ("plugins/entropicmem/scripts/em_internal/__pycache__",
                 "plugins/entropicmem/scripts/em/store/migrations/__pycache__",
                 "plugins/entropicmem/scripts/em/store/__pycache__"):
        shutil.rmtree(REPO / base, ignore_errors=True)


def run_pytest(kexpr: str) -> tuple[bool, str]:
    proc = subprocess.run(
        [PY, "-m", "pytest", "-q", TEST, "-k", kexpr, "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True, env=os.environ.copy(),
    )
    return proc.returncode != 0, (proc.stdout + proc.stderr)[-300:]


def main() -> int:
    vault_original = VAULT.read_bytes()
    mig_original = MIG.read_bytes()
    failures = 0

    # Mutations 1-2: the read boundary.
    vault_digest = hashlib.sha256(vault_original).hexdigest()
    for name, old, new, kexpr in [
        (m[1], m[2], m[3], m[4]) for m in MUTATIONS[:2]
    ]:
        text = vault_original.decode()
        assert text.count(old) == 1, f"anchor not unique: {old!r}"
        VAULT.write_bytes(text.replace(old, new, 1).encode())
        purge_pycache()
        red, tail = run_pytest(kexpr)
        VAULT.write_bytes(vault_original)
        purge_pycache()
        ok = digest(VAULT) == vault_digest
        print(f"{'RED' if red else 'SURVIVED':9} {name} (restore {'ok' if ok else 'FAILED'})", flush=True)
        failures += 0 if red and ok else 1
        if not red or not ok:
            print(tail)

    # Mutation 3: drop the legacy_id column from 0002's INSERT (a targeted
    # byte edit: rename the column in the INSERT's column list only).
    text = mig_original.decode()
    anchor = '"id, legacy_id, scope_profile,'
    assert text.count(anchor) == 1
    mutated = text.replace('"id, legacy_id, scope_profile,', '"id, null, scope_profile,', 1)
    MIG.write_bytes(mutated.encode())
    purge_pycache()
    red, tail = run_pytest("migrates_and_serves or 281_generation")
    MIG.write_bytes(mig_original)
    purge_pycache()
    ok = digest(MIG) == hashlib.sha256(mig_original).hexdigest()
    print(f"{'RED' if red else 'SURVIVED':9} 0002 legacy_id dropped (restore {'ok' if ok else 'FAILED'})", flush=True)
    failures += 0 if red and ok else 1
    if not red or not ok:
        print(tail)

    print("all mutations red" if not failures else f"{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
