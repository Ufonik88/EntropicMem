"""
retrieval.py — Composed retrieval stack for EntropicMem.

Layers:
  1. Hot cache (Wiki-Cache.md) — instant orientation
  2. FTS5 — primary full-text recall over title + tags + body
  3. Wikilink expansion — contextual follow (1-2 hops)
  4. Optional semantic re-rank — sentence-transformers (degraded gracefully)

All layers are standalone; retrieve_composed() runs the full stack.
Stdlib-only for core path. sentence-transformers is optional.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from index import SearchHit, VaultIndex
from vault import Vault

# Sentinel for optional dependency
EMBEDDER_AVAILABLE = False
try:
    from importlib.util import find_spec
    if find_spec("sentence_transformers"):
        EMBEDDER_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    pass


# ── data types ──────────────────────────────────────────────────────────────

@dataclass
class RetrievalResult:
    """Full retrieval response with citations, snippets, and graph context."""
    query: str
    orientation: str = ""               # hot cache snapshot
    hits: List[SearchHit] = field(default_factory=list)
    snippets: List[Dict] = field(default_factory=list)
    graph_context: List[Dict] = field(default_factory=list)
    stats: Dict = field(default_factory=dict)

    def summary(self) -> str:
        """Human-readable one-line summary."""
        return (
            f"Found {len(self.hits)} results for '{self.query}' "
            f"across {len(set(h.domain for h in self.hits))} domains."
        )

    def to_text(self, include_snippets: bool = True) -> str:
        """Render results as formatted text (for terminal/agent consumption)."""
        lines = [f"Query: {self.query}", f"Results: {len(self.hits)}", ""]
        for i, h in enumerate(self.hits[:15], 1):
            lines.append(f"{i}. [{h.domain}] {h.title}  (importance: {h.importance})")
            lines.append(f"   path: {h.path}")
            if include_snippets and h.snippet:
                lines.append(f"   > {h.snippet}")
            if h.tags:
                lines.append(f"   tags: {', '.join(h.tags)}")
            lines.append("")
        return "\n".join(lines)


# ── layer 1: hot cache ─────────────────────────────────────────────────────

def retrieve_hot_cache(vault: Vault) -> str:
    """
    Read Wiki-Cache.md if it exists. Returns empty string if absent.
    This is the orientation layer — instant, zero-cost context.
    """
    cache_path = vault.root / "Wiki-Cache.md"
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")
    return ""


# ── layer 2: FTS ───────────────────────────────────────────────────────────

def retrieve_fts(
    index: VaultIndex, query: str, top_k: int = 20, domain: Optional[str] = None
) -> List[SearchHit]:
    """Primary FTS5 recall over the vault index."""
    return index.search_fts(query, top_k=top_k, domain=domain)


# ── layer 3: wikilink expansion ────────────────────────────────────────────

def retrieve_wikilink_expansion(
    index: VaultIndex, seed_hits: List[SearchHit], hops: int = 2
) -> List[SearchHit]:
    """
    Expand results by following wikilinks in/out from seed notes.
    Returns deduplicated hits from the expanded neighborhood.
    """
    if hops < 1:
        return []

    seen: Set[str] = {h.note_id for h in seed_hits}
    expanded: List[SearchHit] = list(seed_hits)
    frontier = set(seen)

    for _ in range(hops):
        new_frontier: Set[str] = set()
        for nid in frontier:
            backlinks = index.get_backlinks(nid)
            outlinks = index.get_outlinks(nid)
            for link_id in backlinks + outlinks:
                if link_id not in seen:
                    new_frontier.add(link_id)
                    seen.add(link_id)
        frontier = new_frontier
        for nid in frontier:
            meta = index.get_note(nid)
            if meta:
                tags = [t.strip() for t in (meta.get("tags") or "").split(",") if t.strip()]
                expanded.append(SearchHit(
                    note_id=meta["note_id"],
                    path=meta.get("path", ""),
                    title=meta["title"],
                    domain=meta.get("domain", ""),
                    note_type=meta.get("note_type", "permanent"),
                    importance=meta.get("importance", 0.3),
                    tags=tags,
                    snippet=(meta.get("body_preview") or "")[:200],
                    rank=0.0,
                ))
    return expanded


# ── layer 4: semantic re-rank (optional) ────────────────────────────────────

def retrieve_semantic_rerank(
    hits: List[SearchHit], query: str
) -> List[SearchHit]:
    """
    Re-rank hits using sentence-transformers cosine similarity.
    Returns original order if embedder is unavailable.
    """
    if not EMBEDDER_AVAILABLE or len(hits) < 2:
        return hits

    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")

        # build corpus: title + body_preview
        texts = []
        for h in hits:
            text = h.title
            if h.snippet:
                text += " " + h.snippet.replace("**", "")
            texts.append(text)

        query_emb = model.encode([query])
        doc_embs = model.encode(texts)

        from sklearn.metrics.pairwise import cosine_similarity
        scores = cosine_similarity(query_emb, doc_embs)[0]

        for h, score in zip(hits, scores):
            h.rank = float(score)

        hits.sort(key=lambda h: h.rank, reverse=True)
    except Exception:
        # Degrade gracefully — any failure returns original order
        pass

    return hits


# ── composed stack ──────────────────────────────────────────────────────────

def retrieve_composed(
    query: str,
    vault: Vault,
    index: VaultIndex,
    top_k: int = 10,
    domain: Optional[str] = None,
    use_semantic: bool = False,
    wikilink_hops: int = 1,
) -> RetrievalResult:
    """
    Full retrieval stack.

    1. Hot cache → orientation string
    2. FTS5 → primary recall (top_k * 2 for headroom)
    3. Wikilink expansion → contextual neighborhood
    4. Optional semantic re-rank
    5. Deduplicate by note_id
    6. Build snippets + graph context
    """
    # 1. Hot cache
    orientation = retrieve_hot_cache(vault)

    # 2. FTS
    fts_hits = retrieve_fts(index, query, top_k=top_k * 2, domain=domain)

    # 3. Wikilink expansion
    expanded = retrieve_wikilink_expansion(index, fts_hits[:5], hops=wikilink_hops)

    # 4. Merge & dedup (respect domain filter)
    seen: Set[str] = set()
    all_hits: List[SearchHit] = []
    for h in fts_hits + expanded:
        if h.note_id not in seen:
            if domain and h.domain != domain:
                continue
            seen.add(h.note_id)
            all_hits.append(h)

    # 5. Optional semantic re-rank
    if use_semantic:
        all_hits = retrieve_semantic_rerank(all_hits, query)

    # 6. Trim to top_k
    final_hits = all_hits[:top_k]

    # 7. Build snippets (note body previews)
    snippets = []
    for h in final_hits:
        meta = index.get_note(h.note_id)
        if meta:
            snippets.append({
                "note_id": h.note_id,
                "title": h.title,
                "path": meta.get("path", ""),
                "preview": (meta.get("body_preview") or "")[:300],
                "importance": h.importance,
                "domain": h.domain,
            })

    # 8. Build graph context: seed note + 2-hop neighborhood
    graph_ids: Set[str] = {h.note_id for h in final_hits[:5]}
    for nid in list(graph_ids):
        graph_ids.update(index.get_backlinks(nid)[:10])
        graph_ids.update(index.get_outlinks(nid)[:10])
    graph_context = []
    for nid in graph_ids:
        meta = index.get_note(nid)
        if meta:
            graph_context.append({
                "note_id": meta["note_id"],
                "title": meta["title"],
                "domain": meta.get("domain", ""),
                "importance": meta.get("importance", 0.3),
            })

    # 9. Stats
    stats = {
        "fts_hits": len(fts_hits),
        "expanded_hits": len(expanded),
        "final_hits": len(final_hits),
        "semantic": use_semantic and EMBEDDER_AVAILABLE,
        "domains": list(set(h.domain for h in final_hits if h.domain)),
    }

    return RetrievalResult(
        query=query,
        orientation=orientation,
        hits=final_hits,
        snippets=snippets,
        graph_context=graph_context,
        stats=stats,
    )
