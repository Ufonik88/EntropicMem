"""EM-404 validation slice: the v3 tool surface, its alias map and its rules.

The card's behavioural Spec/AC, pinned at the surface level:

* the nine Appendix B schemas are what ``get_tool_schemas`` serves, verbatim in
  name/required/enum/bound terms (descriptions are part of the model-facing
  contract, so the tool-level ones are pinned word for word);
* legacy names map to the new tools for one minor version and the response
  says so (``"deprecated_tool": "<old>"``);
* every call is validated against the target schema before a handler sees it —
  types, enums, ``maxLength`` and ``maxItems`` caps, numeric clamping — with
  errors that name the argument, and unknown arguments are ignored with a
  warning in the response (§4.4);
* write tools in non-primary contexts return ``reason_code: "writes_disabled"``;
* random arguments never raise out of ``handle_tool_call``.

Store-level behaviour (search results, forget's token flow, …) lives in
``tests/unit/test_em404_tool_behaviour.py``.

Rules: invented data only.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
for entry in (str(REPO), str(SCRIPTS)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from plugins.entropicmem import EntropicMemMemoryProvider  # noqa: E402


def _provider(**config) -> EntropicMemMemoryProvider:
    return EntropicMemMemoryProvider(config={"core_memory_enabled": False, **config})


def _call(provider: EntropicMemMemoryProvider, name: str, args: dict) -> dict:
    out = provider.handle_tool_call(name, args)
    assert isinstance(out, str), f"handle_tool_call returned {type(out).__name__}"
    return json.loads(out)


# --- the nine schemas --------------------------------------------------------

SURFACE = [
    "entropicmem_remember",
    "entropicmem_search",
    "entropicmem_update",
    "entropicmem_forget",
    "entropicmem_timeline",
    "entropicmem_entity",
    "entropicmem_profile",
    "entropicmem_review",
    "entropicmem_stats",
]

#: Appendix B, tool by tool: the constrained keywords that must not drift.
SCHEMA_PINS: dict[str, dict] = {
    "entropicmem_remember": {
        "required": ["content"],
        "props": {
            "content": {
                "type": "string",
                "maxLength": 4000,
                "description": "Self-contained statement, full detail for technical facts.",
            },
            "kind": {
                "type": "string",
                "enum": ["fact", "preference", "profile", "procedure", "event", "constraint", "note"],
                "description": "Default fact.",
            },
            "importance": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "0.9 identity/critical, 0.7 useful, 0.4 minor. Default 0.6.",
            },
            "valid_from": {
                "type": "string",
                "description": "ISO date when this became true (optional).",
            },
            "pinned": {
                "type": "boolean",
                "description": "Always surface (use sparingly, e.g. standing constraints).",
            },
            "supersedes": {
                "type": "string",
                "description": "Id of a memory this replaces (optional).",
            },
            "visibility": {
                "type": "string",
                "enum": ["user", "chat", "profile"],
                "description": "Default user.",
            },
        },
    },
    "entropicmem_search": {
        "required": [],
        "props": {
            "query": {"type": "string", "maxLength": 500},
            "ids": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
            "kinds": {"type": "array", "items": {"type": "string"}},
            "sources": {
                "type": "array",
                "items": {"type": "string", "enum": ["memories", "episodes", "notes", "shared"]},
                "description": "Default [memories, episodes].",
            },
            "time_from": {"type": "string"},
            "time_to": {"type": "string"},
            "include_history": {
                "type": "boolean",
                "description": "Include superseded versions.",
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 25},
        },
    },
    "entropicmem_update": {
        "required": ["id", "content"],
        "props": {
            "id": {"type": "string"},
            "content": {"type": "string", "maxLength": 4000},
            "mode": {"type": "string", "enum": ["supersede", "edit"]},
            "importance": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string", "maxLength": 300},
        },
    },
    "entropicmem_forget": {
        "required": [],
        "props": {
            "id": {"type": "string"},
            "query": {"type": "string", "maxLength": 300},
            "confirm_token": {"type": "string"},
            "reason": {"type": "string", "maxLength": 300},
        },
    },
    "entropicmem_timeline": {
        "required": [],
        "props": {
            "time_from": {"type": "string"},
            "time_to": {"type": "string"},
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 25},
        },
    },
    "entropicmem_entity": {
        "required": ["name"],
        "props": {
            "name": {"type": "string", "maxLength": 120},
            "include_history": {"type": "boolean"},
        },
    },
    "entropicmem_profile": {
        "required": ["action"],
        "props": {
            "action": {"type": "string", "enum": ["read", "patch"]},
            "target": {"type": "string", "enum": ["persona", "user_profile"]},
            "old_text": {"type": "string"},
            "new_text": {"type": "string"},
        },
    },
    "entropicmem_review": {
        "required": ["action"],
        "props": {
            "action": {"type": "string", "enum": ["list_pending", "promote", "discard", "feedback", "consolidate_preview", "restore"]},
            "id": {"type": "string"},
            "signal": {"type": "string", "enum": ["helpful", "unhelpful", "wrong", "outdated"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 25},
        },
    },
    "entropicmem_stats": {"required": [], "props": {}},
}

#: The tool-level descriptions are model-facing text — pinned word for word.
TOOL_DESCRIPTIONS = {
    "entropicmem_remember": (
        "Save a durable memory about the user, their work, decisions, preferences, procedures "
        "or constraints. Use for information that will matter in future sessions. Do NOT use "
        "for secrets or passing chit-chat. To correct an existing memory use entropicmem_update instead."
    ),
    "entropicmem_search": (
        "Search long-term memory (memories, past session episodes, vault notes). Use before "
        "answering questions about the past, the user's preferences, or prior decisions. Also "
        "fetches specific ids."
    ),
    "entropicmem_update": (
        "Correct or replace an existing memory. mode=supersede keeps history (default, use when "
        "facts changed); mode=edit fixes wording/typos in place."
    ),
    "entropicmem_forget": (
        "Remove a memory that is wrong or that the user asked to forget. By id: immediate "
        "(recoverable). By query: returns candidates and a confirm_token; call again with "
        "confirm_token to apply."
    ),
    "entropicmem_timeline": "List what happened in a time range (sessions, decisions, events).",
    "entropicmem_entity": (
        "Everything known about a person, project, organisation, product or place: facts, "
        "relations, recent episodes."
    ),
    "entropicmem_profile": (
        "Read the core memory (persona and user profile). Patching is only allowed when enabled "
        "by the user."
    ),
    "entropicmem_review": (
        "Review memory the system is unsure about: list pending memories, promote or discard "
        "them, report feedback on a recalled memory, or preview consolidation."
    ),
    "entropicmem_stats": (
        "Memory health and statistics (counts by kind/status, pending, last jobs, recall metrics)."
    ),
}


def test_surface_is_the_nine_appendix_b_tools_in_order():
    schemas = _provider().get_tool_schemas()
    assert [s["name"] for s in schemas] == SURFACE


def test_each_schema_pins_its_constraints():
    schemas = {s["name"]: s for s in _provider().get_tool_schemas()}
    for name, pin in SCHEMA_PINS.items():
        params = schemas[name]["parameters"]
        assert params["type"] == "object"
        assert params.get("required", []) == pin["required"], name
        assert sorted(params["properties"]) == sorted(pin["props"]), name
        for field, expected in pin["props"].items():
            actual = params["properties"][field]
            for key, value in expected.items():
                assert actual.get(key) == value, f"{name}.{field}.{key}"


def test_tool_descriptions_are_the_appendix_text():
    schemas = {s["name"]: s for s in _provider().get_tool_schemas()}
    for name, description in TOOL_DESCRIPTIONS.items():
        assert schemas[name]["description"] == description, name


# --- the alias map -----------------------------------------------------------

LEGACY = (
    "entropicmem_recall",
    "entropicmem_get",
    "entropicmem_query",
    "entropicmem_patch_core",
    "entropicmem_consolidate",
)


def test_legacy_names_are_not_on_the_served_surface():
    served = {s["name"] for s in _provider().get_tool_schemas()}
    assert not (served & set(LEGACY))


@pytest.mark.parametrize("name", LEGACY)
def test_legacy_call_answers_and_says_so(name):
    # An uninitialized provider still answers through the mapped handler — and
    # the response says which old name was used.
    args = {
        "entropicmem_recall": {"query": "x"},
        "entropicmem_get": {"entropic_id": "abc"},
        "entropicmem_query": {"query": "x"},
        "entropicmem_patch_core": {"target": "persona", "old_text": "a"},
        "entropicmem_consolidate": {},
    }[name]
    payload = _call(_provider(), name, args)
    assert payload.get("deprecated_tool") == name


def test_get_alias_translates_to_search_by_ids(tmp_path):
    provider = _provider()
    # A missing store is fine: the assertion is on the translated call, which
    # is visible in the validation outcome — a bad limit must fail under
    # search's schema, not reach dispatch.
    payload = _call(provider, "entropicmem_get", {"entropic_id": "abc", "limit": "x"})
    assert payload["reason_code"] == "invalid_arguments"
    assert "limit" in payload["error"]


def test_recall_alias_validates_under_the_search_schema():
    payload = _call(_provider(), "entropicmem_recall", {"query": "x", "limit": "ten"})
    assert payload["reason_code"] == "invalid_arguments"
    assert "limit" in payload["error"]


def test_legacy_extra_args_are_ignored_with_a_warning():
    payload = _call(_provider(), "entropicmem_recall", {"query": "x", "domain": "Knowledge"})
    assert any("domain" in warning for warning in payload.get("warnings", []))


def test_unknown_tool_is_an_error():
    payload = _call(_provider(), "entropicmem_nope", {})
    assert "Unknown tool" in payload["error"]


# --- validation at the surface: every schema field ---------------------------

WRONG = {"string": 123, "number": "abc", "integer": "abc", "boolean": "yes", "array": "not-a-list"}

VALID = {
    "string": "ok",
    "number": 0.5,
    "integer": 5,
    "boolean": True,
    "array": ["ok"],
}

#: Per (tool, field): the value an enum or array needs to be considered valid.
VALID_OVERRIDES = {
    ("entropicmem_remember", "kind"): "fact",
    ("entropicmem_remember", "visibility"): "user",
    ("entropicmem_search", "sources"): ["memories"],
    ("entropicmem_update", "mode"): "supersede",
    ("entropicmem_profile", "action"): "read",
    ("entropicmem_profile", "target"): "persona",
    ("entropicmem_review", "action"): "list_pending",
    ("entropicmem_review", "signal"): "helpful",
}

#: Base args that satisfy each tool's required fields.
REQUIRED_BASE = {
    "entropicmem_remember": {"content": "a fact"},
    "entropicmem_update": {"id": "x", "content": "y"},
    "entropicmem_entity": {"name": "Falcon"},
    "entropicmem_profile": {"action": "read"},
    "entropicmem_review": {"action": "list_pending"},
}

FIELD_CASES = [
    (tool, field, spec)
    for tool, pin in SCHEMA_PINS.items()
    for field, spec in pin["props"].items()
]


@pytest.mark.parametrize("tool,field,spec", FIELD_CASES, ids=[f"{t}.{f}" for t, f, _ in FIELD_CASES])
def test_every_schema_field_rejects_the_wrong_type(tool, field, spec):
    args = dict(REQUIRED_BASE.get(tool, {}))
    args[field] = WRONG[spec["type"]]
    payload = _call(_provider(), tool, args)
    assert payload.get("reason_code") == "invalid_arguments", payload
    assert field in payload["error"]
    assert payload["ok"] is False


@pytest.mark.parametrize("tool,field,spec", FIELD_CASES, ids=[f"{t}.{f}" for t, f, _ in FIELD_CASES])
def test_every_schema_field_accepts_a_valid_value(tool, field, spec):
    args = dict(REQUIRED_BASE.get(tool, {}))
    args[field] = VALID_OVERRIDES.get((tool, field), VALID[spec["type"]])
    payload = _call(_provider(), tool, args)
    # No store, so the handler may still refuse — but never with a validation
    # error: the value itself must pass the schema.
    assert payload.get("reason_code") != "invalid_arguments", payload


def test_missing_required_field_is_a_validation_error():
    payload = _call(_provider(), "entropicmem_remember", {})
    assert payload.get("reason_code") == "invalid_arguments"
    assert "content" in payload["error"]


def test_unknown_argument_warns_on_a_clean_call():
    payload = _call(_provider(), "entropicmem_stats", {"nonsense": 1})
    assert any("nonsense" in w for w in payload.get("warnings", []))


def test_clamped_limit_reaches_the_handler_with_a_warning():
    # No store: the clamp itself is visible in the response warnings, and the
    # call gets past validation.
    payload = _call(_provider(), "entropicmem_search", {"query": "x", "limit": 99})
    assert payload.get("reason_code") != "invalid_arguments"
    assert any("limit" in w and "25" in w for w in payload.get("warnings", []))


# --- writes_disabled ---------------------------------------------------------

WRITE_CALLS = [
    ("entropicmem_remember", {"content": "x"}),
    ("entropicmem_update", {"id": "x", "content": "y"}),
    ("entropicmem_forget", {"id": "x"}),
    ("entropicmem_review", {"action": "promote", "id": "x"}),
    ("entropicmem_review", {"action": "discard", "id": "x"}),
    ("entropicmem_review", {"action": "feedback", "signal": "helpful", "id": "x"}),
    ("entropicmem_review", {"action": "restore", "id": "x"}),
    ("entropicmem_profile", {"action": "patch", "target": "persona", "old_text": "a", "new_text": "b"}),
]


@pytest.mark.parametrize("tool,args", WRITE_CALLS, ids=[f"{t}:{a.get('action', '')}" for t, a in WRITE_CALLS])
def test_write_tools_in_non_primary_contexts_return_writes_disabled(tool, args):
    provider = _provider()
    provider._agent_context = "cron"
    payload = _call(provider, tool, args)
    assert payload["ok"] is False
    assert payload["reason_code"] == "writes_disabled"


@pytest.mark.parametrize(
    "tool,args",
    [
        ("entropicmem_search", {"query": "x"}),
        ("entropicmem_timeline", {}),
        ("entropicmem_stats", {}),
        ("entropicmem_review", {"action": "list_pending"}),
        ("entropicmem_review", {"action": "consolidate_preview"}),
    ],
    ids=["search", "timeline", "stats", "list_pending", "consolidate_preview"],
)
def test_read_calls_are_allowed_in_non_primary_contexts(tool, args):
    provider = _provider()
    provider._agent_context = "cron"
    payload = _call(provider, tool, args)
    assert payload.get("reason_code") != "writes_disabled"


# --- the fuzz: nothing raises, everything parses -----------------------------

JUNK_KEYS = [
    "query", "content", "ids", "kinds", "sources", "limit", "id", "mode", "action",
    "signal", "target", "unknown", "domain", "top_k", "entropic_id", "confirm_token",
]
JUNK_VALUES = [None, 0, -1, 1, 25, 26, 999, "", "x", "x" * 5000, True, False, [], ["x"], ["x", 1], {}, 3.5, "fact", "nope"]


def test_fuzz_random_arguments_never_raise_out_of_handle_tool_call():
    rng = random.Random(404)
    provider = _provider()
    names = SURFACE + list(LEGACY) + ["entropicmem_bogus", ""]
    for _ in range(300):
        name = rng.choice(names)
        if rng.random() < 0.1:
            args = rng.choice([None, "text", 7, [], [{"a": 1}]])  # type: ignore[assignment]
        else:
            args = {key: rng.choice(JUNK_VALUES) for key in rng.sample(JUNK_KEYS, rng.randint(0, 5))}
        out = provider.handle_tool_call(name, args)
        assert isinstance(out, str)
        parsed = json.loads(out)
        assert isinstance(parsed, dict), (name, args, out)


def test_fuzz_never_raises_on_a_live_provider(tmp_path):
    rng = random.Random(11)
    provider = _provider()
    provider.initialize("fuzz-session", hermes_home=str(tmp_path))
    names = SURFACE + list(LEGACY)
    for _ in range(120):
        name = rng.choice(names)
        args = {key: rng.choice(JUNK_VALUES) for key in rng.sample(JUNK_KEYS, rng.randint(0, 6))}
        out = provider.handle_tool_call(name, args)
        assert isinstance(out, str)
        json.loads(out)
