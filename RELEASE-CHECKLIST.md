# EntropicMem v1.0 — Release Checklist (Standalone)

Ship only when EntropicMem is a complete, self-contained memory tool.

---

## 1. Product identity

- [ ] README describes standalone memory system (no companion framing)
- [ ] SKILL.md describes EntropicMem as primary durable memory path
- [ ] PROJECT_PLAN.md matches standalone target (this replan)
- [ ] No required external memory application at runtime
- [ ] LICENSE (MIT) present

## 2. Core runtime

- [x] MemoryEngine (`memory.db`) remember/forget/list/stats/project
- [x] Vault Markdown archive
- [x] Vault index FTS + graph edges
- [x] Retrieval stack (query)
- [x] Graph export HTML/JSON/DOT/Canvas + serve
- [ ] `recall` CLI for MemoryEngine (recommended for v1.0)
- [x] `init` bootstrap
- [x] Knowledge loop: ingest, ingest-pile, note, research, lint, moc, hotcache

## 3. Agent installability

- [ ] SETUP.md complete and agent-executable
- [ ] skill SETUP.md mirror matches root
- [ ] `/learn https://github.com/Ufonik88/EntropicMem` dry-run succeeds
- [ ] Smoke: init → remember → query → graph export

## 4. Documentation

- [ ] references/MEMORY_MODEL.md
- [ ] references/VAULT_SCHEMA.md
- [ ] references/CLI_REFERENCE.md
- [ ] references/VISUALIZER.md
- [ ] references/HERMES_INTEGRATION.md
- [ ] docs/ARCHITECTURE.md
- [ ] docs/SELF_INSTALL.md
- [ ] docs/CLI_REFERENCE.md (or pointer to references)
- [ ] docs/VISUALIZER.md
- [ ] docs/COMPARISON.md (capability classes only; no dependency claims)

## 5. Quality

- [x] `pytest tests/ -q` green (80+ tests baseline)
- [ ] CLI help text clean of legacy wording
- [ ] Seed AGENTS.md/SCHEMA.md describe EntropicMem-only workflow
- [ ] CI workflow present

## 6. Release

- [ ] CHANGELOG.md entry for v1.0.0
- [ ] Git tag `v1.0.0`
- [ ] GitHub release published
- [ ] MASTER_TODO reflects post-ship state

---

## v1.0 definition of done (one sentence)

A Hermes agent can install EntropicMem via `/learn`, store durable knowledge, retrieve it with citations, maintain a linked vault, and visualize relationships — entirely within EntropicMem-owned storage and tools.
