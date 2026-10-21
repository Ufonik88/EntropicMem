"""EM-607 — ingest v2.

The card (§6.5) replaces the v2 ingest path, which turned every capitalised
phrase in a document into a vault note. What it asks for:

* HTML to text through ``html.parser``, dropping ``script``/``style``/``nav``/
  ``footer`` and keeping headings and lists;
* a size cap;
* **one** chunked literature note under ``Sources/``;
* entity mentions linked through ``EntityLinker``, so a mention is a link and
  never a note;
* optional LLM key points in the plan's Appendix C.6 shape when a backend is
  available, and a deterministic scan when it is not;
* extracted claims as **`pending`** memories with ``source=ingest`` and the
  source URL as evidence.

**AC:** a 50 KB article makes 1 source note, at most 10 pending memories, and 0
junk entity notes.

Invented data only: Acme, Globex, Initech, Alice and Bob Example, example.com.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
CLI = SCRIPTS / "entropicmem.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.facade.engine import V3Engine  # noqa: E402
from em.ingest.article import (  # noqa: E402
    INGEST_SOURCE,
    MAX_CLAIMS,
    MAX_SOURCE_BYTES,
    MAX_TEXT_CHARS,
    SOURCES_FOLDER,
    SourceTooLarge,
    build_note,
    cap_text,
    check_source_size,
    chunk_text,
    key_points,
    prepare,
    queue_claims,
)
from em.ingest.html_text import html_to_text  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.entities import EntityStore  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import Scope  # noqa: E402
from em_internal.policy import evaluate_write  # noqa: E402

OWNER = Scope(profile="default")

HTML_PAGE = """<!doctype html>
<html><head><title>Acme on Storage</title>
<style>.chart { display: none; }</style>
<script>var s = "<p>script text</p>";</script>
</head>
<body>
<nav><a href="/">Home</a> <a href="/docs">Docs</a></nav>
<h1>Acme Storage Notes</h1>
<p>Acme Corporation moved its primary datastore to Globex Cloud in March 2026.</p>
<ul>
  <li>Globex Cloud keeps three replicas in every region.</li>
  <li>The Initech connector is scheduled for removal.</li>
</ul>
<h2>Costs &amp; budgets</h2>
<p>Acme estimates the annual bill at 42,000 dollars, well below the 61,000 dollars of the year before.</p>
<footer>Copyright Acme</footer>
</body></html>
"""


@pytest.fixture
def db(tmp_path):
    saved = Store(str(tmp_path / "memory.db"))
    with saved.writer() as conn:
        migrate(conn)
    yield str(tmp_path / "memory.db")
    saved.close()


@pytest.fixture
def engine(db):
    engine = V3Engine(db)
    yield engine
    engine.close()


def _pending(path: str) -> list[dict]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM memories WHERE status='pending' ORDER BY created_at"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _entities(path: str) -> list[dict]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM entities")]
    finally:
        conn.close()


def _links(path: str) -> list[dict]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM memory_entities")]
    finally:
        conn.close()


# --- HTML to text -----------------------------------------------------------


def test_the_four_chrome_elements_are_dropped():
    """``script``, ``style``, ``nav`` and ``footer`` never reach the note."""
    parsed = html_to_text(HTML_PAGE)
    for chrome in ("script text", "display: none", "Home", "Docs", "Copyright Acme"):
        assert chrome not in parsed.text, f"{chrome!r} survived the parse"


def test_headings_and_lists_survive_as_structure():
    text = html_to_text(HTML_PAGE).text
    assert "# Acme Storage Notes" in text
    assert "## Costs & budgets" in text
    assert "- Globex Cloud keeps three replicas in every region." in text
    assert "- The Initech connector is scheduled for removal." in text


def test_charrefs_are_decoded_and_whitespace_collapsed():
    parsed = html_to_text("<p>Acme &amp; Globex</p><p>a\n   b\t c</p>")
    assert "Acme & Globex" in parsed.text
    assert "a b c" in parsed.text


def test_malformed_html_is_parsed_rather_than_crashing():
    """Unclosed tags are the web's normal case; an unclosed script is dropped."""
    parsed = html_to_text("<h2>Broken<p>text<p>more<script>var x = 1;")
    assert "Broken" in parsed.text
    assert "text" in parsed.text
    assert "more" in parsed.text
    assert "var x" not in parsed.text


def test_the_title_comes_from_the_page_then_the_caller_then_the_url():
    assert html_to_text(HTML_PAGE).title == "Acme on Storage"
    page = prepare(HTML_PAGE, is_html=True)
    assert page.title == "Acme on Storage"
    named = prepare(HTML_PAGE, is_html=True, title="Chosen Name")
    assert named.title == "Chosen Name"
    from_url = prepare("<html><body><p>x</p></body></html>", url="https://example.com/posts/storage", is_html=True)
    assert from_url.title == "storage"


def test_plain_text_is_not_run_through_the_parser():
    """A Markdown article quoting a tag is text, not HTML."""
    source = prepare("Use `<div>` for a block.\n\nSecond paragraph here.", is_html=False)
    assert "<div>" in source.text


# --- the caps ---------------------------------------------------------------


def test_the_byte_cap_refuses_a_large_source():
    with pytest.raises(SourceTooLarge) as excinfo:
        check_source_size("x" * (MAX_SOURCE_BYTES + 1))
    assert f"{MAX_SOURCE_BYTES:,}-byte" in str(excinfo.value)


def test_the_text_cap_truncates_at_a_boundary_and_is_recorded_in_the_note():
    text = "\n\n".join(f"Paragraph {i} " + "word " * 40 for i in range(MAX_TEXT_CHARS // 200))
    kept, cut = cap_text(text)
    assert cut and len(kept) <= MAX_TEXT_CHARS
    assert not kept.endswith("wor")  # cut on a boundary, not mid-word
    source = prepare(text)
    assert source.truncated
    _, body = build_note(source, key_points(source.text))
    assert "**Truncated:**" in body
    assert f"{len(source.text):,} of {source.original_chars:,} characters" in body


def test_a_source_at_the_cap_is_kept_whole():
    text = "A paragraph that is well under the cap and therefore kept in full."
    source = prepare(text)
    assert not source.truncated
    assert source.original_chars == len(text)


# --- chunking ---------------------------------------------------------------


def test_chunking_preserves_every_paragraph_in_order():
    text = "\n\n".join(f"Paragraph number {i} carries its own sentence." for i in range(40))
    chunks = chunk_text(text, size=300)
    assert len(chunks) > 1
    assert all(len(chunk) <= 300 for chunk in chunks)
    joined = "\n\n".join(chunks)
    assert joined == text  # every paragraph survived, once, in order


def test_one_oversized_paragraph_is_split_not_dropped():
    paragraph = " ".join(f"word{i}" for i in range(400))
    chunks = chunk_text(paragraph, size=200)
    assert len(chunks) > 1
    assert " ".join(chunks).split() == paragraph.split()


def test_empty_text_chunks_to_nothing():
    assert chunk_text("   \n\n  ") == ()


# --- key points and claims --------------------------------------------------


def test_the_deterministic_scan_is_bounded_deduplicated_and_claim_shaped():
    sentences = [
        f"Sentence {i} states a fact about storage capacity and its cost over time." for i in range(30)
    ]
    points = key_points(" ".join(sentences))
    assert 0 < len(points.claims) <= MAX_CLAIMS
    assert points.points == points.claims
    assert len(set(points.claims)) == len(points.claims)
    assert all(40 <= len(claim) <= 300 for claim in points.claims)
    assert not points.from_llm


def test_a_question_is_not_proposed_as_a_claim():
    text = (
        "Why does the storage tier keep moving between regions every single quarter? "
        "The storage tier moved between regions three times in the last year alone."
    )
    points = key_points(text)
    assert all(not claim.endswith("?") for claim in points.claims)
    assert any("moved between regions" in claim for claim in points.claims)


class _FakeLLM:
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def complete_json(self, **kwargs):
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def test_an_llm_reply_supplies_points_and_claims():
    text = "Acme Corporation moved its datastore to Globex Cloud in March 2026."
    reply = {
        "key_points": ["Acme moved to Globex Cloud."],
        "claims": [{"content": "Acme moved its datastore in March 2026.", "evidence_quote": "Acme Corporation moved"}],
    }
    points = key_points(text, llm=_FakeLLM(reply))
    assert points.from_llm
    assert points.points == ("Acme moved to Globex Cloud.",)
    assert points.claims == ("Acme moved its datastore in March 2026.",)


def test_a_fabricated_evidence_quote_drops_the_claim():
    text = "Acme Corporation moved its datastore to Globex Cloud in March 2026."
    reply = {
        "key_points": ["A point."],
        "claims": [{"content": "Acme bought Initech.", "evidence_quote": "Acme bought Initech today."}],
    }
    points = key_points(text, llm=_FakeLLM(reply))
    assert "Acme bought Initech." not in points.claims
    assert points.claims  # fell back to the sentence scan rather than nothing


@pytest.mark.parametrize("failure", [RuntimeError("backend down"), None, {"key_points": [], "claims": []}])
def test_an_unusable_llm_reply_falls_back_to_the_scan(failure):
    text = "The storage tier moved between regions three times in the last year alone."
    points = key_points(text, llm=_FakeLLM(failure))
    assert not points.from_llm
    assert points.claims == points.points
    assert points.claims


# --- the store half ---------------------------------------------------------


def test_the_write_policy_quarantines_ingest():
    """A fetched article is third-party text: it is proposed, never stored live."""
    action, reason = evaluate_write("Acme Corporation moved to Globex Cloud.", source=INGEST_SOURCE)
    assert (action, reason) == ("quarantine", "ingest_requires_review")


def test_claims_land_pending_with_the_url_as_evidence(engine, db):
    source_url = "https://example.com/posts/storage"
    claims = [
        "Acme Corporation moved its primary datastore to Globex Cloud in March 2026.",
        "Globex Cloud keeps three replicas in every region it serves today.",
    ]
    report = queue_claims(engine, claims, url=source_url, domain="Knowledge")
    assert len(report.pending_ids) == 2
    rows = _pending(db)
    assert [row["content"] for row in rows] == claims
    for row in rows:
        assert row["source"] == "ingest"
        assert row["status"] == "pending"
        assert row["evidence"] == source_url
        assert row["pending_reason"] == "ingest_requires_review"


def test_an_empty_claim_is_skipped_not_fatal(engine):
    report = queue_claims(engine, ["", "   ", "A real claim about Globex Cloud and its regions today."])
    assert len(report.pending_ids) == 1
    assert len(report.skipped) == 2


def test_a_known_entity_is_linked_and_creates_no_note(engine, db):
    with engine.store.transaction() as conn:
        entity_id = EntityStore(conn).get_or_create_entity("Globex Cloud", scope=OWNER, kind="product")
    report = queue_claims(
        engine,
        ["Globex Cloud keeps three replicas in every region it serves across the world today."],
        url="https://example.com/posts/storage",
    )
    assert report.entities == ["Globex Cloud"]
    links = _links(db)
    assert [link["entity_id"] for link in links] == [entity_id]
    assert [entity["name"] for entity in _entities(db)] == ["Globex Cloud"]


def test_one_article_cannot_mint_an_entity_from_a_single_mention(engine, db):
    """The linker's two-sighting rule is what keeps the graph clean."""
    report = queue_claims(
        engine,
        ["Initech shipped a connector for Globex Cloud that nobody asked for last year at all."],
        url="https://example.com/posts/storage",
    )
    assert len(report.pending_ids) == 1
    assert report.entities == []
    assert _entities(db) == []


# --- the note ---------------------------------------------------------------


def test_build_note_is_one_chunked_document_under_sources():
    source = prepare(HTML_PAGE, is_html=True, url="https://example.com/acme")
    title, body = build_note(source, key_points(source.text), entities=["Globex Cloud"])
    assert title == "Source - Acme on Storage"
    assert "**Source:** https://example.com/acme" in body
    assert "## Key Points" in body
    assert body.count("## Chunk ") == len(source.chunks)
    assert "## Entities" in body
    # A wikilink here would resurrect the v2 bug: every mention became a note.
    assert "[[" not in body


def test_the_note_says_when_a_model_supplied_the_points():
    source = prepare("Acme Corporation moved its datastore to Globex Cloud in March 2026.")
    reply = {"key_points": ["Acme moved."], "claims": []}
    _, body = build_note(source, key_points(source.text, llm=_FakeLLM(reply)))
    assert "configured LLM" in body


# --- the CLI, and the card's AC ---------------------------------------------


def _run(*args, **env):
    """Run the CLI with a clean ``ENTROPICMEM_*`` environment plus *env*."""
    full = {key: value for key, value in os.environ.items() if not key.startswith("ENTROPICMEM_")}
    full.update(env)
    return subprocess.run(
        [sys.executable, str(CLI), *args], capture_output=True, text=True, env=full, timeout=180
    )


def _v3_store(path: Path) -> None:
    saved = Store(str(path))
    with saved.writer() as conn:
        migrate(conn)
    saved.close()


def _article(chars: int) -> str:
    """A ~*chars* HTML article with no repeated capitalised phrase.

    Every sentence opens with one capitalised word (a sentence-opener, which the
    entity proposer strips) and no mid-sentence capitalised run ever repeats, so
    the fixture can only mint an entity if the card's promise is broken.
    """
    openers = ["The", "Capacity", "Latency", "Storage", "Retrieval", "Indexing", "Compaction", "Writes"]
    paragraphs: list[str] = []
    index = 0
    while sum(len(paragraph) for paragraph in paragraphs) < chars:
        sentences = []
        for _ in range(4):
            opener = openers[index % len(openers)]
            sentences.append(
                f"{opener} sample paragraph {index} records that storage latency held steady "
                f"while writes and reads moved through the same queue during the window."
            )
            index += 1
        paragraphs.append("<p>" + " ".join(sentences) + "</p>")
    return "<html><head><title>Long Storage Report</title></head><body>" + "".join(paragraphs) + "</body></html>"


def test_the_50kb_article_ac_one_note_ten_pending_zero_junk_entity_notes(tmp_path):
    vault = tmp_path / "vault"
    index_db = tmp_path / "index.db"
    memory_db = tmp_path / "memory.db"
    env = {
        "ENTROPICMEM_VAULT_PATH": str(vault),
        "ENTROPICMEM_INDEX_DB": str(index_db),
        "ENTROPICMEM_MEMORY_DB": str(memory_db),
    }
    init = _run("init", "--vault", str(vault), "--index-db", str(index_db), **env)
    assert init.returncode == 0, init.stderr
    _v3_store(memory_db)
    before = {path for path in vault.rglob("*.md")}

    article = tmp_path / "article.html"
    article.write_text(_article(50_000), encoding="utf-8")
    assert article.stat().st_size >= 50_000
    result = _run("ingest", str(article), "--no-llm", **env)
    assert result.returncode == 0, result.stderr

    after = {path for path in vault.rglob("*.md")}
    created = sorted(after - before)
    assert len(created) == 1, created
    assert created[0].parent.name == SOURCES_FOLDER
    assert created[0].stem == "Source - Long Storage Report"

    pending = _pending(str(memory_db))
    assert 0 < len(pending) <= MAX_CLAIMS
    assert all(row["source"] == INGEST_SOURCE for row in pending)
    assert all(row["status"] == "pending" for row in pending)
    assert all(row["evidence"] == str(article) for row in pending)

    # The card's "0 junk entity notes": no entity row from a single article,
    # and no note per capitalised phrase.
    assert _entities(str(memory_db)) == []
    assert all("Sources" in str(path) for path in created)

    assert "1 source note" in result.stdout
    assert f"{len(pending)} pending memories" in result.stdout
    assert "0 entity links" in result.stdout


def test_ingest_queues_pending_on_a_v2_store_too(tmp_path):
    """The owner's live store is v2 today; the claim half must not be v3-only."""
    vault = tmp_path / "vault"
    index_db = tmp_path / "index.db"
    memory_db = tmp_path / "memory.db"
    env = {
        "ENTROPICMEM_VAULT_PATH": str(vault),
        "ENTROPICMEM_INDEX_DB": str(index_db),
        "ENTROPICMEM_MEMORY_DB": str(memory_db),
    }
    assert _run("init", "--vault", str(vault), "--index-db", str(index_db), **env).returncode == 0
    from memory_engine import MemoryEngine  # v2 engine: it creates the v2 schema

    MemoryEngine(memory_db).close()

    doc = tmp_path / "doc.md"
    doc.write_text(
        "Acme Corporation moved its primary datastore to Globex Cloud in March 2026, "
        "and the migration took four weeks of careful planning.",
        encoding="utf-8",
    )
    result = _run("ingest", str(doc), "--no-llm", **env)
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(memory_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = [
            dict(row)
            for row in conn.execute("SELECT source, reason, content FROM pending_facts")
        ]
    finally:
        conn.close()
    assert rows
    assert all(row["source"] == INGEST_SOURCE for row in rows)
    assert all(row["reason"] == "ingest_requires_review" for row in rows)


def test_ingest_never_creates_a_memory_store(tmp_path):
    """A one-shot CLI read must not bootstrap a live-store database."""
    vault = tmp_path / "vault"
    memory_db = tmp_path / "does-not-exist" / "memory.db"
    env = {
        "ENTROPICMEM_VAULT_PATH": str(vault),
        "ENTROPICMEM_INDEX_DB": str(tmp_path / "index.db"),
        "ENTROPICMEM_MEMORY_DB": str(memory_db),
    }
    init = _run("init", "--vault", str(vault), "--index-db", str(tmp_path / "index.db"), **env)
    assert init.returncode == 0, init.stderr

    doc = tmp_path / "note.md"
    doc.write_text("A short document about storage tiers and the people who move them around.", encoding="utf-8")
    result = _run("ingest", str(doc), "--no-llm", **env)
    assert result.returncode == 0, result.stderr
    assert "source note only" in result.stdout
    assert not memory_db.exists()
    assert len(list((vault / SOURCES_FOLDER).glob("*.md"))) == 1


def test_ingest_refuses_an_oversized_file(tmp_path):
    vault = tmp_path / "vault"
    env = {
        "ENTROPICMEM_VAULT_PATH": str(vault),
        "ENTROPICMEM_INDEX_DB": str(tmp_path / "index.db"),
        "ENTROPICMEM_MEMORY_DB": str(tmp_path / "memory.db"),
    }
    _run("init", "--vault", str(vault), "--index-db", str(tmp_path / "index.db"), **env)
    big = tmp_path / "big.html"
    big.write_text("<p>" + "x" * (MAX_SOURCE_BYTES + 10) + "</p>", encoding="utf-8")
    result = _run("ingest", str(big), "--no-llm", **env)
    assert result.returncode == 1
    assert "ingest cap" in result.stderr
    assert not (vault / SOURCES_FOLDER).exists()
