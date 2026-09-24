"""Suite-budget tests (EM-001 maintainer correction, 2026-09-23).

Suite `ci` must run in <= 60 s and carry no ML dependencies even when the
interpreter happens to have sentence-transformers installed (plan lines 704,
1269). Embedding work belongs to suite `full` only.
"""
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Run the REAL ci suite through the CLI inside a fresh interpreter, then dump
# which ML modules made it into sys.modules (maintainer item 4). A subprocess
# keeps the check immune to imports from sibling test files. A module is only
# "imported" if its sys.modules entry is a real module: the lockdown installs
# None sentinels, which make `import` raise ImportError (PEP 302).
_RUNNER_SCRIPT = """
import sys
sys.path.insert(0, {repo!r})
from evals.__main__ import main
rc = main(["run", "--suite", "ci", "--adapter", "v2",
           "--results-dir", {out!r}])
ml = sorted(m for m in ("sentence_transformers", "torch")
            if sys.modules.get(m) is not None)
print("ML_MODULES:", ml)
print("EXIT_CODE:", rc)
"""


def test_ci_suite_never_imports_the_ml_stack(tmp_path):
    script = tmp_path / "runner_probe.py"
    script.write_text(
        _RUNNER_SCRIPT.format(repo=str(REPO), out=str(tmp_path / "res")),
        encoding="utf-8",
    )
    t0 = time.perf_counter()
    out = subprocess.run(
        [sys.executable, str(script)],
        cwd=REPO, capture_output=True, text=True, timeout=120,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "home")},
    )
    elapsed = time.perf_counter() - t0
    assert out.returncode == 0, f"stderr:\n{out.stderr}"
    assert "EXIT_CODE: 0" in out.stdout, out.stdout
    assert "ML_MODULES: []" in out.stdout, \
        f"ci suite imported the ML stack: {out.stdout}"
    assert elapsed <= 60.0, f"ci suite took {elapsed:.1f}s (budget 60s)"


def test_ci_suite_wall_clock_budget(tmp_path):
    """`python -m evals run --suite ci --adapter v2` within the 60 s spec
    budget (plan §EM-001). The subprocess cap is the spec limit itself."""
    t0 = time.perf_counter()
    out = subprocess.run(
        [sys.executable, "-m", "evals", "run", "--suite", "ci", "--adapter", "v2",
         "--results-dir", str(tmp_path)],
        cwd=REPO, capture_output=True, text=True, timeout=60,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "home")},
    )
    elapsed = time.perf_counter() - t0
    assert out.returncode == 0, f"stdout:\n{out.stdout}\nstderr:\n{out.stderr}"
    assert elapsed <= 60.0, f"ci suite took {elapsed:.1f}s (budget 60s)"
