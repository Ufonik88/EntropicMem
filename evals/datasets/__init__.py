"""Scenario dataset files for the eval suites (EM-001).

Suites (plan §EM-001):
  ci    — fast, deterministic, stdlib-only, no network/ML; gate-relevant.
  full  — adds vector-backend scenarios when an accelerator is installed.
  external — reserved for EM-006 (LiveMem etc.), not shipped as data here.

Datasets are JSONL; blank lines and `#` comment lines are ignored. All
personas are synthetic (public-repo rule §0.1).
"""
from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).resolve().parent


def ci_suite_path() -> Path:
    return _HERE / "ci.jsonl"


def full_suite_path() -> Path:
    return _HERE / "full.jsonl"


def hard_suite_paths():
    """The 12-category hard scenario suite (EM-002)."""
    return sorted((_HERE.parent / "datasets_hard").glob("*.jsonl"))


def suite_paths(name: str):
    """Scenario files belonging to a suite name."""
    if name == "ci":
        return [ci_suite_path()]
    if name == "full":
        return [ci_suite_path(), full_suite_path()]
    if name == "hard":
        return hard_suite_paths()
    if name == "external":
        return []  # EM-006 will register external datasets here
    raise ValueError(f"unknown suite: {name!r} (choose ci|full|hard|external)")
