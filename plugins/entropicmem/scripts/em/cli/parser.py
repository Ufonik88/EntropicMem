"""The entropicmem CLI's argparse tree, shared by both entry points.

``scripts/entropicmem.py`` builds this tree on its own parser (the standalone
``python3 .../entropicmem.py <cmd>`` surface); ``plugins/entropicmem/cli.py``
adds the same tree onto the parser the Hermes host creates for
``hermes entropicmem <cmd>`` (EM-408) — the host imports that file only while
``memory.provider: entropicmem`` (``plugins.memory.discover_plugin_cli_commands``).

The host's top-level subparsers use ``dest="command"`` and the host reads
``args.command`` after parsing (``set_process_surface``, startup gates), so a
mounted tree must not reuse that dest: the plugin mount passes
``dest="entropicmem_command"`` and ``entropicmem_command`` dispatches on that
attribute.

This module must stay dependency-free — ``--help`` is a stdlib-only contract
(``tests/test_cli_reference_drift.py``).
"""

from __future__ import annotations

import argparse

__all__ = ["add_commands", "build_parser"]

_DESCRIPTION = "EntropicMem — standalone agent memory system"


def add_commands(parser: argparse.ArgumentParser, *, dest: str = "command") -> argparse.ArgumentParser:
    """Add the global flags and the full subcommand tree to *parser*.

    *dest* names the root subparsers attribute: ``command`` for the standalone
    CLI, ``entropicmem_command`` for the hermes mount (see the module doc).
    """
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    parser.add_argument("--check-deps", action="store_true", help="Print optional dependency status")

    sub = parser.add_subparsers(dest=dest)

    # init
    p_init = sub.add_parser("init", help="Bootstrap a vault")
    p_init.add_argument("--vault", help="Vault root path")
    p_init.add_argument("--index-db", help="SQLite index DB path")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing seed files")
    p_init.add_argument("--dry-run", action="store_true", help="Print actions without writing")

    # ingest
    p_ingest = sub.add_parser("ingest", help="Ingest a source (URL, file, or stdin)")
    p_ingest.add_argument("source", nargs="?", help="URL or file path")
    p_ingest.add_argument("--domain", default="Knowledge", help="Target domain folder")

    # ingest-pile
    p_pile = sub.add_parser("ingest-pile", help="Batch ingest a directory")
    p_pile.add_argument("dir", help="Directory of sources")
    p_pile.add_argument("--domain", default="Knowledge", help="Target domain folder")

    # query
    p_query = sub.add_parser("query", help="Search the vault")
    p_query.add_argument("query", help="Search query")
    p_query.add_argument("--top-k", type=int, default=10, help="Max results (default: 10)")
    p_query.add_argument("--semantic", action="store_true", help="Enable semantic re-rank")
    p_query.add_argument("--domain", help="Filter by domain")

    # note
    p_note = sub.add_parser("note", help="Create a note from stdin")
    p_note.add_argument("title", nargs="?", help="Note title")
    p_note.add_argument("--domain", default="Knowledge", help="Target domain folder")
    p_note.add_argument("--tags", help="Comma-separated tags")

    # research
    p_research = sub.add_parser("research", help="Create research brief for agent-driven web research")
    p_research.add_argument("query", help="Research question")
    p_research.add_argument("--rounds", type=int, default=3, help="Research rounds")

    # lint
    p_lint = sub.add_parser("lint", help="Check vault health")
    p_lint.add_argument("--domain", help="Filter by domain")
    p_lint.add_argument("--pii", action="store_true", help="Scan facts for PII (Phase 9)")

    # moc
    p_moc = sub.add_parser("moc", help="Build/repair domain Index.md + backlinks")
    p_moc.add_argument("--domain", help="Target domain")

    # hotcache
    sub.add_parser("hotcache", help="Rebuild Wiki-Cache.md")

    p_index = sub.add_parser("index", help="Vault index maintenance (v2.1.8)")
    idx_sub = p_index.add_subparsers(dest="index_command")
    idx_rebuild = idx_sub.add_parser("rebuild", help="Full rebuild: reindex every vault note + graph edges")
    idx_rebuild.add_argument("--include-archive", action="store_true",
                             help="Also index notes in the archive folder")
    idx_refresh = idx_sub.add_parser(
        "refresh",
        help="Incremental refresh: only notes whose file stat changed are read (EM-603)",
    )
    idx_refresh.add_argument("--include-archive", action="store_true",
                             help="Also refresh notes in the archive folder")
    idx_sub.add_parser("status", help="Report index freshness without touching anything")

    # graph
    p_graph = sub.add_parser("graph", help="Graph export and serve")
    g_sub = p_graph.add_subparsers(dest="graph_command")
    g_export = g_sub.add_parser("export", help="Export visual graph")
    g_export.add_argument("--format", default="html", choices=["json", "dot", "html", "canvas"])
    g_export.add_argument("--output-dir", default="./export", help="Output directory")
    g_export.add_argument("--max-nodes", type=int, default=500, help="Max nodes (default: 500)")
    g_export.add_argument("--domain", help="Filter by domain")
    g_export.add_argument("--min-importance", type=float, default=0.0, help="Min importance filter")
    g_export.add_argument("--include-bodies", dest="include_bodies", action="store_true", default=True,
                          help="Embed note bodies in HTML/JSON (default: ON so modals show markdown)")
    g_export.add_argument("--no-bodies", dest="include_bodies", action="store_false",
                          help="Omit note bodies (shareable lean shell only)")
    g_serve = g_sub.add_parser("serve", help="Serve graph export dir via HTTP")
    g_serve.add_argument("--port", type=int, default=8069)
    g_serve.add_argument("--bind", default="127.0.0.1", help="Bind address (default 127.0.0.1)")
    g_serve.add_argument("--dir", default="./export")
    g_show = g_sub.add_parser("show", help="Show connected notes for a target (Phase 10)")
    g_show.add_argument("target", help="Note title to find connections for")
    g_show.add_argument("--depth", type=int, default=1, help="Traversal depth (default: 1)")

    # triple (v2.2.0 G2)
    p_triple = sub.add_parser("triple", help="Knowledge triples (subject--predicate-->object)")
    t_sub = p_triple.add_subparsers(dest="triple_command")
    t_sub.add_parser("extract", help="Extract triples from facts + vault notes (rule-based)")
    t_sub.add_parser("stats", help="Triple counts")
    p_t_neighbors = t_sub.add_parser("neighbors", help="All relations touching an entity")
    p_t_neighbors.add_argument("entity", help="Entity to query (e.g. 'Acme Corp')")
    p_t_path = t_sub.add_parser("path", help="Path between two entities")
    p_t_path.add_argument("start", help="Start entity")
    p_t_path.add_argument("end", help="End entity")
    t_sub.add_parser("inconsistencies", help="Conflicting relations (same subject+predicate, different objects)")
    p_t_list = t_sub.add_parser("list", help="List triples with optional filters")
    p_t_list.add_argument("--subject", help="Filter by subject")
    p_t_list.add_argument("--predicate", help="Filter by predicate")
    p_t_list.add_argument("--object", help="Filter by object")
    p_t_list.add_argument("--source", help="Filter by source (extracted, mnemosyne_legacy)")
    p_t_list.add_argument("--limit", type=int, default=50)

    # recall
    p_recall = sub.add_parser("recall", help="Search durable facts in memory engine")
    p_recall.add_argument("query", nargs="?", default="", help="Search query (omit with --related)")
    p_recall.add_argument("--top-k", type=int, default=10, help="Max results (default: 10)")
    p_recall.add_argument("--domain", default=None, help="Filter by domain")
    p_recall.add_argument("--scope", default="own", choices=["own", "shared", "all"],
                          help="own = local facts; shared = peer-shared; all = both")
    p_recall.add_argument("--reflect", action="store_true",
                          help="Agent reflection layer: JSON facts + reflect_summary (Sprint A)")
    p_recall.add_argument("--related", metavar="ENTROPIC_ID",
                          help="Find facts related to a fact via its triples graph (Sprint A)")
    p_recall.add_argument("--type", dest="recall_type", default="fact",
                          choices=["fact", "episodic"], help="Store to search (v2.2.0)")
    p_recall.add_argument("--since", dest="since", help="Start date (YYYY-MM-DD), episodic only (v2.2.0)")
    p_recall.add_argument("--until", dest="until", help="End date (YYYY-MM-DD), episodic only (v2.2.0)")

    # episode (v2.2.0 G1)
    p_episode = sub.add_parser("episode", help="Episodic memory (session summaries, timeline)")
    ep_sub = p_episode.add_subparsers(dest="episode_command")
    p_ep_add = ep_sub.add_parser("add", help="Add an episodic record")
    p_ep_add.add_argument("title", help="Episode title")
    p_ep_add.add_argument("summary", help="Episode summary (what happened and why it matters)")
    p_ep_add.add_argument("--start", dest="start_ts", help="Start timestamp (ISO)")
    p_ep_add.add_argument("--end", dest="end_ts", help="End timestamp (ISO)")
    p_ep_add.add_argument("--session", dest="source_session", default="", help="Source Hermes session id")
    p_ep_add.add_argument("--link-facts", dest="linked_fact_ids", default="", help="Comma-separated fact ids")
    p_ep_add.add_argument("--importance", type=float, default=0.5)
    p_ep_add.add_argument("--domain", default="Knowledge")
    p_ep_add.add_argument("--source", default="agent", help="Origin (agent, cron, mnemosyne_legacy)")
    p_ep_list = ep_sub.add_parser("list", help="List episodes chronologically")
    p_ep_list.add_argument("--from", dest="from_date", help="Start date (YYYY-MM-DD)")
    p_ep_list.add_argument("--to", dest="to_date", help="End date (YYYY-MM-DD)")
    p_ep_list.add_argument("--domain", help="Filter by domain")
    p_ep_list.add_argument("--limit", type=int, default=50)
    ep_sub.add_parser("stats", help="Episode counts")

    # remember
    p_remember = sub.add_parser("remember", help="Store durable fact in memory engine + vault")
    p_remember.add_argument("fact", help="The fact to remember")
    p_remember.add_argument("--domain", default="Knowledge")
    p_remember.add_argument("--tags", help="Comma-separated tags")

    # forget
    p_forget = sub.add_parser("forget", help="Delete fact from memory engine and vault note")
    p_forget.add_argument("--confirm", action="store_true", help="Required to delete")
    p_forget.add_argument("entropic_id", help="The entropic_id to forget")

    # memory
    p_memory = sub.add_parser("memory", help="Memory engine operations")
    m_sub = p_memory.add_subparsers(dest="memory_command")
    m_sub.add_parser("project", help="Project memory facts to vault")
    m_sub.add_parser("stats", help="Show memory engine statistics")
    m_sub.add_parser("reindex", help="Rebuild facts_fts from facts (repair orphans)")
    m_list = m_sub.add_parser("list", help="List facts in memory engine")
    m_list.add_argument("--domain", help="Filter by domain")
    m_list.add_argument("--limit", type=int, default=50)

    # stats (EM-408: top-level shortcut — the same handler as `memory stats`,
    # reached as `hermes entropicmem stats` through the plugin mount)
    p_stats = sub.add_parser("stats", help="Show memory engine statistics")
    p_stats.set_defaults(memory_command="stats")

    # open
    p_open = sub.add_parser("open", help="Open a note in system editor")
    p_open.add_argument("note_id", help="Note ID (Domain/Name or vault://Domain/Name)")

    # extract (Phase 8: auto-extraction)
    p_extract = sub.add_parser("extract", help="Extract durable facts from conversation text (regex-based, no LLM)")
    p_extract.add_argument("--text", help="Conversation text (default: stdin)")
    p_extract.add_argument("--session-id", help="Session ID for tracking")
    p_extract.add_argument("--source", default="auto_extracted", help="Source tag")
    p_extract.add_argument("--min-confidence", type=float, default=0.4, help="Minimum confidence threshold")

    # reinforce (Phase 8: temporal decay)
    p_reinforce = sub.add_parser("reinforce", help="Boost a fact's access count and timestamp")
    p_reinforce.add_argument("entropic_id", help="The entropic_id to reinforce")

    # patch-core (Phase 8: core memory)
    p_patch_core = sub.add_parser("patch-core", help="Surgically update Core Memory (Persona/User Profile)")
    p_patch_core.add_argument("target", choices=["persona", "user_profile"], help="Target Core Memory file")
    p_patch_core.add_argument("--patch", help="Text to find and replace")
    p_patch_core.add_argument("--replacement", default="", help="Replacement text (empty = delete)")

    # embed (Phase 7)
    p_embed = sub.add_parser("embed", help="Manage vector embeddings")
    p_embed.add_argument("--rebuild", action="store_true", help="Rebuild all embeddings")

    # timeline (Phase 8)
    p_timeline = sub.add_parser("timeline", help="Show facts chronologically")
    p_timeline.add_argument("--from", dest="from_date", help="Start date (YYYY-MM-DD)")
    p_timeline.add_argument("--to", dest="to_date", help="End date (YYYY-MM-DD)")
    p_timeline.add_argument("--domain", help="Filter by domain")
    p_timeline.add_argument("--limit", type=int, default=50, help="Max results")

    # security (Phase 11)
    p_security = sub.add_parser("security", help="Encryption at rest")
    s_sub = p_security.add_subparsers(dest="security_command")
    s_sub.add_parser("enable", help="Enable encryption")
    s_sub.add_parser("disable", help="Disable encryption")
    s_sub.add_parser("status", help="Show encryption status")
    s_sub.add_parser(
        "fix-permissions", help="Restrict an existing vault/index to private file modes"
    )

    # export / import (Phase 11)
    p_export = sub.add_parser("export", help="Export memory capsule")
    p_export.add_argument("output", nargs="?", default="capsule.tar.gz", help="Output path")
    p_import = sub.add_parser("import", help="Import memory capsule")
    p_import.add_argument("input", help="Input capsule path")

    # history (Phase 11)
    p_history = sub.add_parser("history", help="Show fact version history")
    p_history.add_argument("entropic_id", help="Fact ID")

    # consolidate (M2)
    p_consolidate = sub.add_parser("consolidate", help="Archive old, low-access facts")
    p_consolidate.add_argument("--max-age-days", type=int, default=90, help="Archive facts older than N days (default: 90)")
    p_consolidate.add_argument("--min-access-count", type=int, default=0, help="Only archive facts accessed N times or fewer")
    p_consolidate.add_argument("--confirm", action="store_true", help="Required to actually archive")
    p_consolidate.add_argument("--dry-run", action="store_true", help="Report what would be archived without archiving")

    # migrate (P1 multi-profile provenance)
    p_migrate = sub.add_parser("migrate", help="P1 provenance migration (fail-closed, idempotent)")
    p_migrate.add_argument("--schema-version", type=int, default=1, help="Schema version to stamp")
    p_migrate.add_argument("--phase", type=int, default=1, help="Implementation phase to stamp")
    p_migrate.add_argument("--status", action="store_true", help="Report migration state without migrating")

    # shared / publish / pull (P2 controlled sync)
    sub.add_parser("shared-init", help="Bootstrap the shared sync store (idempotent)")
    p_publish = sub.add_parser("publish", help="Drain the local outbox into the shared log")
    p_publish.add_argument("--backfill", action="store_true",
                           help="Emit all local non-secret facts once (explicit opt-in for legacy facts)")
    sub.add_parser("pull", help="Apply new shared events into the local shared-facts projection")

    # Parse

    p_audit = sub.add_parser("audit", help="Show recent security audit log")
    p_audit.add_argument("--limit", type=int, default=50)
    p_audit_sub = p_audit.add_subparsers(dest="audit_command")
    p_audit_sub.add_parser("verify", help="Verify the v3 audit hash chain")

    p_pending = sub.add_parser("pending", help="Manage quarantined auto-extract facts")
    p_pending_sub = p_pending.add_subparsers(dest="pending_command")
    p_pl = p_pending_sub.add_parser("list", help="List pending facts")
    p_pl.add_argument("--limit", type=int, default=50)
    p_pp = p_pending_sub.add_parser("promote", help="Promote pending fact to durable memory")
    p_pp.add_argument("id", help="Pending fact id")
    p_pd = p_pending_sub.add_parser("discard", help="Discard pending fact")
    p_pd.add_argument("id", help="Pending fact id")
    p_pr = p_pending_sub.add_parser("prune", help="TTL-purge old pending facts (EM-111)")
    p_pr.add_argument("--older-than", default="30d", help="TTL, e.g. 30d (default)")

    p_worker = sub.add_parser("worker", help="Run background jobs on a v3 store (never migrates)")
    w_sub = p_worker.add_subparsers(dest="worker_command")
    p_run = w_sub.add_parser("run", help="Claim and run queued jobs")
    p_run.add_argument("--once", action="store_true", help="Run at most one job")
    p_run.add_argument("--types", nargs="+", help="Limit to these job types (default: every registered type)")
    p_run.add_argument("--max-seconds", type=float, dest="max_seconds", help="Stop after this many seconds")

    # vault (EM-601 slice 2): lint the projected vault for unsafe auto-sections
    p_vault = sub.add_parser("vault", help="Vault projection commands")
    v_sub = p_vault.add_subparsers(dest="vault_command")
    p_vault_lint = v_sub.add_parser("lint", help="Lint the projected vault: report projected files whose auto-sections are unsafe")
    p_vault_lint.add_argument("--root", required=True, help="Vault root path")

    return parser


def build_parser(prog: str = "entropicmem") -> argparse.ArgumentParser:
    """A standalone parser carrying the full command tree (``main()``'s)."""
    parser = argparse.ArgumentParser(prog=prog, description=_DESCRIPTION)
    add_commands(parser)
    return parser
