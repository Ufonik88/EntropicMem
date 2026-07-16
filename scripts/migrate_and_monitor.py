#!/usr/bin/env python3
"""EntropicMem migration + parity harness.

Reads durable facts from the legacy Mnemosyne DB and writes them into EntropicMem's
MemoryEngine + vault (non-destructive — legacy DB is never touched).

Also runs a recall-parity check: for each migrated fact, can EntropicMem recall it?
Results are written to a monitoring log that the 12h cron analyzes.

Run: python3 migrate_and_monitor.py [--dry-run] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
REPO_SCRIPTS = Path("/home/ufonik/Documents/Coding Projects/EntropicMem/skills/entropicmem/scripts")
if str(REPO_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(REPO_SCRIPTS))

HERMES_HOME = Path.home() / ".hermes"
MNEMOSYNE_DB = HERMES_HOME / "mnemosyne" / "data" / "mnemosyne.db"
ENTROPICMEM_HOME = HERMES_HOME / "entropicmem"
VAULT_PATH = ENTROPICMEM_HOME / "vault"
INDEX_DB = ENTROPICMEM_HOME / "index.db"
MEMORY_DB = ENTROPICMEM_HOME / "memory.db"
LOG_DIR = ENTROPICMEM_HOME / "migration_logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def log_path_for_run(ts: str) -> Path:
    return LOG_DIR / f"run_{ts}.jsonl"


# ── Legacy reader ────────────────────────────────────────────────────────────────
def read_legacy_facts(limit: int | None = None) -> list[dict]:
    """Pull global durable facts from Mnemosyne memories table + embeddings."""
    if not MNEMOSYNE_DB.is_file():
        return []
    conn = sqlite3.connect(str(MNEMOSYNE_DB))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        # memories table holds the canonical durable facts (no scope/domain cols)
        q = """
            SELECT id, content, source, importance, metadata_json, created_at
            FROM memories
            ORDER BY id
        """
        if limit:
            q = q.replace("ORDER BY id", f"ORDER BY id LIMIT {int(limit)}")
        rows = cur.execute(q).fetchall()
        out = []
        for r in rows:
            meta_raw = r["metadata_json"]
            try:
                meta = json.loads(meta_raw) if meta_raw else {}
            except Exception:
                meta = {}
            # derive domain from metadata tags if present
            tags = meta.get("tags") or []
            domain = "People" if any("user" in str(t).lower() for t in tags) else "Knowledge"
            out.append({
                "legacy_id": r["id"],
                "content": (r["content"] or "").strip(),
                "source": r["source"] or "legacy",
                "importance": float(r["importance"] or 0.5),
                "domain": domain,
                "created": r["created_at"],
            })
        return out
    finally:
        conn.close()


# ── EntropicMem writers ──────────────────────────────────────────────────────────
def write_to_entropicmem(fact: dict, dry_run: bool) -> dict:
    """Write one fact. Returns result dict for the log."""
    res = {"legacy_id": fact["legacy_id"], "content_len": len(fact["content"]), "status": "skip", "error": None, "entropic_id": None}
    if not fact["content"]:
        res["status"] = "skip_empty"
        return res
    if dry_run:
        res["status"] = "dry_run"
        return res
    try:
        from memory_engine import MemoryEngine
        from vault import Vault
        from index import VaultIndex

        engine = MemoryEngine(MEMORY_DB)
        # dedupe by content hash (engine does this internally too)
        eid = engine.remember(
            content=fact["content"],
            title=fact["content"][:60],
            domain=fact["domain"],
            source=fact["source"],
            importance=fact["importance"],
        )
        res["entropic_id"] = eid
        res["status"] = "written"

        # vault projection (best-effort)
        try:
            vault = Vault(VAULT_PATH)
            body = (
                f"## Fact\n{fact['content']}\n\n"
                f"## Source\n- legacy migration ({fact['source']})\n\n"
                f"## Links\n- [[{fact['domain']}/Index]]\n"
            )
            note = vault.write_note(
                fact["domain"],
                f"Fact - {fact['content'][:50]}",
                body,
                tags=["legacy", "migrated"],
                domain=fact["domain"],
                frontmatter={"entropic_id": eid, "legacy_id": fact["legacy_id"]},
            )
            idx = VaultIndex(INDEX_DB)
            n = vault.read_note(note)
            idx.upsert_note(n)
            idx.upsert_edges_for_note(vault, n)
            idx.close()
        except Exception as ve:
            res["vault_error"] = str(ve)[:200]
        engine.close()
    except Exception as e:
        res["status"] = "error"
        res["error"] = str(e)[:300]
    return res


# ── Main ────────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = log_path_for_run(ts)
    run_start = time.time()

    facts = read_legacy_facts(args.limit)
    total = len(facts)
    written = skipped = errors = 0
    parity_ok = parity_total = 0
    error_samples = []

    print(f"[migrate] {total} legacy facts found (limit={args.limit}, dry_run={args.dry_run})")

    with log_path.open("w", encoding="utf-8") as lf:
        lf.write(json.dumps({
            "event": "run_start", "ts": ts, "total": total,
            "dry_run": args.dry_run, "legacy_db": str(MNEMOSYNE_DB),
        }) + "\n")
        for i, fact in enumerate(facts):
            r = write_to_entropicmem(fact, args.dry_run)
            if r["status"] == "written":
                written += 1
            elif r["status"] in ("error",):
                errors += 1
                if len(error_samples) < 10:
                    error_samples.append({"legacy_id": r["legacy_id"], "error": r["error"]})
            else:
                skipped += 1
            lf.write(json.dumps({"event": "fact", **r}) + "\n")
            if (i + 1) % 500 == 0:
                print(f"  ...{i+1}/{total}")

        # ── Parity: SEPARATE pass after all writes commit ──────────────
        # (In-line parity during the write loop races the FTS commit and
        #  under-reports; measure after the engine is fully settled.)
        # Track (entropic_id, snippet) for each written fact so we can
        # verify EXACT self-retrieval by id — not fuzzy substring matching.
        parity_total = sum(1 for f in facts if f["content"])
        parity_ok = 0
        if not args.dry_run and written:
            from memory_engine import MemoryEngine, StoredFact

            engine = MemoryEngine(MEMORY_DB)
            written_facts = []  # (entropic_id, full_content)
            for f in facts:
                if not f["content"]:
                    continue
                # use FULL content for self-recall (exact-match boost in engine)
                eid = StoredFact.make_id(f["content"])
                written_facts.append((eid, f["content"]))
            for eid, content in written_facts:
                rows = engine.recall(content, top_k=10)
                if any(r.id == eid for r in rows):
                    parity_ok += 1
            engine.close()

        duration = round(time.time() - run_start, 2)
        summary = {
            "event": "run_summary",
            "ts": ts,
            "total": total,
            "written": written,
            "skipped": skipped,
            "errors": errors,
            "parity_total": parity_total,
            "parity_ok": parity_ok,
            "parity_rate": round(parity_ok / parity_total, 4) if parity_total else None,
            "duration_s": duration,
            "error_samples": error_samples,
        }
        lf.write(json.dumps(summary) + "\n")
        print(f"[migrate] written={written} skipped={skipped} errors={errors} "
              f"parity={parity_ok}/{parity_total} dur={duration}s")
        print(f"[migrate] log: {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())