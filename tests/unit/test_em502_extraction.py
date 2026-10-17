"""EM-502 slice 1 — the extraction rule path, segmentation and the evidence guard.

The card's acceptance criterion is here: the rule path must hold **precision
≥ 0.8** on ``evals/datasets/extraction.jsonl`` (≥ 40 synthetic transcripts with
gold memories). The LLM path's F1 is *reported*, not gated — it needs a
reference model — so it is exercised with a deterministic stub and its metric is
computed but not asserted against a threshold.

Invented data only (rule 4); the dataset uses Alice/Bob Example, Acme/Globex/
Initech, and synthetic places.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
for _entry in (str(REPO), str(SCRIPTS)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from em.formation.extract import (  # noqa: E402
    MAX_SEGMENT_CHARS,
    Turn,
    build_transcript,
    extract_rules,
    extract_window,
    extract_with_llm,
    segment_turns,
    validate_candidates,
)
from em.formation.rules import Candidate, extract_candidates  # noqa: E402

DATASET = REPO / "evals" / "datasets" / "extraction.jsonl"


class StubLLM:
    """A deterministic stand-in for the EM-501 seam."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.reply


def _load():
    rows = []
    for line in DATASET.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


def _turns(row):
    return [
        Turn(role=t["role"], text=t["text"], author_id=t.get("author", ""), turn=t.get("turn", -1))
        for t in row["turns"]
    ]


def _matches(candidate, gold):
    text = candidate.content.casefold()
    return any(g["contains"].casefold() in text for g in gold)


def _precision(rows):
    tp = total = 0
    for row in rows:
        for candidate in extract_rules(_turns(row)):
            total += 1
            if _matches(candidate, row.get("gold", [])):
                tp += 1
    return tp, total


def test_the_dataset_has_at_least_forty_transcripts():
    assert len(_load()) >= 40


def test_the_rule_path_meets_the_precision_gate():
    """**The card's CI-gated AC.** A pattern that over-extracts (matches talk
    that states no memory) drops this below 0.8 and fails the build."""
    rows = _load()
    tp, total = _precision(rows)
    assert total > 0, "the rule path extracted nothing — the patterns are broken"
    precision = tp / total
    assert precision >= 0.8, (
        f"rule-path precision {precision:.2f} ({tp}/{total}) is below the 0.8 AC"
    )


def test_the_rule_path_finds_the_gold_facts():
    """Precision alone is satisfiable by extracting nothing; recall is the sanity
    bound that keeps the gate honest (it is deliberately loose — a few gold facts
    are assistant suggestions the model path owns)."""
    rows = _load()
    gold_total = sum(len(row.get("gold", [])) for row in rows)
    found = 0
    for row in rows:
        candidates = extract_rules(_turns(row))
        for gold in row.get("gold", []):
            if any(gold["contains"].casefold() in c.content.casefold() for c in candidates):
                found += 1
    assert gold_total > 40
    assert found / gold_total >= 0.8, f"recall {found}/{gold_total} is implausibly low"


def test_every_evidence_quote_is_a_verbatim_substring():
    for row in _load():
        transcript = build_transcript(_turns(row))
        for candidate in extract_rules(_turns(row)):
            assert candidate.evidence_quote in transcript, (
                f"candidate quote is not verbatim: {candidate.evidence_quote!r}"
            )


def test_a_correction_and_a_commitment_are_extracted():
    correction = extract_candidates("Actually, the port is 7070 now.")
    assert any(c.kind == "fact" and "7070" in c.content for c in correction)
    commitment = extract_candidates("I'll send the report by Friday.")
    assert any(c.kind == "event" and "by Friday" in c.content for c in commitment)
    procedure = extract_candidates("First, clone the repo; then run the make target.")
    assert any(c.kind == "procedure" for c in procedure)


def test_an_assistant_claim_is_capped_at_half_confidence():
    candidates = extract_candidates(
        "I use info-level logging for the worker.", speaker="assistant", source_turn=3
    )
    assert candidates, "the assistant statement should still be extracted"
    assert all(c.confidence <= 0.6 for c in candidates)
    assert all(c.speaker == "assistant" and c.source_turn == 3 for c in candidates)


def test_segmentation_is_bounded_and_overlaps_one_turn():
    turns = [Turn(role="user", text=f"Turn {i} " + ("x" * 400), turn=i) for i in range(40)]
    segments = segment_turns(turns)
    assert len(segments) > 1, "the fixture must actually overflow one segment"
    for segment in segments:
        assert len(build_transcript(segment)) <= MAX_SEGMENT_CHARS
    for previous, following in zip(segments, segments[1:]):
        assert following[0] == previous[-1], "the head of a segment must repeat the prior turn"


def test_a_fabricated_llm_quote_is_rejected_and_a_real_one_kept():
    turns = [Turn(role="user", text="The staging port is 9090.", turn=1)]
    transcript = build_transcript(turns)

    fabricated = Candidate(
        kind="fact", content="the port is 7070", evidence_quote="the port is 7070"
    )
    assert validate_candidates([fabricated], transcript=transcript) == []

    real = Candidate(kind="fact", content="The staging port is 9090.", evidence_quote="The staging port is 9090.")
    assert validate_candidates([real], transcript=transcript) == [real]

    # and through the full window path
    llm = StubLLM(
        {"memories": [
            {"kind": "fact", "content": "port 7070", "confidence": 0.5,
             "evidence_quote": "port 7070", "speaker": "user"},
        ]}
    )
    assert [c for c in extract_window(turns, llm=llm) if c.kind == "fact"] == []


def test_a_malformed_llm_reply_is_fail_soft():
    turns = [Turn(role="user", text="My timezone is Europe/Johannesburg.", turn=1)]
    for reply in (None, {}, {"memories": "not a list"}, {"memories": [{"kind": "bogus"}]}):
        candidates = extract_with_llm(turns, StubLLM(reply))
        assert candidates == []
    # the rule path still ran through the window call
    assert any(c.kind == "profile" for c in extract_window(turns, llm=StubLLM(None)))


def test_the_model_path_carries_appendix_c1_shape():
    turns = [Turn(role="user", text="I prefer dark mode.", turn=4, author_id="u-alice")]
    llm = StubLLM(
        {"memories": [
            {"kind": "preference", "content": "Prefers dark mode", "confidence": 0.9,
             "evidence_quote": "I prefer dark mode", "speaker": "user", "source_turn": 4},
        ]}
    )
    out = extract_window(turns, llm=llm)
    assert any(c.content == "Prefers dark mode" for c in out)
    call = llm.calls[0]
    assert call["task"] == "extract"
    assert "<transcript>" in call["user"] and "</transcript>" in call["user"]
    assert "untrusted" not in call["system"].lower()  # C.1 states the rule in its own words
    assert "MUST be copied verbatim" in call["system"]
    assert call["schema"]["required"] == ["memories"]


def test_the_llm_f1_harness_is_measured_not_gated():
    """Appendix C.1's F1 is *reported* (it needs a reference model). The harness
    computes it; the number is not asserted, so CI does not depend on a model."""
    rows = _load()
    tp = fp = fn = 0
    for row in rows:
        turns = _turns(row)
        gold = row.get("gold", [])
        # A perfect-recall stub: the harness's job is to measure, not to extract.
        reply = {"memories": [
            {"kind": g["kind"], "content": g["contains"], "confidence": 0.8,
             "evidence_quote": g["contains"], "speaker": "user", "source_turn": 1}
            for g in gold
        ]}
        for candidate in extract_with_llm(turns, StubLLM(reply)):
            if _matches(candidate, gold):
                tp += 1
            else:
                fp += 1
        fn += len(gold)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / fn if fn else 0.0
    assert 0.0 <= precision <= 1.0 and 0.0 <= recall <= 1.0
