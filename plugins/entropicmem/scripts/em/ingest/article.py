"""EM-607 — ingest v2, the parts that are not vault or store work.

The card (§6.5) asks for five things, and this module is the first four:

* **HTML → text** through the stdlib parser (:mod:`em.ingest.html_text`).
* **A size cap** — :data:`MAX_SOURCE_BYTES` on what is read, and
  :data:`MAX_TEXT_CHARS` on what is kept. The second is a truncation, not a
  refusal, because a long article is still worth a note; the truncation is
  recorded in the note rather than hidden.
* **One chunked note** under ``Sources/`` — :func:`chunk_text` splits on
  paragraph boundaries and :func:`build_note` renders the body. One note per
  ingest, whatever the length: the v2 path wrote one *literature* note plus one
  *atomic* note per capitalised phrase, which is the junk this card removes.
* **Key points, optionally by LLM** — :func:`key_points` takes the plan's
  Appendix C.6 shape (``{"key_points": […], "claims": [{"content",
  "evidence_quote"}]}``, ≤ 10 of each) when a backend is supplied, and falls back
  to a deterministic sentence scan when it is not, when the call fails, or when
  the reply does not validate. It is fail-soft in the same way the formation
  paths are: an unavailable model changes the quality of the note, never
  whether the ingest happened.

The fifth — `pending` memories with ``source=ingest`` and the URL as evidence —
is the store's job and lives in :func:`queue_claims`, which needs a v3 store.
The CLI composes the two.

**Why the claim set is the key-point set.** The card names "extracted claims"
and the plan's C.6 returns both in one call. Keeping one set means a 50 KB
article cannot produce more than :data:`MAX_CLAIMS` pending rows no matter how
the text is shaped, which is the card's own AC — a limit that one code path
enforces is worth more than two paths that each respect it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from .html_text import ArticleText, html_to_text

__all__ = [
    "CHUNK_CHARS",
    "INGEST_SOURCE",
    "MAX_CLAIMS",
    "MAX_SOURCE_BYTES",
    "MAX_TEXT_CHARS",
    "SOURCES_FOLDER",
    "KeyPoints",
    "Source",
    "SourceTooLarge",
    "build_note",
    "cap_text",
    "check_source_size",
    "chunk_text",
    "key_points",
    "prepare",
    "queue_claims",
]

#: The write-policy source every claim carries. ``evaluate_write`` quarantines
#: it, so ``MemoryStore.add`` lands a ``pending`` row: ingest proposes, a human
#: promotes.
INGEST_SOURCE = "ingest"

#: Where a source note lands. One folder for every ingested document, so the
#: vault never confuses "a thing I read" with "a thing I know".
SOURCES_FOLDER = "Sources"

#: What we are willing to read at all. Twice the size of a very long article;
#: anything past this is a download, not an article, and refusing is clearer
#: than silently ingesting the first part of a book.
MAX_SOURCE_BYTES = 2 * 1024 * 1024

#: What the note keeps. A 50 KB article fits whole; a 400 KB one is truncated at
#: a paragraph boundary and says so in the note.
MAX_TEXT_CHARS = 60_000

#: One note, many chunks: big enough to be quotable, small enough that the note
#: reads as sections rather than one wall of text.
CHUNK_CHARS = 4_000

#: The card's ceiling on pending memories per ingest, and the plan's C.6 cap.
MAX_CLAIMS = 10

#: How many chunks one document may spend LLM calls on. C.6 is per chunk and the
#: formation budget defaults to 60 calls an hour; three keeps one ingest well
#: inside it while still reading more than the opening.
MAX_LLM_CHUNKS = 3

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_MARKER_RE = re.compile(r"^(?:#{1,6}\s+|-\s+|\*\s+)")


class SourceTooLarge(ValueError):
    """The source is past :data:`MAX_SOURCE_BYTES`; nothing was read from it."""

    def __init__(self, size: int, limit: int = MAX_SOURCE_BYTES) -> None:
        super().__init__(
            f"source is {size:,} bytes, larger than the {limit:,}-byte ingest cap"
        )
        self.size = size
        self.limit = limit


@dataclass(frozen=True)
class Source:
    """One prepared source: what the note will say and how it is chunked."""

    title: str
    url: str
    text: str
    chunks: tuple[str, ...]
    truncated: bool = False
    original_chars: int = 0
    raw_chars: int = 0


@dataclass(frozen=True)
class KeyPoints:
    """Appendix C.6's two outputs, already capped and deduplicated."""

    points: tuple[str, ...] = ()
    claims: tuple[str, ...] = ()
    from_llm: bool = False


# --- the caps ---------------------------------------------------------------


def check_source_size(raw: str, *, limit: int = MAX_SOURCE_BYTES) -> None:
    """Raise :class:`SourceTooLarge` when *raw* exceeds the byte cap."""
    size = len(raw.encode("utf-8"))
    if size > limit:
        raise SourceTooLarge(size, limit)


def cap_text(text: str, *, limit: int = MAX_TEXT_CHARS) -> tuple[str, bool]:
    """Truncate to *limit* at a paragraph boundary. Returns ``(text, cut)``.

    A boundary is preferred so the last kept chunk is whole; a single paragraph
    longer than the limit is cut at the last space instead of mid-word.
    """
    if len(text) <= limit:
        return text, False
    head = text[:limit]
    for boundary in ("\n\n", "\n", ". "):
        cut = head.rfind(boundary)
        if cut >= limit // 2:
            return head[:cut].rstrip(), True
    cut = head.rfind(" ")
    return (head[:cut] if cut > 0 else head).rstrip(), True


# --- chunking ---------------------------------------------------------------


def chunk_text(text: str, *, size: int = CHUNK_CHARS) -> tuple[str, ...]:
    """Split on paragraph boundaries into chunks of about *size* characters.

    A paragraph longer than *size* is split at spaces rather than dropped, and
    the chunk order is the document order. Joining the result with a blank line
    reproduces the input except for that whitespace normalisation.
    """
    if not text.strip():
        return ()
    chunks: list[str] = []
    current: list[str] = []
    length = 0

    def flush() -> None:
        nonlocal current, length
        if current:
            chunks.append("\n\n".join(current).strip())
            current = []
            length = 0

    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) > size:
            flush()
            words = paragraph.split()
            piece: list[str] = []
            budget = 0
            for word in words:
                if budget and budget + len(word) + 1 > size:
                    chunks.append(" ".join(piece))
                    piece = []
                    budget = 0
                piece.append(word)
                budget += len(word) + 1
            if piece:
                chunks.append(" ".join(piece))
            continue
        if length and length + len(paragraph) + 2 > size:
            flush()
        current.append(paragraph)
        length += len(paragraph) + 2
    flush()
    return tuple(chunk for chunk in chunks if chunk)


# --- preparation ------------------------------------------------------------


def prepare(
    raw: str,
    *,
    url: str = "",
    title: str = "",
    is_html: bool = False,
) -> Source:
    """Turn fetched or read content into a :class:`Source`.

    *is_html* is the caller's knowledge (a URL, an ``.html`` file); guessing by
    looking for ``<`` in the first line would mangle a Markdown article quoting
    a tag. An HTML page contributes its ``<title>`` as the title fallback, then
    the caller's hint wins, then the URL's last path segment.
    """
    check_source_size(raw)
    parsed = html_to_text(raw) if is_html else ArticleText(text=raw, title="")
    text, truncated = cap_text(parsed.text.strip())
    name = (
        title.strip()
        or parsed.title.strip()
        or _title_from_url(url)
        or "Untitled Source"
    )
    return Source(
        title=name,
        url=url,
        text=text,
        chunks=chunk_text(text),
        truncated=truncated,
        original_chars=len(parsed.text),
        raw_chars=len(raw),
    )


def _title_from_url(url: str) -> str:
    if not url:
        return ""
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    tail = tail.split("?", 1)[0].split("#", 1)[0]
    return re.sub(r"\.[a-zA-Z0-9]{1,5}$", "", tail).strip()


# --- key points and claims --------------------------------------------------


def _sentences(text: str) -> list[str]:
    out: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        block = " ".join(block.split())
        if not block:
            continue
        for sentence in _SENTENCE_RE.split(block):
            sentence = _MARKER_RE.sub("", sentence).strip()
            if sentence:
                out.append(sentence)
    return out


def _deterministic(text: str, *, limit: int) -> tuple[list[str], list[str]]:
    """Sentence scan: substantial sentences, in document order, deduplicated.

    40 characters is the floor because a shorter sentence is a fragment of the
    surrounding prose ("See below."), and 300 the ceiling because a claim has to
    fit a memory. A sentence ending in ``?`` is a question the article asks, not
    a claim it makes, so it is not proposed.
    """
    picked: list[str] = []
    seen: set[str] = set()
    for sentence in _sentences(text):
        if not 40 <= len(sentence) <= 300 or sentence.endswith("?"):
            continue
        key = sentence.casefold()
        if key in seen:
            continue
        seen.add(key)
        picked.append(sentence)
        if len(picked) >= limit:
            break
    return picked, list(picked)


_LLM_SYSTEM = (
    "You extract the key points and factual claims from one chunk of a document. "
    "Reply with JSON only: {\"key_points\": [str], \"claims\": [{\"content\": str, "
    "\"evidence_quote\": str}]}. At most 10 of each. A key point is what the chunk "
    "teaches; a claim is one self-contained fact a reader could store, 40 to 300 "
    "characters. evidence_quote must be copied verbatim from the chunk and at most "
    "300 characters. Never add a fact the chunk does not state, and never guess at "
    "an author's intent."
)

_LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "key_points": {"type": "array", "items": {"type": "string"}},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"content": {"type": "string"}, "evidence_quote": {"type": "string"}},
            },
        },
    },
}


def _from_llm(
    chunks: Sequence[str], llm: Any, *, limit: int
) -> Optional[tuple[list[str], list[str]]]:
    """Ask the model per chunk; ``None`` when it gave us nothing usable.

    A reply is accepted only if it is a mapping with at least one usable item.
    Claims keep their text when the quote is present but do not survive a quote
    the chunk does not contain — the same evidence rule the formation path uses,
    because a fabricated quote is worse than no claim.
    """
    points: list[str] = []
    claims: list[str] = []
    seen_points: set[str] = set()
    seen_claims: set[str] = set()
    got_anything = False
    for chunk in list(chunks)[:MAX_LLM_CHUNKS]:
        if len(points) >= limit and len(claims) >= limit:
            break
        try:
            reply = llm.complete_json(
                task="ingest_key_points",
                system=_LLM_SYSTEM,
                user=chunk,
                schema=_LLM_SCHEMA,
                max_tokens=1200,
            )
        except Exception:  # a backend bug must not fail the ingest
            continue
        if not isinstance(reply, dict):
            continue
        for raw_point in reply.get("key_points") or []:
            point = _clean(str(raw_point))
            if not point or point.casefold() in seen_points:
                continue
            seen_points.add(point.casefold())
            points.append(point)
            got_anything = True
            if len(points) >= limit:
                break
        for raw_claim in reply.get("claims") or []:
            if not isinstance(raw_claim, dict):
                continue
            content = _clean(str(raw_claim.get("content") or ""))
            quote = str(raw_claim.get("evidence_quote") or "").strip()
            if not content or len(content) > 300 or content.casefold() in seen_claims:
                continue
            if quote and quote not in chunk:
                continue  # fabricated evidence: the claim is dropped
            seen_claims.add(content.casefold())
            claims.append(content)
            got_anything = True
            if len(claims) >= limit:
                break
    return (points, claims) if got_anything else None


def _clean(text: str) -> str:
    return " ".join(text.split()).strip()


def key_points(text: str, *, llm: Any = None, limit: int = MAX_CLAIMS) -> KeyPoints:
    """Appendix C.6's outputs, deterministic unless an available *llm* answers."""
    if llm is not None:
        got = _from_llm(_chunks_for_llm(text), llm, limit=limit)
        if got is not None:
            points, claims = got
            # A model that returns points but no claims still gets a note; the
            # claim side falls back rather than proposing nothing.
            if not claims:
                _, claims = _deterministic(text, limit=limit)
            return KeyPoints(tuple(points[:limit]), tuple(claims[:limit]), from_llm=True)
    points, claims = _deterministic(text, limit=limit)
    return KeyPoints(tuple(points), tuple(claims), from_llm=False)


def _chunks_for_llm(text: str) -> tuple[str, ...]:
    return chunk_text(text)


# --- the note ---------------------------------------------------------------


def build_note(source: Source, points: KeyPoints, *, entities: Sequence[str] = ()) -> tuple[str, str]:
    """Render the one source note. Returns ``(title, body)``.

    The body is chunked by :func:`chunk_text` so a long article stays readable,
    and it is honest about two things a reader would otherwise have to guess: a
    truncation, and whether the key points came from a model.
    """
    title = f"Source - {source.title}"
    lines: list[str] = [f"**Source:** {source.url or 'local file'}", ""]
    if source.truncated:
        lines.append(
            f"**Truncated:** kept the first {len(source.text):,} of "
            f"{source.original_chars:,} characters"
        )
        lines.append("")
    if points.points:
        lines.append("## Key Points")
        lines.append("")
        lines.extend(f"- {point}" for point in points.points)
        lines.append("")
    for index, chunk in enumerate(source.chunks, start=1):
        lines.append(f"## Chunk {index}")
        lines.append("")
        lines.append(chunk)
        lines.append("")
    if entities:
        # Plain text on purpose: a wikilink here would resurrect the v2 bug this
        # card removes, where every capitalised phrase became a note.
        lines.append("## Entities")
        lines.append("")
        lines.extend(f"- {name}" for name in entities)
        lines.append("")
    if points.from_llm:
        lines.append("*Key points and claims were extracted with the configured LLM.*")
        lines.append("")
    return title, "\n".join(lines).rstrip() + "\n"


# --- the store half ---------------------------------------------------------


@dataclass
class QueueReport:
    """What the store accepted, and which entities the claims mention."""

    pending_ids: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def queue_claims(
    engine: Any,
    claims: Sequence[str],
    *,
    url: str = "",
    domain: str = "Knowledge",
    actor: str = "ingest",
) -> QueueReport:
    """Write claims as ``pending`` memories and link their entity mentions.

    ``engine.remember(source="ingest")`` routes through ``evaluate_write``, which
    quarantines the source — so every claim lands ``pending`` with
    ``pending_reason="ingest_requires_review"`` and never reaches recall. The
    claim's ``evidence`` is the source URL, the card's rule.

    Entity mentions go through :class:`~em.store.entities.EntityLinker`, which is
    the whole point of the card: a known entity is linked, a new phrase is only
    *proposed* until it is seen in a second memory, and nothing here creates a
    vault note. On a v2 store there is no entity graph to link into, so the
    claims are queued and the entity half is reported empty.
    """
    report = QueueReport()
    evidence = {"evidence": url} if _is_v3(engine) else {}
    for claim in claims:
        try:
            memory_id = engine.remember(
                content=claim,
                source=INGEST_SOURCE,
                domain=domain,
                tags=["ingest"],
                actor=actor,
                **evidence,
            )
        except (ValueError, TypeError) as exc:  # a policy block or a bad draft
            report.skipped.append(f"{claim[:60]}: {exc}")
            continue
        report.pending_ids.append(memory_id)

    report.entities = _link_mentions(engine, report.pending_ids) if _is_v3(engine) else []
    return report


def _is_v3(engine: Any) -> bool:
    """True for the v3 facade, which is the only engine that has an entity graph."""
    from ..facade.engine import V3Engine

    return isinstance(engine, V3Engine)


def _link_mentions(engine: Any, memory_ids: Sequence[str]) -> list[str]:
    """Link each queued claim through the facade's entity linker.

    Imported here, and only here, so a v2 run (no ``em.store`` rows to join)
    pays nothing for a v3 module.
    """
    if not memory_ids:
        return []
    from ..formation.entity_linker import EntityLinker
    from ..store.memories import MemoryStore

    names: list[str] = []
    seen: set[str] = set()
    with engine.store.transaction() as conn:
        linker = EntityLinker(conn, engine.scope)
        store = MemoryStore(conn)
        for memory_id in memory_ids:
            row = store.get(memory_id)
            if row is None:
                continue
            for entity_id in linker.link(row):
                if entity_id in seen:
                    continue
                seen.add(entity_id)
                name = linker.store.entity_card(entity_id, engine.scope)
                names.append(str(name["name"]) if name else entity_id)
    return names
