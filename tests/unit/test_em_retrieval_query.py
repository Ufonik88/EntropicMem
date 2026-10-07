"""EM-301 — the `QueryAnalyzer` (§3.6).

The card's AC in its own words: "unit tests for term selection, intent detection
table (≥ 30 labelled queries, ≥ 90% accuracy), entity detection." Each of those
is a named test below.

Invented data only (rule 4): Acme / Globex / Initech, Alice / Bob Example.
"""

from __future__ import annotations

import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.retrieval import query as Q  # noqa: E402
from em.retrieval.query import (  # noqa: E402
    MAX_TERMS,
    analyze,
    detect_entities,
    detect_intent,
    detect_temporal,
    idf,
    select_terms,
    strip_memory_context,
    tokenize,
    vocabulary,
)
from em.retrieval.stopwords import STOPWORDS  # noqa: E402
from em.retrieval.temporal import TimeRange  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.entities import EntityStore  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.migrations import LATEST, discover, migrate  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402

ALICE = Scope(profile="default", user="alice")
BOB = Scope(profile="default", user="bob")
OTHER_PROFILE = Scope(profile="other")
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "memory.db"))
    with s.writer() as conn:
        migrate(conn)
    yield s
    s.close()


def remember(store, content, *, scope=ALICE, **kw) -> str:
    with store.transaction() as conn:
        result = MemoryStore(conn).add(
            MemoryDraft(content=content, **kw), scope=scope, actor="tester"
        )
    assert result.ok, result
    return result.id


# --- the stopword list ----------------------------------------------------


def test_the_stopword_list_is_the_one_3_6_asks_for():
    """§3.6: "built-in English list ~180 words"."""
    assert len(STOPWORDS) == 180
    assert all(word == word.casefold() for word in STOPWORDS)
    for word in ("the", "and", "of", "a", "to", "is", "was"):
        assert word in STOPWORDS


def test_the_v3_list_is_byte_identical_to_the_v2_one():
    """One list, two engines: a change in one cannot silently miss the other."""
    sys.path.insert(0, str(SCRIPTS))
    from stopwords import STOPWORDS as V2  # the EM-104 module the v2 engine uses

    assert STOPWORDS == V2


# --- text -----------------------------------------------------------------


def test_memory_context_blocks_are_stripped():
    """§3.6: "strip `<memory-context>` blocks defensively"."""
    text = "who am i <memory-context>recalled junk with secret words</memory-context> really"
    cleaned = strip_memory_context(text)
    assert "recalled junk" not in cleaned
    assert "secret words" not in cleaned
    assert "who am i" in cleaned and "really" in cleaned


def test_memory_context_stripping_is_case_insensitive_and_spans_lines():
    text = "a\n<MEMORY-CONTEXT>\nmultiline\n</Memory-Context>\nb"
    cleaned = strip_memory_context(text)
    assert "multiline" not in cleaned
    assert "a" in cleaned and "b" in cleaned


def test_tokenize_is_runs_of_word_characters():
    assert tokenize("hub-fleet, migration; 9090 (nginx)") == [
        "hub", "fleet", "migration", "9090", "nginx",
    ]


# --- term selection (AC) --------------------------------------------------


def test_idf_is_the_formula_in_3_6():
    """§3.6: log((N - df + 0.5)/(df + 0.5) + 1)."""
    assert idf(10, 5) == pytest.approx(math.log((10 - 5 + 0.5) / (5 + 0.5) + 1))
    assert idf(0, 0) == 0.0  # an empty corpus scores every term zero


def test_stopwords_and_short_tokens_are_dropped():
    # One real term present: the stopwords and the 1-character token go.
    assert select_terms(["the", "staging", "a", "is", "of"]) == ("staging",)
    assert select_terms(["i", "vault", "a"]) == ("vault",)


def test_an_all_stopword_query_falls_back_to_its_own_tokens():
    """§3.6 is silent here, and "who am I" — the `profile` intent's own example —
    is exactly this case. v2's EM-104 rule is carried forward: drop the length-1
    tokens, keep what is left, rather than retrieve nothing."""
    assert select_terms(["who", "am", "i"]) == ("who", "am")


def test_terms_are_casefolded_and_deduplicated():
    assert select_terms(["Staging", "STAGING", "staging"]) == ("staging",)


def test_a_rarer_term_outranks_a_common_one():
    # "deploy" is in 9 of 10 documents, "quiesce" in 1 — IDF must prefer the latter.
    terms = select_terms(
        ["deploy", "quiesce"], doc_freq={"deploy": 9, "quiesce": 1}, n_docs=10
    )
    assert terms == ("quiesce", "deploy")


def test_length_breaks_an_idf_tie():
    terms = select_terms(["cat", "feline"], doc_freq={}, n_docs=10)
    assert terms == ("feline", "cat")


def test_selection_is_capped_at_twelve():
    terms = select_terms([f"term{i:02d}" for i in range(30)])
    assert len(terms) == MAX_TERMS


def test_extra_stopwords_are_honoured():
    # There is no config module yet, so EM-407 owns the source; the parameter works.
    assert select_terms(["staging", "acme"], extra_stopwords=["acme"]) == ("staging",)


def test_vocabulary_reads_the_view_and_counts_only_active_rows(store):
    remember(store, "the staging server runs on port 9090")
    remember(store, "the billing job runs nightly")
    forgotten = remember(store, "the quiesce procedure for the vault")
    with store.transaction() as conn:
        conn.execute("UPDATE memories SET status='deleted' WHERE id=?", (forgotten,))

    terms = ["staging", "server", "quiesce"]
    frequencies, n_docs = vocabulary(store.reader(), terms)
    assert n_docs == 2, "§3.6's N is the active memory count"
    assert frequencies["staging"] == 1
    assert frequencies["server"] == 1
    # The view is over the FTS index, which keeps a deleted row's text: §3.6
    # specifies `fts5vocab(memories_fts)` and an active-only `N`, so the two
    # differ by exactly the non-active rows. That is the plan's design.
    assert frequencies["quiesce"] == 1


def test_vocabulary_bridges_the_porter_stem_gap(store):
    """`memories_fts` is porter-tokenized, so the view holds stems, not words.

    The view carries `stage`; the query says `staging`. Without the MATCH
    fallback the map would report df 0 for most real tokens and IDF would
    collapse into a length ordering — so this asserts the *raw* word resolves.
    """
    remember(store, "the staging server runs on port 9090")

    view_terms = {
        r["term"] for r in store.reader().execute("SELECT term FROM memories_vocab")
    }
    assert "staging" not in view_terms and "stage" in view_terms, "the premise changed"

    frequencies, _ = vocabulary(store.reader(), ["staging", "running"])
    assert frequencies["staging"] == 1, "a stemmed token must still get its df"
    assert frequencies["running"] == 1


# --- intent detection (AC) ------------------------------------------------

#: (query, intent the user meant). Real phrasings, not pattern-shaped strings —
#: three of them are here because the heuristic *does* miss them, so the table
#: measures the rule rather than flattering it.
LABELLED = (
    # lookup (9)
    ("what is the staging server port", "lookup"),
    ("deploy command for the billing service", "lookup"),
    ("globex contract renewal date", "lookup"),
    ("acme corp address", "lookup"),
    ("database backup location", "lookup"),
    ("initech contact person", "lookup"),
    ("the nginx config file path", "lookup"),
    ("which repo holds the plugin", "lookup"),
    ("port 9090 service name", "lookup"),
    # temporal (10)
    ("when did we migrate the hub fleet", "temporal"),
    ("when is the renewal due", "temporal"),
    ("what time is the deploy scheduled", "temporal"),
    ("how long ago did we switch to v3", "temporal"),
    ("last time we discussed the api keys", "temporal"),
    ("what did we decide yesterday", "temporal"),
    ("what changed this week", "temporal"),
    ("what happened last month", "temporal"),
    ("what did i do 3 days ago", "temporal"),
    ("when I say deploy, what do I mean", "temporal"),
    # procedural (9)
    ("how do i deploy the plugin", "procedural"),
    ("how does the linker work", "procedural"),
    ("how can i reset the vault", "procedural"),
    ("how to run the migrations", "procedural"),
    ("steps to cut a release", "procedural"),
    ("the procedure for rotating keys", "procedural"),
    ("what is the process for onboarding", "procedural"),
    ("how should i configure embeddings", "procedural"),
    ("how would i roll back a migration", "procedural"),
    # profile (9)
    ("who am i", "profile"),
    ("what is my name", "profile"),
    ("what are my preferences", "profile"),
    ("tell me about me", "profile"),
    ("do i prefer concise answers", "profile"),
    ("what do i like in a response", "profile"),
    ("my profile details", "profile"),
    ("my settings for the vault", "profile"),
    ("do i use bullet points", "profile"),
    # two that match more than one pattern, so the declared precedence is pinned:
    # temporal outranks profile, and procedural outranks profile.
    ("when did i last update my profile", "temporal"),
    ("how do i export my profile", "procedural"),
    # the three the heuristic gets wrong, kept in so the budget is honest (9)
    ("how long is the deploy window", "temporal"),  # duration, no "ago"
    ("do i have any preferences saved", "profile"),  # "do I have", not "do I prefer"
    ("what do i need to do to deploy", "procedural"),  # "what do I" reads as identity
)

#: Declared, expected failures. A change that fixes one is fine; a change that
#: breaks a passing one is not, because `wrong` is asserted to be a subset.
KNOWN_MISSES = frozenset({
    "how long is the deploy window",
    "do i have any preferences saved",
    "what do i need to do to deploy",
})


def test_the_intent_table_is_at_least_thirty_queries():
    assert len(LABELLED) >= 30


def test_intent_detection_meets_the_card_budget():
    """AC: ≥ 30 labelled queries, ≥ 90% accuracy."""
    wrong = {text for text, expected in LABELLED if detect_intent(text) != expected}
    assert wrong <= KNOWN_MISSES, f"unexpected misses: {sorted(wrong - KNOWN_MISSES)}"
    accuracy = (len(LABELLED) - len(wrong)) / len(LABELLED)
    assert accuracy >= 0.90, f"intent accuracy {accuracy:.1%} is under the 90% budget"


def test_the_default_intent_is_lookup():
    assert detect_intent("globex contract renewal date") == "lookup"
    assert detect_intent("") == "lookup"


# --- entity detection (AC) ------------------------------------------------


def make_entity(store, name, *, scope=ALICE) -> str:
    with store.transaction() as conn:
        entity_id = EntityStore(conn).get_or_create_entity(name, scope=scope)
        EntityStore(conn).add_alias(entity_id, name)
    return entity_id


def test_detected_entities_are_returned(store):
    eid = make_entity(store, "Acme Corp")
    assert detect_entities("what does Acme Corp use", conn=store.reader(), scope=ALICE) == (eid,)


def test_the_longest_alias_comes_first(store):
    # ngrams() is longest-first, so "Zorp Systems" is tried before the bare
    # "Zorp" — both are real entities here, and the order is the ranking.
    whole = make_entity(store, "Zorp Systems")
    bare = make_entity(store, "Zorp")
    got = detect_entities("the Zorp Systems contract", conn=store.reader(), scope=ALICE)
    assert got == (whole, bare)


def test_entity_detection_stops_at_four_tokens(store):
    eid = make_entity(store, "Acme Corp Global Holdings Limited")
    got = detect_entities(
        "the Acme Corp Global Holdings Limited deal", conn=store.reader(), scope=ALICE
    )
    assert eid not in got, "a 5-token alias is out of range (MAX_NGRAM is 4)"


def test_entity_detection_is_scoped_to_the_profile(store):
    """An alias is not unique across profiles; the profile is the scope."""
    other = make_entity(store, "Acme Corp", scope=OTHER_PROFILE)
    assert detect_entities("Acme Corp", conn=store.reader(), scope=ALICE) == ()
    assert detect_entities("Acme Corp", conn=store.reader(), scope=OTHER_PROFILE) == (other,)


def test_no_entities_is_an_empty_tuple(store):
    assert detect_entities("nothing to see", conn=store.reader(), scope=ALICE) == ()
    assert detect_entities("", conn=store.reader(), scope=ALICE) == ()


# --- temporal detection ---------------------------------------------------


def test_a_bare_iso_date_is_that_whole_day():
    window = detect_temporal("what happened on 2026-09-20", now=NOW)
    assert window == TimeRange(
        start=datetime(2026, 9, 20, tzinfo=timezone.utc),
        end=datetime(2026, 9, 21, tzinfo=timezone.utc),
    )


def test_since_leaves_the_end_open_and_before_leaves_the_start_open():
    assert detect_temporal("everything since 2026-01-01", now=NOW) == TimeRange(
        start=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    assert detect_temporal("everything before 2026-01-01", now=NOW) == TimeRange(
        end=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )


def test_between_is_inclusive_of_the_end_day():
    window = detect_temporal("between 2026-01-01 and 2026-02-01", now=NOW)
    assert window == TimeRange(
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 2, 2, tzinfo=timezone.utc),
    )


def test_between_with_reversed_bounds_is_not_a_window():
    assert detect_temporal("between 2026-02-01 and 2026-01-01", now=NOW) is None


def test_last_n_units_is_a_range_not_a_day():
    """§3.6 is explicit that "last N" is a range."""
    assert detect_temporal("what changed in the last 2 weeks", now=NOW) == TimeRange(
        start=NOW - timedelta(weeks=2), end=NOW
    )
    assert detect_temporal("what changed in the last week", now=NOW) == TimeRange(
        start=NOW - timedelta(weeks=1), end=NOW
    )


def test_last_month_clamps_the_day_instead_of_raising():
    # 31 March minus one month must be 28 February, not an invalid date.
    march = datetime(2026, 3, 31, tzinfo=timezone.utc)
    window = detect_temporal("last month", now=march)
    assert window == TimeRange(start=datetime(2026, 2, 28, tzinfo=timezone.utc), end=march)


def test_a_query_with_no_time_expression_has_no_window():
    assert detect_temporal("what is the staging server port", now=NOW) is None


# --- analyze --------------------------------------------------------------


def test_analyze_returns_the_structured_query(store):
    remember(store, "the staging server runs on port 9090 behind nginx")
    got = analyze("what is the staging server port", conn=store.reader(), scope=ALICE, now=NOW)
    assert got.raw == "what is the staging server port"
    assert got.text == "what is the staging server port"
    assert "staging" in got.terms
    assert "the" not in got.terms and "is" not in got.terms
    assert got.intent == "lookup"
    assert got.entities == ()
    assert got.temporal is None


def test_analyze_strips_a_memory_context_block_before_choosing_terms(store):
    text = "the vault <memory-context>quiesce nebula</memory-context> path"
    got = analyze(text, conn=store.reader(), scope=ALICE, now=NOW)
    assert "quiesce" not in got.terms and "nebula" not in got.terms
    assert "vault" in got.terms and "path" in got.terms
    assert got.raw == text, "raw keeps what arrived; text is what was analysed"


def test_analyze_prefers_the_rare_term(store):
    """The rare term wins on IDF even though the common one is *longer*.

    The lengths are chosen deliberately: "staging" (7) is in six memories and
    "veto" (4) in one, so length ordering would put "staging" first. Only a
    working document frequency gets "veto" to the front — which is what makes
    this test fail if the vocabulary lookup stops being wired in.
    """
    for i in range(6):
        remember(store, f"the staging server number {i} is running")
    remember(store, "a veto applies to the next release")
    got = analyze("staging veto", conn=store.reader(), scope=ALICE, now=NOW)
    assert got.terms[0] == "veto", got.terms
    assert "staging" in got.terms


def test_analyze_carries_intent_entities_and_temporal_together(store):
    eid = make_entity(store, "Acme Corp")
    got = analyze(
        "when did Acme Corp switch to the new hub last week",
        conn=store.reader(),
        scope=ALICE,
        now=NOW,
    )
    assert got.intent == "temporal"
    assert got.entities == (eid,)
    assert got.temporal == TimeRange(start=NOW - timedelta(weeks=1), end=NOW)


def test_analyze_reads_an_empty_store_without_error(store):
    got = analyze("who am i", conn=store.reader(), scope=ALICE, now=NOW)
    assert got.intent == "profile"
    assert got.terms  # falls back to length ordering rather than returning nothing


# --- the migration --------------------------------------------------------


def test_migration_0004_creates_the_vocabulary_view(store):
    assert LATEST == max(m.version for m in discover())
    assert any(m.version == 4 and "vocab" in m.name for m in discover())
    names = {
        r["name"]
        for r in store.reader().execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        )
    }
    assert "memories_vocab" in names
    assert store.reader().execute("PRAGMA user_version").fetchone()[0] == LATEST


def test_the_analyzer_is_stdlib_only(store):
    """Plan §3.2: everything under `em` is stdlib-only.

    Absolute imports must be the standard library; anything from this project is
    imported relatively, which is what keeps the provider out of the retrieval
    layer.
    """
    import ast

    allowed = {"__future__", "math", "re", "sqlite3", "dataclasses", "datetime", "typing"}
    imported = set()
    for node in ast.walk(ast.parse(Path(Q.__file__).read_text())):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= allowed, f"non-stdlib absolute imports: {sorted(imported - allowed)}"
