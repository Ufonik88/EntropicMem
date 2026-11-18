"""Tests for the --derive-from-record mode of record_suite_figures.py (ADR-001 W45).

Each test maps to one acceptance criterion in
`~/.hermes/kanban/workspaces/code-pipeline/specs/2026-W45-ADR-001-suite-figures-derive.md`.
Written first, watched fail, then made pass — one vertical slice at a time.
"""

from __future__ import annotations

import json

import pytest

REPO_SCRIPTS = "scripts"


@pytest.fixture
def mod(monkeypatch, tmp_path):
    """Import record_suite_figures with RECORD pointed at a temp file.

    A test that exercises `main()` can drop a base record at `mod.RECORD`
    (`tmp_path / "suite_figures.json"`) and the script will read/write there,
    never the real `docs/plan/suite_figures.json`.
    """
    import importlib
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(repo / REPO_SCRIPTS))
    import record_suite_figures

    importlib.reload(record_suite_figures)
    record_suite_figures.RECORD = tmp_path / "suite_figures.json"
    return record_suite_figures


#: A known-good base record: every ladder relation already holds.
BASE_RECORD = {
    "sha": "abc1234",
    "ci_run": "",
    "ci_projected": True,
    "comment": "test base",
    "current": {
        "bare": [3200, 10, 2],
        "digest": [3201, 9, 2],
        "ci_equiv": [3300, 2, 2],
        "ci": [3298, 4, 2],
        "python310": [3300, 2, 2],
    },
    "historical": [],
}


# ── 1. derive returns bare_old + delta ───────────────────────────────────────

def test_derive_returns_bare_old_plus_delta(mod):
    """bare_new = bare_old + (ci_equiv_new - ci_equiv_old), element-wise."""
    old = json.loads(json.dumps(BASE_RECORD))
    # delta = (3310 - 3300, 2 - 2, 2 - 2) = (10, 0, 0)
    result = mod.derive_triples(old, (3310, 2, 2))
    assert result["bare"] == [3210, 10, 2], result["bare"]


# ── 2. digest always equals bare + (1 pass, -1 skip) ────────────────────────

def test_digest_equals_bare_plus_one_pass_minus_one_skip(mod):
    """digest_new = (bare_new_passed + 1, bare_new_skipped - 1, bare_new_xfailed)."""
    old = json.loads(json.dumps(BASE_RECORD))
    result = mod.derive_triples(old, (3310, 2, 2))
    bare = result["bare"]
    digest = result["digest"]
    assert digest == [bare[0] + 1, bare[1] - 1, bare[2]], (digest, bare)


# ── 3. refuses when the base record has no ci_equiv ─────────────────────────

def test_refuses_when_base_has_no_ci_equiv(mod):
    """Refuses (SystemExit) and writes nothing when the base record lacks ci_equiv."""
    old = json.loads(json.dumps(BASE_RECORD))
    del old["current"]["ci_equiv"]
    with pytest.raises(SystemExit, match="ci_equiv"):
        mod.derive_triples(old, (3310, 2, 2))


# ── 4. refuses when a derived count would go negative ───────────────────────

def test_refuses_when_derived_count_would_be_negative(mod):
    """Refuses when a derived triple would go negative.

    old bare = (3200, 10, 2), old ci_equiv = (3300, 2, 2).
    new ci_equiv = (3400, 0, 2) -> delta = (100, -2, 0)
    bare_new_skipped = 10 + (-2) = 8 (ok), digest_new_skipped = 8 - 1 = 7 (ok).
    Force it: old bare skipped = 1 -> bare_new_skipped = 1 - 2 = -1 (negative).
    """
    old = json.loads(json.dumps(BASE_RECORD))
    old["current"]["bare"] = [3200, 1, 2]
    with pytest.raises(SystemExit, match="negative"):
        mod.derive_triples(old, (3400, 0, 2))


# ── 5. derive_record sets derived: true and ci_projected ─────────────────────

def test_derive_record_sets_derived_and_ci_projected(mod):
    """The full record carries derived: true and ci_projected: true when no --ci-run."""
    old = json.loads(json.dumps(BASE_RECORD))
    record = mod.derive_record(old, (3310, 2, 2), ci_line=None, ci_run=None)
    assert record.get("derived") is True, record
    assert record.get("ci_projected") is True, record


# ── 6. --check still reports DRIFT when on-disk counts differ ────────────────

def test_check_reports_drift_when_counts_differ(mod, capsys):
    """--check must exit 1 and print DRIFT when a fresh measurement disagrees.

    The on-disk record has ci_equiv = (3300, 2, 2); a fresh measurement of
    (3310, 2, 2) is drift, and the mode must not launder it.
    """
    mod.RECORD.write_text(json.dumps(BASE_RECORD, indent=2), encoding="utf-8")
    rc = mod.main([
        "--derive-from-record",
        "--ci-equiv", "3310 / 2 / 2",
        "--sha", "abc1234",
        "--check",
    ])
    out = capsys.readouterr().out
    assert rc == 1, f"--check must exit 1 on drift, got {rc}\n{out}"
    assert "DRIFT" in out, out


# ── 7. end-to-end: derived record accepted by test_suite_figures.py ──────────

def _stamp_docs(repo, record: dict, sha: str) -> None:
    """Write BASELINE/CHANGELOG that agree with `record` — the P1a technique.

    Only the FIRST `Read as at` line is updated (the current record's line);
    the rest are history and must be preserved. CHANGELOG gets exactly one
    new `suite figures: ... (derived)` line under [Unreleased].
    """
    import re

    cur = record["current"]
    t = {k: tuple(v) for k, v in cur.items()}
    triple = {k: f"{v[0]} passed, {v[1]} skipped, {v[2]} xfailed" for k, v in t.items()}
    short = {k: f"{v[0]} / {v[1]} / {v[2]}" for k, v in t.items()}
    extras_p = t["ci_equiv"][0] - t["digest"][0]
    extras_s = t["ci_equiv"][1] - t["digest"][1]

    # ── BASELINE.md ──
    path = repo / "docs" / "plan" / "BASELINE.md"
    text = path.read_text(encoding="utf-8")
    out, in_ladder, updated_read_as_at = [], False, False
    for line in text.splitlines():
        stripped = line.strip()

        # The fenced ladder block
        if stripped.startswith("bare ") and " / " in stripped and not in_ladder:
            in_ladder = True
            out.append(f"bare          {short['bare']}")
            continue
        if in_ladder and stripped.startswith("+ extras"):
            sign = "+" if extras_s >= 0 else "\u2212"
            out.append(f"+ extras      +{extras_p} passed, {sign}{abs(extras_s)} skipped   (fastapi/crypto/numpy files)")
            continue
        if in_ladder and stripped.startswith("+ digest list"):
            out.append("+ digest list +1 passed,  \u22121 skipped    (test_no_personal_data.py)")
            continue
        if in_ladder and stripped.startswith("= CI-equiv"):
            out.append(f"= CI-equiv    {short['ci_equiv']}")
            continue
        if in_ladder and stripped.startswith("\u2212 host pins"):
            out.append("\u2212 host pins   \u22122 passed,  +2 skipped    (the two hermes-agent tests skip in CI)")
            continue
        if in_ladder and stripped.startswith("= CI"):
            mark = " (projected from the CI-equivalent by the host-pin relation)" \
                if record.get("ci_projected") else ""
            out.append(f"= CI          {short['ci']}{mark}")
            in_ladder = False
            continue

        # The five table rows (label is the row's first cell only)
        if line.startswith("|"):
            cells = [c.strip() for c in line.split("|")]
            label = cells[1] if len(cells) >= 3 else ""
            key = next((k for needle, k in (
                ("CI, `test` job", "ci"),
                ("bare (`.venv311`", "bare"),
                ("digest list", "digest"),
                ("CI-equivalent", "ci_equiv"),
                ("Python 3.10", "python310"),
            ) if needle in label), None)
            if key:
                line = re.sub(r"\d+ passed, \d+ skipped, \d+ xfailed", triple[key], line)
                if key == "ci" and record.get("ci_projected"):
                    line = re.sub(r"read at `[0-9a-f]{7,40}`", "projected", line)
                    if "projected" not in line:
                        line = line.rstrip() + " *(projected)*"
        out.append(line)

        # Only the FIRST Read-as-at line is rewritten; the rest are history.
        if not updated_read_as_at and stripped.startswith("Read as at `"):
            out[-1] = (
                f"Read as at `{sha}` (derived from the previous record plus the measured "
                "CI-equivalent delta; the count variants were derived, not re-measured)."
            )
            updated_read_as_at = True

    path.write_text("\n".join(out) + "\n", encoding="utf-8")

    # ── CHANGELOG.md — exactly one new derived line under [Unreleased] ──
    # The CI figure must appear in the guard's long slash form: the guard's
    # CHANGELOG check accepts `3308 / 4 / 2` or the word `projected`, and the
    # real repo's [Unreleased] wording is transient (it says `projected` only
    # between a record stamp and its read pass) — a test must not depend on it.
    path = repo / "CHANGELOG.md"
    text = path.read_text(encoding="utf-8")
    note = f"- suite figures: CI **{short['ci']}**, bare **{short['bare']}** (derived)\n"
    if "## [Unreleased]" in text:
        head, rest = text.split("## [Unreleased]", 1)
        text = f"{head}## [Unreleased]\n{note}{rest}"
    else:
        text = f"## [Unreleased]\n{note}\n{text}"
    path.write_text(text, encoding="utf-8")


def test_end_to_end_derived_record_accepted(tmp_path):
    """A derived record + docs stamped to match is accepted by test_suite_figures.py.

    Criterion 7: the whole point of the mode is that a branch can stamp its own
    figures without four interpreters and have the guard agree.
    """
    import os
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    repo = tmp_path / "repo"
    repo.mkdir()
    for d in ["scripts", "docs/plan", "tests"]:
        (repo / d).mkdir(parents=True, exist_ok=True)
    for f in ["scripts/record_suite_figures.py", "scripts/doc_figures.py",
              "tests/test_suite_figures.py"]:
        shutil.copy2(Path(__file__).resolve().parents[1] / f, repo / f)
    for f in ["docs/plan/suite_figures.json", "docs/plan/BASELINE.md",
              "CHANGELOG.md", "MASTER_TODO.md", "docs/plan/REMAINING_PLAN.md",
              "docs/plan/NEXT_CHUNK.md"]:
        src = Path(__file__).resolve().parents[1] / f
        if src.exists():
            shutil.copy2(src, repo / f)

    env = {**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.com"}
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True, env=env)

    def head_sha():
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              cwd=repo, capture_output=True, text=True, env=env).stdout.strip()

    # Seed historical with every triple currently in the temp repo's docs so the
    # docs' prior figures do not read as drift, and anchor the base record at
    # this commit. Read the docs directly (local regex) rather than mutating the
    # shared doc_figures.REPO — a test must not leak state into its siblings.
    import re as _re
    _triple_re = _re.compile(r"(\d+)\s+passed,\s+(\d+)\s+skipped,\s+(\d+)\s+xfailed")
    _short_re = _re.compile(r"\b(\d{3,5}) / (\d{1,3}) / (\d{1,2})\b")
    seed = set()
    for name in ("CHANGELOG.md", "MASTER_TODO.md", "docs/plan/BASELINE.md",
                 "docs/plan/REMAINING_PLAN.md", "docs/plan/NEXT_CHUNK.md"):
        p = repo / name
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        seed |= {tuple(int(g) for g in m.groups()) for m in _triple_re.finditer(text)}
        seed |= {tuple(int(g) for g in m.groups()) for m in _short_re.finditer(text)}
    record_path = repo / "docs/plan/suite_figures.json"
    base = json.loads(json.dumps(BASE_RECORD))
    base["sha"] = head_sha()
    base["historical"] = sorted(list(t) for t in seed)
    record_path.write_text(json.dumps(base, indent=2), encoding="utf-8")

    # Stamp docs to the BASE figures so the derive run's own guard pass is green.
    _stamp_docs(repo, base, base["sha"])
    # A commit touching tests/ so the guard's suite-surface ancestor check resolves.
    (repo / "tests" / "test_placeholder.py").write_text("# placeholder\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "stamp base + tests touch"], cwd=repo, check=True, env=env)
    base["sha"] = head_sha()
    record_path.write_text(json.dumps(base, indent=2), encoding="utf-8")
    _stamp_docs(repo, base, base["sha"])
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "re-stamp at head"], cwd=repo, check=True, env=env)
    sha = head_sha()

    # Derive: one variant fed in, everything else derived.
    # The record must anchor at a HEAD whose tree already states the derived
    # figures, so stamp first, commit, then derive at that HEAD. Otherwise the
    # guard's suite-surface ancestor check fires: the stamp commit touches
    # tests/ and would be newer than the recorded sha.
    proc = subprocess.run(
        [sys.executable, str(repo / "scripts/record_suite_figures.py"),
         "--derive-from-record", "--ci-equiv", "3310 / 2 / 2", "--sha", sha],
        cwd=repo, capture_output=True, text=True, env=env,
    )
    record = json.loads(record_path.read_text())
    assert record.get("derived") is True, (
        f"derive did not write a derived record.\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    for key in ("bare", "digest", "ci_equiv", "ci", "python310"):
        assert len(record["current"][key]) == 3, f"{key} is not a triple"

    # Every pre-existing triple is now historical, so the docs do not go stale.
    assert set(map(tuple, record["historical"])) >= set(map(tuple, base["current"].values()))

    # Stamp the docs to the derived figures, commit, then re-derive at that HEAD
    # so the record's sha is the tip whose tree states these figures.
    _stamp_docs(repo, record, sha)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "stamp derived figures"], cwd=repo, check=True, env=env)
    sha = head_sha()
    proc = subprocess.run(
        [sys.executable, str(repo / "scripts/record_suite_figures.py"),
         "--derive-from-record", "--ci-equiv", "3310 / 2 / 2", "--sha", sha],
        cwd=repo, capture_output=True, text=True, env=env,
    )
    record = json.loads(record_path.read_text())
    assert record.get("sha") == sha, (record.get("sha"), sha, proc.stdout, proc.stderr)
    assert record.get("derived") is True
    _stamp_docs(repo, record, sha)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "re-stamp record at head"], cwd=repo, check=True, env=env)
    sha = head_sha()

    # The guard must accept the derived record whose docs were stamped to match.
    proc2 = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_suite_figures.py", "--no-header",
         "--tb=line"],
        cwd=repo, capture_output=True, text=True, env=env,
    )
    assert proc2.returncode == 0, (
        "the guard rejected a derived record whose docs were stamped to match:\n"
        f"{proc2.stdout[-3000:]}"
    )


def test_a_ci_line_disagreeing_with_the_measured_ci_equiv_is_refused(mod):
    """The read figure must agree with the only measured leg.

    `_check_ladder` is what stops a hand-typed `--ci-line` from landing in the
    record as a read figure that contradicts the measured ci_equiv. Dropping the
    check from `derive_record` survived the source branch's seven tests; this is
    the test that makes that mutation red.
    """
    old = {
        "sha": "base0001",
        "ci_run": "42655175550",
        "ci_projected": False,
        "current": {
            "bare": [3193, 20, 2],
            "digest": [3194, 19, 2],
            "ci_equiv": [3290, 2, 2],
            "ci": [3288, 4, 2],
            "python310": [3290, 2, 2],
        },
        "historical": [],
    }
    # ci_equiv measured at +11 passed; the host-pin relation makes CI 3299 / 4 / 2.
    # A ci-line that reads 3288 instead contradicts the measured leg and must be
    # refused rather than recorded as a read figure.
    with pytest.raises(SystemExit, match="host-pin relation"):
        mod.derive_record(old, (3301, 2, 2), "3288 passed, 4 skipped, 2 xfailed", "42669999999")
