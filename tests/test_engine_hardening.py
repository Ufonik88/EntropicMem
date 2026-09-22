"""Regression tests for the EntropicMem engine hardening pass.

One test module per behavior fix:
  (1)  reentrant write lock + try/finally leak fixes (remember/reinforce/
       forget/consolidate/migrate nested _backup/_init_schema)
  (2)  recall_for_agent / recall_related repaired (self.db + audit() +
       subject/predicate/object triples) and wired into the CLI
  (3)  `entropicmem consolidate --confirm` pass-through + dry-run hint
  (4)  unified graph_edges link graph (no legacy `links` table anywhere)
  (5)  one shared build_fts_query() (OR-of-capped-tokens, metacharacter-safe)
       + match_error reason token + recall()/recall_with_relevance() parity
  (6)  LIKE wildcard escaping (%/_ literal) + search_fts path comes from JOIN
  (7)  vectorized vector_search with a per-db cached decode matrix (parity
       with the pure-Python fallback, cache invalidation, cache isolation)
  (8)  narrowed excepts: swallowed FTS failures log a warning
  (9)  extract_and_store docstring states quarantine semantics
  (10) validate_entropic_id / validate_url wired into cmd_* entry points,
       _stub deleted, stale 'stub for Phase 3-4' comment gone
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

import embeddings
import memory_engine as me
from graph_query import (
    get_connected_notes,
    get_incoming_links,
    get_outgoing_links,
    init_graph_schema,
    init_links_schema,
    store_links,
)
from index import VaultIndex
from index import build_fts_query as index_build_fts_query
from memory_engine import (
    FTS_REASON_MATCH_ERROR,
    FTS_REASON_OK,
    MAX_FTS_TERMS,
    MemoryEngine,
    build_fts_query,
    escape_like,
    run_fts_match,
)
from vault import Vault

_ROOT = Path(__file__).resolve().parent.parent
_CLI = str(_ROOT / "plugins" / "entropicmem" / "scripts" / "entropicmem.py")


def _run(*args, **env):
    return subprocess.run(
        [sys.executable, _CLI, *args],
        capture_output=True,
        text=True,
        env={**os.environ, **env},
    )


@pytest.fixture
def engine(tmp_path):
    eng = MemoryEngine(tmp_path / "memory.db")
    yield eng
    eng.close()


# ── (1) write lock: reentrancy + no leaked holds ─────────────────────────────

class TestWriteLock:
    def test_lock_is_reentrant_counter(self, engine):
        engine._acquire_write_lock()
        assert engine._write_locked and engine._lock_depth == 1
        engine._acquire_write_lock()
        assert engine._lock_depth == 2  # nested acquire must not re-flock
        engine._release_write_lock()
        assert engine._write_locked and engine._lock_depth == 1  # still held
        engine._release_write_lock()
        assert not engine._write_locked and engine._lock_depth == 0

    def test_remember_balances_lock_on_success(self, engine):
        engine.remember("balanced lock fact", domain="Testing")
        assert not engine._write_locked and engine._lock_depth == 0

    def test_remember_exception_releases_lock(self, engine, monkeypatch):
        def boom(content, max_len=80):
            raise RuntimeError("synthetic failure inside the locked section")

        monkeypatch.setattr(me.StoredFact, "make_id", staticmethod(boom))
        with pytest.raises(RuntimeError):
            engine.remember("this remember blows up", domain="Testing")
        assert not engine._write_locked and engine._lock_depth == 0
        monkeypatch.undo()
        # the lock is free again: later writers get through
        eid = engine.remember("later writer gets through", domain="Testing")
        assert eid

    def test_reinforce_missing_releases_lock(self, engine):
        assert engine.reinforce("deadbeefdeadbeef") is False
        assert not engine._write_locked and engine._lock_depth == 0

    def test_nested_backup_keeps_outer_lock(self, engine):
        engine._acquire_write_lock()
        engine._backup()  # nested acquire/release must not drop the outer hold
        assert engine._write_locked and engine._lock_depth == 1
        engine._release_write_lock()
        assert engine._lock_depth == 0

    def test_forget_keeps_lock_through_nested_backup(self, engine):
        eid = engine.remember("fact to forget under lock", domain="Testing")
        engine._acquire_write_lock()
        assert engine.forget(eid, confirm=True) is True
        assert engine._write_locked and engine._lock_depth == 1
        engine._release_write_lock()
        assert engine._lock_depth == 0

    def test_migrate_keeps_lock_through_nested_init_schema(self, engine):
        engine._acquire_write_lock()
        engine.migrate()
        assert engine._write_locked and engine._lock_depth == 1
        engine._release_write_lock()
        assert engine._lock_depth == 0

    def test_consolidate_mutates_under_lock(self, engine, monkeypatch):
        engine.remember("ancient low value fact", domain="Testing")
        depths = []
        orig_backup = engine._backup

        def spy_backup():
            depths.append(engine._lock_depth)
            return orig_backup()

        monkeypatch.setattr(engine, "_backup", spy_backup)
        result = engine.consolidate(
            max_age_days=0, min_access_count=0, dry_run=False, confirm=True,
        )
        assert result["archived"] == 1
        assert depths and depths[0] >= 1  # mutation phase ran under the write lock
        assert not engine._write_locked and engine._lock_depth == 0

    def test_close_releases_leaked_hold(self, tmp_path):
        eng = MemoryEngine(tmp_path / "m2.db")
        eng._acquire_write_lock()
        eng._acquire_write_lock()  # leaked double hold
        eng.close()
        eng2 = MemoryEngine(tmp_path / "m2.db")
        assert eng2.remember("after close works", domain="Testing")
        eng2.close()


# ── (2) recall_for_agent / recall_related fixed + CLI wiring ─────────────────

class TestSprintARecallTools:
    def test_recall_for_agent_returns_reflection_and_audits(self, engine):
        eid = engine.remember(
            "Deploy scripts live in the ops repo",
            title="Deploy", domain="DevOps", tags=["ops"],
        )
        out = engine.recall_for_agent("deploy", top_k=5)
        assert set(out) == {"facts", "reflect_summary", "source_ids"}
        assert out["source_ids"] == [eid]
        assert "Reflect on 1 recalled facts" in out["reflect_summary"]
        # the reflection is audited via audit() -> audit_log table (no
        # AttributeError from the old self.audit_log reference)
        actions = [r["action"] for r in engine.list_audit(limit=20)]
        assert "reflect" in actions

    def test_recall_related_walks_triples_columns(self, engine):
        seed = engine.remember(
            "Event venue booking confirmed", title="Event", domain="Projects",
        )
        other = engine.remember(
            "Cost envelope set aside", title="Budget", domain="Finance",
        )
        engine.upsert_triple("Event", "funds", "Budget")
        results = engine.recall_related(seed, top_k=5)
        assert [f.id for f in results] == [other]
        assert "triple" in results[0].why_retrieved
        # audited as well
        actions = [r["action"] for r in engine.list_audit(limit=20)]
        assert "recall_related" in actions

    def test_recall_related_uses_tags_and_skips_self(self, engine):
        seed = engine.remember(
            "Quarterly numbers collected", title="Report", domain="Finance",
            tags=["finance"],
        )
        other = engine.remember(
            "Ledger export automation", title="Ledger", domain="Finance",
        )
        engine.upsert_triple("finance", "owns", "Ledger")
        results = engine.recall_related(seed, top_k=5)
        assert [f.id for f in results] == [other]

    def test_recall_related_unknown_id_empty(self, engine):
        assert engine.recall_related("deadbeefdeadbeef") == []

    def test_cli_recall_reflect_and_related(self):
        with tempfile.TemporaryDirectory() as td:
            env = _cli_env(td)
            r = _run("remember", "CLI reflection smoke fact", **env)
            assert r.returncode == 0
            eid = [ln for ln in r.stdout.splitlines() if "Remembered:" in ln][0].split(":")[1].strip()

            r2 = _run("recall", "reflection smoke", "--reflect", **env)
            assert r2.returncode == 0, r2.stderr
            data = json.loads(r2.stdout)
            assert "reflect_summary" in data
            assert eid in data["source_ids"]

            r3 = _run("recall", "--related", eid, **env)
            assert r3.returncode == 0, r3.stderr
            assert "No related facts." in r3.stdout

            r4 = _run("recall", "--related", "not-a-hex", **env)
            assert r4.returncode == 1
            assert "Invalid entropic_id" in r4.stderr


# ── (3) consolidate --confirm reaches the engine ─────────────────────────────

class TestConsolidateCli:
    def test_engine_confirm_required_flag(self, engine):
        engine.remember("some forgettable fact", domain="Testing")
        r = engine.consolidate(max_age_days=0, min_access_count=0, dry_run=False, confirm=False)
        assert r["dry_run"] is True and r["confirm_required"] is True
        r2 = engine.consolidate(max_age_days=0, min_access_count=0, dry_run=True, confirm=True)
        assert r2["dry_run"] is True and r2["confirm_required"] is False
        r3 = engine.consolidate(max_age_days=0, min_access_count=0, dry_run=False, confirm=True)
        assert r3["dry_run"] is False and r3["archived"] == 1

    def test_cli_confirm_archives_and_dry_run_hints(self):
        with tempfile.TemporaryDirectory() as td:
            env = _cli_env(td)
            assert _run("remember", "Consolidation victim fact", **env).returncode == 0

            dry = _run("consolidate", "--max-age-days", "0", **env)
            assert dry.returncode == 0
            assert "Dry run: 1 facts would be archived" in dry.stdout
            assert "--confirm" in dry.stdout  # dry-run says confirm is required

            real = _run("consolidate", "--confirm", "--max-age-days", "0", **env)
            assert real.returncode == 0
            assert "Consolidated: 1 facts archived" in real.stdout  # really archived


# ── (4) unified graph_edges link graph ───────────────────────────────────────

class TestGraphUnification:
    def test_schema_is_graph_edges_never_links(self):
        conn = sqlite3.connect(":memory:")
        init_graph_schema(conn)
        init_links_schema(conn)  # deprecated alias targets the same table
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "graph_edges" in names
        assert "links" not in names  # the dead schema is gone
        conn.close()

    def test_store_links_writes_graph_edges(self):
        conn = sqlite3.connect(":memory:")
        init_graph_schema(conn)
        n = store_links(conn, "Finance/Budget.md", "Budget", [("Event", "for the event")])
        assert n == 1
        row = conn.execute("SELECT source_id, target_id, kind FROM graph_edges").fetchone()
        assert tuple(row) == ("Budget", "Event", "wikilink")
        # path-style lookup resolves to the stored title node
        assert get_outgoing_links(conn, "Finance/Budget.md")[0]["target"] == "Event"
        conn.close()

    def test_connected_notes_resolves_titles_via_notes_meta(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE notes_meta (note_id TEXT, title TEXT, path TEXT)")
        conn.execute(
            "INSERT INTO notes_meta VALUES ('n1', 'Alpha', 'Projects/Alpha.md'), "
            "('n2', 'Beta', 'Projects/Beta.md')"
        )
        init_graph_schema(conn)
        conn.execute("INSERT INTO graph_edges (source_id, target_id) VALUES ('n1', 'n2')")
        conn.commit()
        out = get_connected_notes(conn, "Alpha", depth=1)
        assert out["outgoing"] == {"Beta"}
        incoming = get_incoming_links(conn, "Beta")
        assert incoming and incoming[0]["source_title"] == "Alpha"
        conn.close()

    def test_expand_with_links_reads_graph_edges(self, engine):
        # regression: _expand_with_links used to query the always-empty links table
        engine.remember("Event venue booking confirmed", title="Event", domain="Projects")
        engine.remember("Cost envelope set aside", title="Budget", domain="Finance")
        init_graph_schema(engine.db)
        engine.db.execute(
            "INSERT INTO graph_edges (source_id, target_id, kind) VALUES ('Event', 'Budget', 'wikilink')"
        )
        engine.db.commit()

        plain = engine.recall_hybrid("event", expand_links=False)
        assert all("Cost envelope" not in f.content for f in plain)

        expanded = engine.recall_hybrid("event", expand_links=True)
        assert any("Cost envelope" in f.content for f in expanded), (
            "graph_edges-linked Budget fact missing from expanded recall"
        )

    def test_graph_show_cli_reads_index_graph_edges(self):
        with tempfile.TemporaryDirectory() as td:
            env = _cli_env(td)
            vault = Vault(Path(env["ENTROPICMEM_VAULT_PATH"]))
            p1 = vault.write_note("Projects", "Alpha Note", "Links to [[Beta Note]]", domain="Projects")
            p2 = vault.write_note("Projects", "Beta Note", "Plain body here", domain="Projects")
            idx = VaultIndex(Path(env["ENTROPICMEM_INDEX_DB"]))
            n1, n2 = vault.read_note(p1), vault.read_note(p2)
            idx.upsert_note(n1)
            idx.upsert_note(n2)
            idx.upsert_edges_for_note(vault, n1)
            idx.upsert_edges_for_note(vault, n2)
            idx.close()

            r = _run("graph", "show", "Alpha Note", **env)
            assert r.returncode == 0, r.stderr
            assert "Outgoing links" in r.stdout
            assert "Beta Note" in r.stdout

    def test_graph_show_empty_graph_message(self):
        with tempfile.TemporaryDirectory() as td:
            env = _cli_env(td)
            r = _run("graph", "show", "Nothing", **env)
            assert r.returncode == 0
            assert "Link graph is empty" in r.stdout


# ── (5) shared build_fts_query + reason tokens + field parity ────────────────

class TestFtsQueryBuilder:
    def test_single_home_for_all_callers(self):
        assert me.build_fts_query is index_build_fts_query
        assert me.build_fts_query is me.build_fts_query  # self-contained module

    def test_multiword_is_or_of_terms_not_one_phrase(self):
        q = build_fts_query("prefetch terms")
        assert " OR " in q
        assert '"prefetch"*' in q and '"terms"*' in q
        assert '"prefetch terms"' not in q  # never one giant phrase

    def test_terms_capped_most_discriminative_first(self):
        words = ["tiny"] + [f"token{i:03d}" for i in range(150)]
        q = build_fts_query(" ".join(words))
        assert q.count(" OR ") + 1 <= MAX_FTS_TERMS  # ~450 terms -> 10
        assert '"token000"*' in q  # long tokens kept
        assert '"tiny"*' not in q  # short token dropped at the cap

    def test_metacharacters_never_raise(self, engine):
        engine.remember("weird content with colons: (parens) and ^ carets", domain="Testing")
        for q in ['NEAR/2 (a b', 'a"b (c^ *) :', '(((', '^cat: "x"', '100% _under_', 'AND OR NOT']:
            results = engine.recall(q)  # must not raise sqlite3.OperationalError
            assert isinstance(results, list)
        assert build_fts_query('a"b:c (d^) *')  # quoting is metacharacter-safe

    def test_run_fts_match_reason_tokens(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='porter unicode61')")
        conn.execute("INSERT INTO t VALUES ('hello world')")
        rows, reason = run_fts_match(conn, "SELECT * FROM t WHERE t MATCH ?", ("(",))
        assert rows == [] and reason == FTS_REASON_MATCH_ERROR
        rows, reason = run_fts_match(conn, "SELECT * FROM t WHERE t MATCH ?", ('"hello"*',))
        assert len(rows) == 1 and reason == FTS_REASON_OK
        conn.close()

    def test_match_error_surfaces_as_reason_token(self, engine, monkeypatch):
        engine.remember("fallback target fact", title="Fallback", domain="Testing")
        monkeypatch.setattr(
            me, "run_fts_match", lambda *a, **k: ([], me.FTS_REASON_MATCH_ERROR),
        )
        hits = engine.recall_with_relevance("fallback target")
        assert hits  # LIKE fallback still finds the fact
        assert all("match_error" in f.why_retrieved for f in hits)
        hits2 = engine.recall("fallback target")
        assert hits2 and all("match_error" in f.why_retrieved for f in hits2)

    def test_match_failure_is_logged(self, engine, caplog):
        with caplog.at_level("WARNING", logger="memory_engine"):
            rows, reason = run_fts_match(
                engine.db, "SELECT 1 FROM facts_fts WHERE facts_fts MATCH ?", ("(",),
            )
        assert rows == [] and reason == FTS_REASON_MATCH_ERROR
        assert any("FTS5 MATCH failed" in rec.message for rec in caplog.records)

    def test_recall_and_relevance_agree_on_fields(self, engine):
        eid = engine.remember("noise noise noise filler words", title="alpha bravo", domain="Testing")
        by_recall = {f.id for f in engine.recall("alpha bravo")}
        by_relevance = {f.id for f in engine.recall_with_relevance("alpha bravo")}
        assert eid in by_recall, "recall() must match title tokens"
        assert eid in by_relevance, "recall_with_relevance() must match the same fields"


# ── (6) LIKE wildcard escaping + N+1 fix ─────────────────────────────────────

class TestLikeEscaping:
    def test_percent_and_underscore_match_literally(self, engine):
        a = engine.remember("progress 100%_done now", title="Literal", domain="Testing")
        b = engine.remember("plain zebra fact", title="Zebra", domain="Testing")

        hits = engine.recall("%")  # no FTS tokens -> LIKE fallback, escaped
        ids = {f.id for f in hits}
        assert a in ids and b not in ids, f"user % acted as a wildcard: {ids}"

        hits2 = engine.recall_with_relevance("_")
        ids2 = {f.id for f in hits2}
        assert a in ids2 and b not in ids2, f"user _ acted as a wildcard: {ids2}"

    def test_escape_like_escapes_all_wildcards(self):
        assert escape_like("100%_x\\y") == "100\\%\\_x\\\\y"

    def test_search_fts_path_comes_from_join(self):
        # regression for the per-hit get_note() N+1: path is selected in the
        # main JOIN and must be populated for every hit
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "vault"
            root.mkdir()
            vault = Vault(root)
            idx = VaultIndex(Path(td) / "index.db")
            p1 = vault.write_note(
                "Projects", "Search Note", "body about walloping widgets", domain="Projects",
            )
            note = vault.read_note(p1)
            idx.upsert_note(note)
            hits = idx.search_fts("walloping widgets")
            assert hits
            assert all(h.path for h in hits)
            assert hits[0].path == str(p1)
            idx.close()

    def test_search_by_title_escapes_wildcards(self):
        with tempfile.TemporaryDirectory() as td:
            idx = VaultIndex(Path(td) / "index.db")
            assert idx.search_by_title("100%_pure") == []  # never raises, no wildcard sweep
            idx.close()


# ── (7) vectorized vector_search + cache ─────────────────────────────────────

@pytest.fixture
def emb_db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "emb.db"))
    conn.execute("CREATE TABLE facts (id TEXT PRIMARY KEY, domain TEXT)")
    embeddings.init_embeddings_schema(conn)
    for fid, dom in [("a", "X"), ("b", "X"), ("c", "Y")]:
        conn.execute("INSERT INTO facts VALUES (?, ?)", (fid, dom))
    conn.commit()
    yield conn
    conn.close()


class TestVectorSearch:
    def test_numpy_path_matches_pure_python(self, emb_db, monkeypatch):
        embeddings.store_embedding(emb_db, "a", [1.0, 0.0, 0.1])
        embeddings.store_embedding(emb_db, "b", [0.0, 1.0, 0.0])
        embeddings.store_embedding(emb_db, "c", [-1.0, 0.0, 0.0])

        fast = embeddings.vector_search(emb_db, [1.0, 0.0, 0.0], top_k=3)
        monkeypatch.setattr(embeddings, "NUMPY_AVAILABLE", False)  # force fallback loop
        slow = embeddings.vector_search(emb_db, [1.0, 0.0, 0.0], top_k=3)

        assert [fid for fid, _ in fast] == [fid for fid, _ in slow]
        assert [fid for fid, _ in fast] == ["a", "b", "c"]
        for (_, s1), (_, s2) in zip(fast, slow):
            assert abs(s1 - s2) < 1e-5

    def test_cache_invalidated_on_store(self, emb_db):
        embeddings.store_embedding(emb_db, "a", [0.6, 0.8])  # cos(q)=0.6
        embeddings.store_embedding(emb_db, "b", [0.0, 1.0])  # cos(q)=0.0
        assert embeddings.vector_search(emb_db, [1.0, 0.0], top_k=1)[0][0] == "a"
        embeddings.store_embedding(emb_db, "b", [0.9, 0.1])  # cos(q)≈0.994 — now best
        assert embeddings.vector_search(emb_db, [1.0, 0.0], top_k=1)[0][0] == "b"

    def test_cache_invalidated_on_delete(self, emb_db):
        embeddings.store_embedding(emb_db, "a", [1.0, 0.0])
        embeddings.store_embedding(emb_db, "b", [0.5, 0.0])
        embeddings.delete_embedding(emb_db, "a")
        top = embeddings.vector_search(emb_db, [1.0, 0.0], top_k=5)
        assert [fid for fid, _ in top] == ["b"]

    def test_cache_isolated_per_db_file(self, tmp_path):
        db1 = sqlite3.connect(str(tmp_path / "one.db"))
        db2 = sqlite3.connect(str(tmp_path / "two.db"))
        for db in (db1, db2):
            db.execute("CREATE TABLE facts (id TEXT PRIMARY KEY, domain TEXT)")
            embeddings.init_embeddings_schema(db)
        embeddings.store_embedding(db1, "a", [1.0, 0.0])
        embeddings.store_embedding(db2, "a", [0.0, 1.0])

        r1 = embeddings.vector_search(db1, [1.0, 0.0], top_k=1)
        r2 = embeddings.vector_search(db2, [1.0, 0.0], top_k=1)
        assert r1[0][1] > 0.99  # db1's a is aligned
        assert r2[0][1] < 0.01  # db2's a is orthogonal — no cross-db cache bleed
        db1.close()
        db2.close()

    def test_domain_filter_still_works(self, emb_db):
        embeddings.store_embedding(emb_db, "a", [1.0, 0.0])
        embeddings.store_embedding(emb_db, "c", [1.0, 0.0])
        hits = embeddings.vector_search(emb_db, [1.0, 0.0], top_k=5, domain="Y")
        assert [fid for fid, _ in hits] == ["c"]

    def test_empty_table_returns_empty(self, emb_db):
        assert embeddings.vector_search(emb_db, [1.0, 0.0]) == []


# ── (9) extract_and_store docstring: quarantine semantics ────────────────────

class TestDocstringFidelity:
    def test_extract_and_store_promises_quarantine_not_remember(self):
        doc = MemoryEngine.extract_and_store.__doc__ or ""
        assert "quarantine" in doc.lower()
        assert "promote_pending" in doc
        assert "via remember()" not in doc


# ── (10) CLI validation wiring + _stub removal ───────────────────────────────

class TestCliValidationWiring:
    def test_stub_gone_and_comment_fixed(self):
        src = Path(_CLI).read_text(encoding="utf-8")
        assert "def _stub" not in src
        assert "_stub" not in src
        assert "stub for Phase 3-4" not in src

    def test_reinforce_history_forget_validate_ids(self):
        with tempfile.TemporaryDirectory() as td:
            env = _cli_env(td)
            for cmd in (("reinforce", "not-a-hex"),
                        ("history", "not-a-hex"),
                        ("forget", "--confirm", "not-a-hex")):
                r = _run(*cmd, **env)
                assert r.returncode == 1, f"{cmd} accepted a malformed id"
                assert "Invalid entropic_id" in r.stderr

    def test_ingest_rejects_internal_urls_via_validate_url(self):
        with tempfile.TemporaryDirectory() as td:
            env = _cli_env(td)
            r = _run("ingest", "http://localhost:9/internal", **env)
            assert r.returncode == 1
            assert "not allowed" in r.stderr
            # non-http schemes fall through to the file branch unchanged
            r2 = _run("ingest", "ftp://example.com/x", **env)
            assert r2.returncode == 1  # file not found — never fetched


# ── shared CLI setup ─────────────────────────────────────────────────────────

def _cli_env(td: str) -> dict:
    """Temp vault/index/memory paths and a seeded vault for CLI runs."""
    env = {
        "ENTROPICMEM_VAULT_PATH": str(Path(td) / "vault"),
        "ENTROPICMEM_INDEX_DB": str(Path(td) / "index.db"),
        "ENTROPICMEM_MEMORY_DB": str(Path(td) / "memory.db"),
    }
    assert _run(
        "init", "--vault", env["ENTROPICMEM_VAULT_PATH"],
        "--index-db", env["ENTROPICMEM_INDEX_DB"], **env,
    ).returncode == 0
    return env
