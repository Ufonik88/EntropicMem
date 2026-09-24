"""Multimodal-safe message normalisation (EM-101, H2).

``message_text`` flattens any host message/content shape to plain text and
never raises. A single multimodal (list) payload used to blow up the prefetch
fingerprint with a swallowed TypeError, silently killing memory injection for
the whole session.
"""

from __future__ import annotations

from typing import Any

_TEXT_KEYS = ("text", "input_text", "output_text")


def message_text(msg: Any) -> str:
    """Flatten one message or content payload to plain text ('' for non-text).

    Handles: str, dicts with ``text``/``input_text``/``output_text`` or
    nested ``content``, lists/tuples of parts, None, and junk (returns '').
    """
    if msg is None:
        return ""
    if isinstance(msg, str):
        return msg
    if isinstance(msg, dict):
        for key in _TEXT_KEYS:
            text = msg.get(key)
            if isinstance(text, str):
                return text
        return message_text(msg.get("content"))
    if isinstance(msg, (list, tuple)):
        return " ".join(t for t in (message_text(part) for part in msg) if t)
    return ""
