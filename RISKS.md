# EntropicMem — Risk Register

Cross-referenced to `PROJECT_PLAN.md` §9. Owner: Entropy (agent) / Ufonik (human).  
Severity: **High** = blocks v1.0 ship; **Med** = degrades UX but workable; **Low** = nice-to-fix.

| # | Risk | Severity | Owner | Mitigation | Status |
|---|------|----------|-------|------------|--------|
| 1 | Live vault + Syncthing/git — agent writes to `~/Documents/Obsidian Vault` before guards tested | **High** | `vault.py` write guards | Safe mode default; never write `Mnemosyne/`, `.obsidian/`, `_archive/`; Phase 1 tests on temp vault only | **Closed** |
| 2 | `/learn` can't `pip install` — jinja2 / optional deps unavailable at install time | **High** | SETUP.md + stdlib-first | Vendoring `jinja2` not viable (large); document `pip install jinja2 sentence-transformers graphviz` as user step; `entropicmem --check-deps` reports | **Open** |
| 3 | Mnemosyne API churn breaks bridge — `remember()`/`recall()` signatures change | **Med** | `mnemosyne_bridge.py` uses public class only | Bridge imports `Mnemosyne` from `mnemosyne.core.memory`; unit tests mock the class; no direct SQL | **Open** |
| 4 | Graph hairball on 3K+ notes — D3 becomes unusable | **Med** | `graph_export.py` caps + filters | Default `--max-nodes 500`; archive excluded; domain/tag/importance filters; Phase 1 ships static HTML only | **Open** |
| 5 | Collision with bundled `obsidian` / `llm-wiki` skills — user confusion | **Med** | SKILL.md + COMPARISON.md | Explicit `related_skills`, complementary positioning ("EntropicMem = structure+graph+bridge"); no shared commands | **Open** |
| 6 | Embeddings optional — semantic re-rank missing if deps absent | **Low** | `retrieval.py` degrades to FTS | `use_semantic=False` default; `sentence-transformers` extra; `--check-deps` honest | **Decided** |
| 7 | Click-to-open protocol (`entropicmem://`) unregistered — clicks do nothing | **Low** | Document only in v1 | `graph.html` prints target to console if protocol unregistered; SETUP.md has registration recipe | **Accepted** |
| 8 | Skill-first vs MemoryProvider timing — premature provider attempt | **Med** | Phase 6+ only, never `memory.provider` | Plan explicitly: Phase 6 = adapter; v1 never enables as active provider | **Open** |
| 9 | Tencent/ByteDance lineage confusion in docs | **Low** | COMPARISON.md "Lineage" column | OpenViking = ByteDance; Tencent = Hunyuan/VectorDB; plan uses "context engineering lineage" phrasing | **Open** |
| 10 | Bridge cron not auto-installed — user forgets to run | **Low** | Recipe in SETUP.md only | `hermes cron create` or systemd timer; 6h default matches existing pipeline | **Open** |
| 11 | `entropic_id` collision (SHA256[:16] = 64-bit) | **Low** | Log warning on collision | Negligible for <10M notes; `hashlib.sha256(content).hexdigest()[:16]`; Fnv1a alternative if needed | **Accepted** |
| 12 | Path split-brain — README/SETUP/PLAN mix `scripts/` at root vs under skill | **Med** | Single layout: `skills/entropicmem/scripts/` | All docs must reference `~/.hermes/skills/entropicmem/scripts/entropicmem.py` post-learn | **Open** |

---

## Decision Log (from §9)

| Item | Decision | Rationale |
|------|----------|-----------|
| 5 | Node cap 500 for visual export | Keeps D3 responsive; archive excluded by default |
| 6 | Optional-dep policy: FTS mandatory, embeddings extra | Stdlib-first; `/learn` can't pip; `jinja2` = 1 mandatory extra, documented |
| 7 | Skill-first, MemoryProvider = Phase 6+ | Only one provider active; Mnemosyne is primary and must stay so |
| 8 | Lineage: OpenViking = ByteDance; Tencent analogues separate | Factual accuracy; avoids misattribution |
| 9 | Galaxy theme = dark, per-domain palette, node glow, edge weight | Matches Obsidian graph aesthetic; Obsidian-compatible colors |
| 11 | `entropic_id` = SHA256(content)[:16] | Deterministic round-trip key; no UUID service; matches Mnemosyne 16-char IDs |
| 12 | Single layout: `skills/entropicmem/scripts/` | Avoids split-brain; `skill_manage` copies entire skill dir |

---

## Mitigation Verification (Phase 1 Gate)

Before Phase 1 begins, confirm:

- [ ] `vault.py` write guards unit-tested against live vault paths
- [ ] `entropicmem --check-deps` prints honest status
- [ ] `mnemosyne_bridge.py` tests mock `Mnemosyne` class (no real DB)
- [ ] `graph_export.py --max-nodes 500` produces <200KB HTML
- [ ] `SKILL.md` description ≤60 chars, triggers listed, `related_skills` present
- [ ] All paths in docs = `skills/entropicmem/scripts/`
