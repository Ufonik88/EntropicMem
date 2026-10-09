"""The vector tests must not be silently skipped in CI.

Two tests in ``test_em_embedding_cache.py`` (the numpy/pure-Python agreement
check and the 50k p95 < 25 ms AC) skip without numpy; the other five skips on a
bare box are environment-only (two internal-ops scripts, the private digest
list). CI's ordinary ``test`` job installs numpy for exactly this reason.

This guard fails if the job loses numpy, stops running the suite, or the two
gated tests disappear — so "the vector paths are green in CI" can never mean
"they never ran". It is a structural check on the workflow text, in the same
family as the docs-link and CLI-drift guards.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "test.yml"
CACHE_TESTS = REPO / "tests" / "unit" / "test_em_embedding_cache.py"

#: The two tests that skip without numpy. Deleting one to silence a red run
#: would silently turn the vector agreement/AC checks off.
GATED_TESTS = (
    "test_numpy_and_python_paths_agree",
    "test_50k_vectors_search_p95_under_25ms_with_numpy",
)


def _job_block(name: str) -> str:
    """The YAML text of job ``name``, up to the next two-space-indented key."""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = None
    for index, line in enumerate(lines):
        if line == f"  {name}:":
            start = index
            break
    assert start is not None, f"workflow has no `{name}:` job"
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.match(r"^  [A-Za-z][A-Za-z0-9_-]*:$", lines[index]):
            end = index
            break
    return "\n".join(lines[start:end])


def test_the_test_job_installs_numpy_and_runs_the_suite():
    block = _job_block("test")
    installs = [line for line in block.splitlines() if "pip install" in line]
    assert installs, "the test job has no pip install step"
    assert any("numpy" in line for line in installs), (
        "the test job no longer installs numpy; the two gated vector tests would "
        "silently skip in CI. Re-add numpy to the pip install line or remove the "
        "gating from the tests."
    )
    assert any(line.strip() == "- run: pytest -q tests/" for line in block.splitlines()), (
        "the test job no longer runs the full test suite"
    )


def test_both_numpy_gated_vector_tests_still_exist():
    source = CACHE_TESTS.read_text(encoding="utf-8")
    missing = [name for name in GATED_TESTS if f"def {name}(" not in source]
    assert not missing, (
        f"numpy-gated vector tests disappeared: {missing}. CI installs numpy so "
        "these run; deleting them would remove the cache-agreement and 50k AC checks."
    )
