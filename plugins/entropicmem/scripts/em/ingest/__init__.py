"""EM-607 — ingest v2: HTML to text, one source note, pending claims.

The card's shape, in one sentence: **read a document, write one chunked note
under ``Sources/``, and propose its claims as ``pending`` memories linked to the
entities they mention — never a note per capitalised phrase.**

Modules:

* :mod:`em.ingest.html_text` — the stdlib-parser HTML to text conversion.
* :mod:`em.ingest.article` — the size caps, chunking, Appendix C.6 key points,
  the note body, and the store half (``pending`` claims via the write policy,
  entity mentions via ``EntityLinker``).
"""

from __future__ import annotations

from .article import (
    CHUNK_CHARS,
    INGEST_SOURCE,
    MAX_CLAIMS,
    MAX_SOURCE_BYTES,
    MAX_TEXT_CHARS,
    SOURCES_FOLDER,
    KeyPoints,
    QueueReport,
    Source,
    SourceTooLarge,
    build_note,
    cap_text,
    check_source_size,
    chunk_text,
    key_points,
    prepare,
    queue_claims,
)
from .html_text import ArticleText, html_to_text

__all__ = [
    "CHUNK_CHARS",
    "INGEST_SOURCE",
    "MAX_CLAIMS",
    "MAX_SOURCE_BYTES",
    "MAX_TEXT_CHARS",
    "SOURCES_FOLDER",
    "ArticleText",
    "KeyPoints",
    "QueueReport",
    "Source",
    "SourceTooLarge",
    "build_note",
    "cap_text",
    "check_source_size",
    "chunk_text",
    "html_to_text",
    "key_points",
    "prepare",
    "queue_claims",
]
