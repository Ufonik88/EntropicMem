"""Chunk 49 — the dependency floors state what is verified, no more.

The 2026-10-20 deps round raised floors to "the newest release in the same
major"; the rework refuses that direction, because CI pins exact versions
(``pytest==9.0.3``, ``fastapi==0.143.0``, ``cryptography==50.0.2``,
``ruff==0.16.2``) and a floor **above the tested pin** lets a fresh install
resolve versions the suite has never exercised — and can collide with the
Hermes host's own pins. What these tests pin:

* the security floor is the security fix CI pins — the manifest's own comment
  claims the floors carry it, so the two must name the same version;
* the dev ruff floor is the lint-parity pin — the version the rules are
  written against;
* no extra floor exceeds the version CI actually tests (the class the
  2026-10-20 round got wrong);
* no lock file is tracked — chunk 30's ``.gitignore`` policy, which a stray
  ``git add uv.lock`` once violated.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PYPROJECT = REPO / "pyproject.toml"
WORKFLOW = REPO / ".github" / "workflows" / "test.yml"


def _floor(extra: str, package: str) -> str:
    """The version floor ``pyproject.toml`` declares for one package."""
    text = PYPROJECT.read_text(encoding="utf-8")
    block = re.search(rf"^{extra} = \[(.*?)\]", text, re.M | re.S)
    assert block, f"pyproject.toml declares no [{extra}] extra"
    for spec in re.findall(r'"([^"]+)"', block.group(1)):
        name, _, rest = spec.partition(">=")
        if name.strip() == package:
            return rest.split(",")[0].strip()
    raise AssertionError(f"pyproject.toml's [{extra}] names no floor for {package}")


def _ci_pin(package: str) -> str:
    """The exact version the CI workflow pins for one package."""
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(rf'{package}==([0-9][^"\s]*)', text)
    assert match, f"the CI workflow pins no exact version for {package}"
    return match.group(1)


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def test_the_security_floor_carries_the_pinned_security_fix():
    """The manifest's own comment: the floors carry the current security fix."""
    assert _floor("security", "cryptography") == _ci_pin("cryptography"), (
        "cryptography's floor and CI's security pin name different versions — "
        "the manifest claims the floors carry the fix CI enforces"
    )


def test_the_dev_ruff_floor_is_the_lint_parity_pin():
    """The lint rules are written against the pinned ruff; the floor says so."""
    assert _floor("dev", "ruff") == _ci_pin("ruff"), (
        "ruff's dev floor is not the lint-parity version CI pins — a fresh "
        "dev install would lint with something the recorded parity does not cover"
    )


def test_no_extra_floor_exceeds_the_pin_ci_tests():
    """The class the 2026-10-20 round got wrong: floors above the tested pin."""
    # pytest rides [dev], fastapi rides [serve]; both are CI-pinned exactly.
    for extra, package in (("dev", "pytest"), ("serve", "fastapi")):
        floor = _version_tuple(_floor(extra, package))
        pinned = _version_tuple(_ci_pin(package))
        assert floor <= pinned, (
            f"{package}'s {extra} floor ({'.'.join(map(str, floor))}) is above the "
            f"version CI tests ({'.'.join(map(str, pinned))}) — a fresh install would "
            "resolve a version the suite has never exercised"
        )


def test_no_lockfile_is_tracked():
    """Chunk 30's policy: the repo ships as source, not a locked application."""
    tracked = subprocess.run(
        ["git", "ls-files", "*.lock"], cwd=REPO, capture_output=True, text=True
    ).stdout.strip()
    assert tracked == "", f"a lock file is tracked against policy: {tracked}"
