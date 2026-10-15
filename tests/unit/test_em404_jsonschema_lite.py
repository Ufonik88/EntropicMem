"""EM-404: ``em.util.jsonschema_lite`` — the tool-argument validator.

The validator is the card's foundation: every tool call is validated against
Appendix B's schema before a handler sees it (types, enums, ``maxLength``,
``maxItems``, numeric bounds — the bounds clamp, the rest error). The rules are
§4.4's: string args are length-capped, integers clamped, unknown args ignored
*with a warning in the response*, and every error names the argument and what
was expected, so the model can fix its call.

Rules: invented data only.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.util.jsonschema_lite import ArgumentError, validate_arguments  # noqa: E402

SCHEMA = {
    "name": "x",
    "parameters": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "maxLength": 4000},
            "kind": {"type": "string", "enum": ["fact", "preference", "note"]},
            "importance": {"type": "number", "minimum": 0, "maximum": 1},
            "limit": {"type": "integer", "minimum": 1, "maximum": 25},
            "pinned": {"type": "boolean"},
            "ids": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
            "sources": {
                "type": "array",
                "items": {"type": "string", "enum": ["memories", "episodes", "notes", "shared"]},
            },
        },
        "required": ["content"],
    },
}

EMPTY_SCHEMA = {"name": "stats", "parameters": {"type": "object", "properties": {}}}


def _error(schema, args) -> ArgumentError:
    with pytest.raises(ArgumentError) as found:
        validate_arguments(schema, args)
    return found.value


# --- hard errors -------------------------------------------------------------


def test_arguments_must_be_an_object():
    for bad in ("content", 3, [1, 2], None):
        err = _error(SCHEMA, bad)
        assert "object" in str(err)


def test_missing_required_names_the_field():
    err = _error(SCHEMA, {})
    assert "content" in str(err)
    assert "required" in str(err)


def test_none_reads_as_not_provided_optional():
    cleaned, warnings = validate_arguments(SCHEMA, {"content": "x", "pinned": None})
    assert "pinned" not in cleaned
    assert warnings == []


def test_none_reads_as_not_provided_required():
    err = _error(SCHEMA, {"content": None})
    assert "content" in str(err)


def test_wrong_type_names_field_expected_and_got():
    err = _error(SCHEMA, {"content": "x", "limit": "ten"})
    message = str(err)
    assert "limit" in message
    assert "integer" in message
    assert "string" in message
    assert "'ten'" in message


def test_booleans_are_not_integers():
    err = _error(SCHEMA, {"content": "x", "limit": True})
    assert "limit" in str(err)


def test_float_is_not_an_integer():
    err = _error(SCHEMA, {"content": "x", "limit": 2.5})
    assert "limit" in str(err)


def test_enum_error_lists_every_choice():
    err = _error(SCHEMA, {"content": "x", "kind": "junk"})
    message = str(err)
    assert "kind" in message
    for choice in ("fact", "preference", "note"):
        assert choice in message


def test_array_item_type_is_validated_and_named_by_index():
    err = _error(SCHEMA, {"content": "x", "ids": ["a", 2]})
    message = str(err)
    assert "ids[1]" in message
    assert "string" in message


def test_array_item_enum_is_validated_and_named_by_index():
    err = _error(SCHEMA, {"content": "x", "sources": ["memories", "nope"]})
    message = str(err)
    assert "sources[1]" in message
    for source in ("memories", "episodes", "notes", "shared"):
        assert source in message


def test_a_bare_string_is_not_an_array():
    err = _error(SCHEMA, {"content": "x", "ids": "abc"})
    assert "ids" in str(err)


# --- clamping: value fixed, warning recorded ---------------------------------


def test_maxlength_truncates_and_warns():
    cleaned, warnings = validate_arguments(SCHEMA, {"content": "x" * 4010})
    assert len(cleaned["content"]) == 4000
    assert len(warnings) == 1
    assert "4000" in warnings[0]
    assert "content" in warnings[0]


def test_string_at_maxlength_is_clean():
    _, warnings = validate_arguments(SCHEMA, {"content": "x" * 4000})
    assert warnings == []


def test_number_max_clamps():
    cleaned, warnings = validate_arguments(SCHEMA, {"content": "x", "importance": 1.5})
    assert cleaned["importance"] == 1.0
    assert any("importance" in w and "1" in w for w in warnings)


def test_number_min_clamps():
    cleaned, warnings = validate_arguments(SCHEMA, {"content": "x", "importance": -2})
    assert cleaned["importance"] == 0.0
    assert any("importance" in w for w in warnings)


def test_integer_limits_clamp():
    cleaned, warnings = validate_arguments(SCHEMA, {"content": "x", "limit": 100})
    assert cleaned["limit"] == 25
    assert any("limit" in w and "25" in w for w in warnings)
    cleaned, warnings = validate_arguments(SCHEMA, {"content": "x", "limit": 0})
    assert cleaned["limit"] == 1
    assert any("limit" in w for w in warnings)


def test_maxitems_truncates_and_warns():
    cleaned, warnings = validate_arguments(SCHEMA, {"content": "x", "ids": [f"i{n}" for n in range(25)]})
    assert len(cleaned["ids"]) == 20
    assert any("ids" in w and "20" in w for w in warnings)


# --- unknown args: ignored, with a warning -----------------------------------


def test_unknown_arguments_warn_and_are_dropped():
    cleaned, warnings = validate_arguments(SCHEMA, {"content": "x", "domain": "Knowledge"})
    assert "domain" not in cleaned
    assert len(warnings) == 1
    assert "domain" in warnings[0]


def test_empty_schema_warns_on_everything():
    cleaned, warnings = validate_arguments(EMPTY_SCHEMA, {"anything": 1})
    assert cleaned == {}
    assert len(warnings) == 1
    assert "anything" in warnings[0]


def test_warnings_accumulate():
    cleaned, warnings = validate_arguments(
        SCHEMA, {"content": "x" * 4100, "limit": 999, "zzz": 1}
    )
    assert len(warnings) == 3
    assert len(cleaned["content"]) == 4000
    assert cleaned["limit"] == 25


def test_a_clean_call_is_clean():
    args = {
        "content": "the staging host is falcon-2",
        "kind": "fact",
        "importance": 0.8,
        "limit": 10,
        "pinned": False,
        "ids": ["a"],
        "sources": ["memories"],
    }
    cleaned, warnings = validate_arguments(SCHEMA, args)
    assert cleaned == args
    assert warnings == []


def test_unknown_key_and_none_do_not_interact():
    cleaned, warnings = validate_arguments(SCHEMA, {"content": "x", "pinned": None, "zzz": 1})
    assert cleaned == {"content": "x"}
    assert len(warnings) == 1
