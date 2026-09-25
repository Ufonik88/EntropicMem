"""CLI smoke tests: `python -m evals run` writes results + prints the table.

Runs the real ci suite through the real v2 adapter via subprocess with a
clean environment (no pytest imports) to prove the AC: stdlib-only on a clean
checkout.
"""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_cli_run_ci_v2_writes_results(tmp_path):
    out = subprocess.run(
        [sys.executable, "-m", "evals", "run", "--suite", "ci", "--adapter", "v2",
         "--results-dir", str(tmp_path)],
        cwd=REPO, capture_output=True, text=True, timeout=180,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "home")},
    )
    assert out.returncode == 0, f"stdout:\n{out.stdout}\nstderr:\n{out.stderr}"
    # Markdown table on stdout
    assert "| metric | value |" in out.stdout
    assert "recall@5" in out.stdout
    # exactly one result JSON in the results dir, named <suite>-<sha>.json
    files = sorted(tmp_path.glob("ci-*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["suite"] == "ci" and data["adapter"] == "v2"
    assert "metrics" in data and "by_category" in data
    assert data["metrics"]["n_turns"] >= 7  # ci.jsonl turn count


def test_cli_compare_prints_deltas(tmp_path):
    results = tmp_path / "ci-base.json"
    data = {
        "suite": "ci", "adapter": "v2", "git_sha": "0" * 8, "k": 5,
        "metrics": {"recall@5": 0.9, "mrr": 0.9, "noise_rate": 0.05},
        "by_category": {}, "turns": [],
    }
    results.write_text(json.dumps(data), encoding="utf-8")
    out = subprocess.run(
        [sys.executable, "-m", "evals", "run", "--suite", "ci", "--adapter", "v2",
         "--results-dir", str(tmp_path / "res"), "--compare", str(results)],
        cwd=REPO, capture_output=True, text=True, timeout=180,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "home")},
    )
    assert out.returncode in (0, 1), out.stderr  # 1 = gate failure allowed
    assert "| metric | baseline | current | delta | regressed |" in out.stdout


def test_cli_unknown_suite_fails(tmp_path):
    out = subprocess.run(
        [sys.executable, "-m", "evals", "run", "--suite", "nope", "--adapter", "v2"],
        cwd=REPO, capture_output=True, text=True, timeout=60,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "home")},
    )
    assert out.returncode != 0
    assert "unknown suite" in (out.stderr + out.stdout).lower()


def _compare_rc(tmp_path, metrics):
    base = tmp_path / "base.json"
    base.write_text(json.dumps({"suite": "ci", "adapter": "v2", "git_sha": "0" * 8, "k": 5,
                                "metrics": metrics, "by_category": {}, "turns": []}),
                    encoding="utf-8")
    out = subprocess.run(
        [sys.executable, "-m", "evals", "run", "--suite", "ci", "--adapter", "v2",
         "--results-dir", str(tmp_path / "res"), "--compare", str(base)],
        cwd=REPO, capture_output=True, text=True, timeout=180,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "home")},
    )
    return out


def test_cli_compare_ignores_non_gated_worsening(tmp_path):
    out = _compare_rc(tmp_path, {"prefetch_tokens": 1.0, "latency_ms": 0.0001})
    assert out.returncode == 0, out.stdout + out.stderr
    assert "| info |" in out.stdout


def test_cli_compare_fails_on_gated_regression(tmp_path):
    out = _compare_rc(tmp_path, {"noise_rate": 0.0})
    assert out.returncode == 1, out.stdout + out.stderr
    assert "REGRESSION vs baseline" in out.stderr
