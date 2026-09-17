"""Tests for the extractive session digest helper (P1 Slice 2: A1/A2/A5/C1)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "entropicmem" / "scripts"))

from session_digest import (  # noqa: E402
    episode_id_for,
    extract_constraints,
    extractive_digest,
    precompress_episode_id,
)

SAMPLE = [
    {"role": "system", "content": "system prompt noise"},
    {"role": "user", "content": "Help me fix the EntropicMem recall benchmark."},
    {"role": "tool", "content": "TOOL NOISE SHOULD NEVER APPEAR"},
    {"role": "assistant", "content": "The benchmark now prints precision@5."},
    {"role": "user", "content": "Remember: never push to main without CI green."},
    {"role": "assistant", "content": "Understood, I will keep that rule in mind."},
]


def test_digest_shape_and_content():
    d = extractive_digest(SAMPLE)
    assert set(d) == {
        "title", "summary", "fact_candidates",
        "user_text", "assistant_text", "start_ts", "end_ts", "message_count",
    }
    assert d["title"].startswith("Help me fix the EntropicMem recall benchmark")
    assert "User:" in d["summary"] and "Assistant:" in d["summary"]
    assert "TOOL NOISE" not in d["summary"]
    assert "TOOL NOISE" not in d["user_text"]
    assert d["message_count"] == 4
    assert isinstance(d["fact_candidates"], list)
    assert any("never push to main" in c for c in d["fact_candidates"])
    assert d["start_ts"] and d["end_ts"]


def test_digest_empty_and_tool_only_are_noops():
    assert extractive_digest([])["summary"] == ""
    assert extractive_digest(None)["summary"] == ""
    tool_only = [{"role": "tool", "content": "result"}, {"role": "system", "content": "s"}]
    d = extractive_digest(tool_only)
    assert d["summary"] == "" and d["title"] == ""


def test_digest_summary_capped_with_elision():
    msgs = [{"role": "user", "content": "x" * 400} for _ in range(40)]
    d = extractive_digest(msgs, max_chars=500)
    assert len(d["summary"]) <= 500
    assert "…" in d["summary"]


def test_episode_ids_are_deterministic_and_sanitized():
    assert episode_id_for("abc/123") == "ep_sess_abc-123"
    assert episode_id_for("") == "ep_sess_unknown"
    assert precompress_episode_id("abc 123") == "ep_precomp_abc-123"


def test_extract_constraints_finds_markers():
    s = extract_constraints(SAMPLE)
    assert "never push to main" in s
    assert s.startswith("- ")


def test_extract_constraints_empty_when_nothing_salient():
    msgs = [{"role": "user", "content": "What time is the meeting?"}]
    assert extract_constraints(msgs) == ""
