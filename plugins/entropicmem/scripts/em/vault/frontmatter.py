"""EM-602 — frontmatter and wikilink robustness (S6, slice 1).

The vault is hand-editable Markdown: a person edits it, Obsidian edits it, and
the projector rewrites marked regions of it. Two things therefore have to be
exactly right, or a note corrupts itself silently:

**The frontmatter block round-trips.** The old writer built its lines with
f-strings — ``title: "{title}"`` — so a title containing ``"``, a backslash or
a newline produced a block that read back differently, or did not parse at all,
while the note still looked saved. This module quotes and escapes only what
YAML requires, keeps plain text plain (``title: Test Title``), and falls back
to a **block scalar** for anything multi-line. ``:`/``#``/leading ``-`` and
friends are quoted; date-like and number-like strings are quoted so YAML never
re-reads them as a date or an int.

**A ``---`` in the body is not a delimiter.** The old reader split the whole
file on ``---``, so a horizontal rule or a code fence in the note body
truncated it. :func:`split_frontmatter` only accepts a delimiter at the very
start of the file and on a line of its own.

The reader prefers **PyYAML** when it is importable and otherwise uses the
subset parser in this module, which understands exactly what the writer emits
(``tests/unit/test_em602_frontmatter.py`` round-trips the two against each
other). The v2 module ``em_internal.vault`` keeps its public shape but delegates
here, so the vault and the projector share one implementation.

Stdlib only; PyYAML is an optional, lazily imported accelerator and nothing at
import time touches it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "DELIMITER",
    "Wikilink",
    "dump_frontmatter",
    "dump_scalar",
    "load_frontmatter",
    "parse_wikilinks",
    "split_frontmatter",
]

#: The frontmatter fence. A line must be exactly this to open or close a block.
DELIMITER = "---"

#: The four wikilink shapes: ``[[Target]]``, ``[[Target|Alias]]``,
#: ``[[Target#Heading]]``, ``[[Target^block]]``, plus the ``![[embed]]`` prefix.
_WIKILINK = re.compile(r"(!?)\[\[([^\[\]]+?)\]\]")

#: Keys that can be written bare. Anything else is quoted.
_PLAIN_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")

#: Characters that are unambiguous in a *block* context but which this module
#: deliberately refuses to write plain: ``:``, ``#``, ``"``/``'``, ``\``, ``,``,
#: ``[``/``]``/``{``/``}`` are all either flow-structural or comment/tag markers,
#: and quoting them is always safe. A plain scalar must start and end with a
#: word character.
_PLAIN_SAFE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9 _./@()+&=;!?%^*~<>-]*[A-Za-z0-9_./@()+&=;!?%^*~<>-])?$"
)

#: Values YAML would read as something other than a string.
_RESERVED_PLAIN = {"true", "false", "null", "~", "yes", "no", "on", "off", "y", "n"}
_NUMBER_LIKE = re.compile(r"^[-+]?(?:\d+|\d*\.\d+(?:[eE][-+]?\d+)?|\.inf|\.nan)$")
_DATE_LIKE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[Tt ].*)?$")


# ── splitting ────────────────────────────────────────────────────────────────


def split_frontmatter(text: str) -> Tuple[Optional[str], str]:
    """``(block, body)`` — the frontmatter text without its fences, or ``None``.

    A fence only counts on the first line and on a line of its own: a ``---``
    in the body, an indented one, ``----`` or ``--- `` never opens or closes a
    block. An unterminated block is not frontmatter at all — the whole text is
    the body, exactly as ``em_internal.vault`` behaved.
    """
    if not text:
        return None, text
    lines = text.splitlines(keepends=True)
    if lines[0].rstrip("\r\n") != DELIMITER:
        return None, text
    for index in range(1, len(lines)):
        if lines[index].rstrip("\r\n") == DELIMITER:
            block = "".join(lines[1:index])
            body = "".join(lines[index + 1 :])
            return block, body
    return None, text


def load_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """``(metadata, body)`` — parse the block with PyYAML when available.

    PyYAML is preferred; when it is absent, or rejects a block it cannot read,
    the subset parser takes over, so a hand-written block that is "YAML-ish"
    still yields what it can rather than raising.
    """
    block, body = split_frontmatter(text)
    if block is None:
        return {}, text
    return _parse_block(block), body


# ── writing ──────────────────────────────────────────────────────────────────


def _quote(value: str) -> str:
    """A single-line double-quoted YAML scalar with the escapes the reader undoes."""
    out = ['"']
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif ord(ch) < 0x20:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _needs_quotes(value: str) -> bool:
    if value == "" or value != value.strip():
        return True
    if not _PLAIN_SAFE.match(value):
        return True
    low = value.lower()
    if low in _RESERVED_PLAIN:
        return True
    return bool(_NUMBER_LIKE.match(value) or _DATE_LIKE.match(value))


def _inline(value: Any) -> str:
    """One scalar on one line — never a block scalar (lists need this)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return value if not _needs_quotes(value) else _quote(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_inline(item) for item in value) + "]"
    raise TypeError(f"cannot render {type(value).__name__} as a YAML scalar")


def _block_scalar(value: str) -> str:
    """``|``/``|-`` plus the indented lines of a multi-line string."""
    keep = value.endswith("\n")
    body = value[:-1] if keep else value
    header = "|" if keep else "|-"
    indented = "\n".join("  " + line for line in body.split("\n"))
    return f"{header}\n{indented}"


def _block_safe(value: str) -> bool:
    """True when a block scalar preserves *value* exactly.

    A block scalar's indentation is inferred from its first non-empty line, so
    a line that itself begins or ends with whitespace is ambiguous. Those go
    through the escaped one-line form instead — always safe, just less pretty.
    """
    for line in value.split("\n"):
        if line and line != line.strip():
            return False
    return True


def dump_scalar(value: Any) -> str:
    """Render one value: a block scalar for multi-line strings, else inline."""
    if isinstance(value, str) and "\n" in value and _block_safe(value):
        return _block_scalar(value)
    return _inline(value)


def dump_frontmatter(mapping: Mapping[str, Any]) -> str:
    """Render ``mapping`` as a fenced frontmatter block (no trailing newline)."""
    lines = [DELIMITER]
    for key, value in mapping.items():
        name = key if isinstance(key, str) and _PLAIN_KEY.match(key) else _inline(key)
        lines.append(f"{name}: {dump_scalar(value)}")
    lines.append(DELIMITER)
    return "\n".join(lines)


# ── reading (the subset parser) ──────────────────────────────────────────────


def _yaml_module():
    """PyYAML, imported lazily so importing this module never needs it."""
    try:
        import yaml  # noqa: PLC0415
    except Exception:  # pragma: no cover - absence is the tested path
        return None
    return yaml


def _normalise(value: Any) -> Any:
    """Dates stay ISO **strings**, never ``date`` objects.

    A hand-written block may carry ``updated: 2026-01-02`` unquoted; PyYAML
    then hands back a ``datetime.date`` and every caller that treats ``updated``
    as a string (``date.fromisoformat(note.updated)``) breaks. The vault's
    metadata fields are strings, so normalise the YAML typing away rather than
    let a hand edit change a field's type.
    """
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _parse_block(block: str) -> Dict[str, Any]:
    if not block.strip():
        return {}
    yaml = _yaml_module()
    if yaml is not None:
        try:
            data = yaml.safe_load(block)
        except Exception:
            data = None
        if isinstance(data, dict):
            return {key: _normalise(value) for key, value in data.items()}
    return _parse_subset(block)


def _split_flow(inner: str) -> List[str]:
    """Split a flow sequence on commas that are not inside quotes."""
    items: List[str] = []
    buf: List[str] = []
    quote = ""
    index = 0
    while index < len(inner):
        ch = inner[index]
        if quote:
            buf.append(ch)
            if quote == '"' and ch == "\\" and index + 1 < len(inner):
                buf.append(inner[index + 1])
                index += 2
                continue
            if ch == quote:
                if quote == "'" and index + 1 < len(inner) and inner[index + 1] == "'":
                    buf.append("'")
                    index += 2
                    continue
                quote = ""
            index += 1
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
            index += 1
            continue
        if ch == ",":
            items.append("".join(buf))
            buf = []
            index += 1
            continue
        buf.append(ch)
        index += 1
    items.append("".join(buf))
    return [item.strip() for item in items if item.strip() != ""]


def _unescape_double(value: str) -> str:
    out: List[str] = []
    index = 0
    while index < len(value):
        ch = value[index]
        if ch == "\\" and index + 1 < len(value):
            nxt = value[index + 1]
            simple = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/"}
            if nxt in simple:
                out.append(simple[nxt])
                index += 2
                continue
            if nxt == "u" and len(value) >= index + 6:
                try:
                    out.append(chr(int(value[index + 2 : index + 6], 16)))
                    index += 6
                    continue
                except ValueError:
                    pass
            out.append(nxt)
            index += 2
            continue
        out.append(ch)
        index += 1
    return "".join(out)


def _parse_scalar(text: str) -> Any:
    text = text.strip()
    if text == "":
        return None
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return _unescape_double(text[1:-1])
    if len(text) >= 2 and text[0] == "'" and text[-1] == "'":
        return text[1:-1].replace("''", "'")
    if text.startswith("[") and text.endswith("]"):
        return [_parse_scalar(item) for item in _split_flow(text[1:-1])]
    low = text.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "~"):
        return None
    if _NUMBER_LIKE.match(text) and "inf" not in low and "nan" not in low:
        try:
            return int(text)
        except ValueError:
            try:
                return float(text)
            except ValueError:
                return text
    return text


def _collect_block(lines: Sequence[str], index: int) -> Tuple[str, int]:
    """The indented lines of a block scalar, dedented, plus the next index."""
    collected: List[str] = []
    while index < len(lines):
        line = lines[index]
        if line.strip() == "":
            collected.append("")
            index += 1
            continue
        if line[:1] in (" ", "\t"):
            collected.append(line)
            index += 1
            continue
        break
    indents = [len(ln) - len(ln.lstrip(" ")) for ln in collected if ln.strip()]
    base = min(indents) if indents else 0
    text = "\n".join(ln[base:] if ln.strip() else "" for ln in collected)
    return text, index


def _render_block(header: str, text: str) -> str:
    """Rebuild the string a block-scalar header describes.

    Chomping is the part the naive version got wrong: ``|-`` strips the
    trailing line break, a bare ``|`` clips to exactly one, and ``|+`` keeps
    every one — and the block always carries a trailing empty line from the
    document's own final newline, so the three differ in practice.
    """
    if header.startswith(">"):
        folded: List[str] = []
        buffer: List[str] = []
        for line in text.split("\n"):
            if line.strip():
                buffer.append(line.strip())
            else:
                folded.append(" ".join(buffer))
                buffer = []
        folded.append(" ".join(buffer))
        text = "\n".join(part for part in folded if part)
    stripped = text.rstrip("\n")
    if header.endswith("-"):
        return stripped
    if header.endswith("+"):
        return text
    return stripped + "\n"


def _collect_list(lines: Sequence[str], index: int) -> Tuple[Optional[List[str]], int]:
    items: List[str] = []
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped == "-":
            items.append("")
            index += 1
            continue
        if stripped.startswith("- "):
            items.append(stripped[2:])
            index += 1
            continue
        break
    return (items if items else None), index


def _parse_subset(block: str) -> Dict[str, Any]:
    """The fallback reader: exactly the subset :func:`dump_frontmatter` emits."""
    data: Dict[str, Any] = {}
    lines = block.split("\n")
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        index += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[:1] in (" ", "\t") or line.lstrip().startswith("- "):
            continue
        key, sep, rest = line.partition(":")
        if not sep:
            continue
        key = key.strip()
        if len(key) >= 2 and key[0] == key[-1] and key[0] in "\"'":
            key = _parse_scalar(key)
        rest = rest.strip()
        if rest[:1] in ("|", ">"):
            text, index = _collect_block(lines, index)
            data[key] = _render_block(rest, text)
            continue
        if rest == "":
            items, index = _collect_list(lines, index)
            data[key] = [_parse_scalar(item) for item in items] if items is not None else None
            continue
        data[key] = _parse_scalar(rest)
    return data


# ── wikilinks ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Wikilink:
    """One parsed wikilink.

    ``target`` is the note the link points at (alias, heading and block are
    stripped), which is what the graph index resolves against note titles.
    """

    target: str
    alias: str = ""
    heading: str = ""
    block: str = ""
    embed: bool = False
    raw: str = ""


def parse_wikilinks(text: str) -> List[Wikilink]:
    """Every ``[[…]]``/``![[…]]`` in *text*, in order, duplicates included."""
    links: List[Wikilink] = []
    for match in _WIKILINK.finditer(text or ""):
        inner = match.group(2)
        left, sep, alias = inner.partition("|")
        target = left
        heading = ""
        block = ""
        cut = min(
            (idx for idx in (target.find("#"), target.find("^")) if idx != -1),
            default=-1,
        )
        if cut != -1:
            fragment = target[cut:]
            target = target[:cut]
            if fragment.startswith("#"):
                head, block_sep, tail = fragment[1:].partition("^")
                heading = head
                if block_sep:
                    block = tail
            elif fragment.startswith("^"):
                block = fragment[1:]
        links.append(
            Wikilink(
                target=target,
                alias=alias if sep else "",
                heading=heading,
                block=block,
                embed=match.group(1) == "!",
                raw=match.group(0),
            )
        )
    return links
