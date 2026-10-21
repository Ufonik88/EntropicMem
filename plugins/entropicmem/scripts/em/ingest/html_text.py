"""EM-607 — HTML to readable text, via the stdlib parser.

The v2 ingest path stripped tags with three regexes (``<script>…</script>``,
``<style>…</style>``, then ``<[^>]+>``). That is not a parser: a ``<script>``
containing a newline was dropped, a ``<script>`` on one line with a ``>`` inside
a string was not, headings and list items were flattened into the surrounding
prose, and an entity like ``&amp;`` stayed encoded. This module replaces it.

What survives, because it is the article: headings (as ``#`` … ``######``),
list items (as ``-``), and paragraph text. What is dropped, because it is
chrome: ``script``, ``style``, ``nav`` and ``footer`` — the card's four. The
document title is captured separately so a caller does not have to guess a
name from the URL.

Deliberately stdlib-only (``html.parser``) and never a dependency: ingest runs
from the CLI on a box that may have nothing installed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

__all__ = ["HTML_TEXT_MAX_CHARS", "ArticleText", "html_to_text", "normalise_text"]

#: Elements whose *content* is not article text. The card names all four;
#: everything else is flattened into the flow rather than dropped, because a
#: ``div`` around a paragraph is structure, not noise.
SKIP_TAGS = frozenset({"script", "style", "nav", "footer"})

#: Elements that end the current run of text. A flush is what creates a
#: paragraph boundary, so the block set is what decides where text breaks.
BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }
)

_HEADING_RE = re.compile(r"^h([1-6])$")

#: A hard ceiling on the extracted text, applied by the caller's size cap as
#: well; here it only stops a pathological document from being held in memory
#: as one string. It is intentionally far above the ingest card's cap.
HTML_TEXT_MAX_CHARS = 4_000_000


@dataclass(frozen=True)
class ArticleText:
    """The two things an ingest needs from a page."""

    text: str
    title: str


class _ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._buffer: list[str] = []
        self._skip_depth = 0
        self._heading = 0
        self._list_item = False
        self._in_title = False
        self._title: list[str] = []

    # -- structure ---------------------------------------------------------

    def _flush(self) -> None:
        raw = "".join(self._buffer)
        self._buffer = []
        text = normalise_text(raw)
        if not text:
            return
        if self._heading:
            self._out.append(f"{'#' * self._heading} {text}")
        elif self._list_item:
            self._out.append(f"- {text}")
        else:
            self._out.append(text)
        # A list bullet applies to one item; a heading to one line.
        self._heading = 0
        self._list_item = False

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001 - stdlib signature
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = True
        elif _HEADING_RE.match(tag):
            self._flush()
            self._heading = int(tag[1])
        elif tag == "li":
            self._flush()
            self._list_item = True
        elif tag in BLOCK_TAGS:
            self._flush()

    def handle_startendtag(self, tag: str, attrs) -> None:  # noqa: ANN001
        # ``<br/>`` and ``<img/>``: a void block still ends the run.
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS:
            # Never let a stray ``</script>`` drive the depth negative.
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = False
        elif _HEADING_RE.match(tag) or tag in BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title.append(data)
            return
        if self._skip_depth:
            return
        self._buffer.append(data)

    # -- result ------------------------------------------------------------

    def result(self) -> ArticleText:
        self._flush()
        return ArticleText(
            text="\n\n".join(self._out).strip(),
            title=normalise_text("".join(self._title)),
        )


def normalise_text(raw: str) -> str:
    """Collapse whitespace inside a run of text, keeping words apart.

    ``textwrap`` semantics, not ``strip``: an inline ``<b>`` boundary leaves two
    adjacent words with no space between them, so runs are joined with one
    space rather than concatenated.
    """
    return re.sub(r"\s+", " ", raw).strip()


def html_to_text(raw: str) -> ArticleText:
    """Parse *raw* HTML into text plus its ``<title>``.

    Malformed input is the normal case on the web, so the parser is fed in one
    pass and whatever it understood is returned: an unclosed ``<p>`` still
    breaks the paragraph, an unclosed ``<script>`` is dropped to the end, and a
    truncated document simply ends. Input is capped first so a 100 MB page
    cannot make the buffer the problem.
    """
    parser = _ArticleParser()
    parser.feed(raw[:HTML_TEXT_MAX_CHARS])
    parser.close()
    return parser.result()
