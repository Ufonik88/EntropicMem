"""EM-407, the typed config: Appendix A's model, §3.8's loader, the typed schema.

The card's pieces, one group per claim:

* **the model** — one nested dataclass per Appendix A section, with the Appendix's
  defaults except where EM-306's calibration owns the number (``gate.*`` and
  ``ranking.*`` default to ``em/config.py``'s tuned scalars, not the Appendix's
  spec table — that is the point of the card).
* **the §3.8 read order** — defaults → the host's merged ``plugins.entropicmem``
  (legacy flat) + ``memory.entropicmem`` (nested, wins) view → the dashboard's
  ``$HERMES_HOME/entropicmem/config.json`` → ``ENTROPICMEM_*`` paths → the
  constructor overrides tests use. Later sources win; within one source a nested
  or dotted key beats its legacy flat spelling.
* **validation** — every typed leaf has a rule; an invalid value is collected as
  a ``ConfigError`` and the built-in default stands (the future ``doctor`` reads
  the collected list; the provider logs it once).
* **the schema** — ``config_schema_fields()`` is the curated user-facing subset
  (the card's ten required keys among them), and ``plugins/entropicmem/
  config_schema.py`` declares the same surface to the dashboard with only
  ``plugins.memory.config_schema`` imported.

Invented data only (rule 4). The live store is never touched.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
for _entry in (str(REPO), str(SCRIPTS)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import em.config as em_config  # noqa: E402
from em.config import (  # noqa: E402
    RULES,
    Config,
    config_schema_fields,
    load_config,
)

#: The ten keys the master plan's Appendix A pins as the schema's minimum.
REQUIRED_SCHEMA_KEYS = {
    "scope.mode",
    "scope.owner_user_ids",
    "prefetch.token_budget",
    "prefetch.enabled",
    "core.writable_by_agent",
    "embeddings.backend",
    "formation.mode",
    "formation.llm",
    "vault.projection",
    "paths.vault_path",
}


def _leaves(node, prefix: str = "") -> dict:
    """Every typed leaf of a config instance, by dotted key."""
    out = {}
    for f in dataclasses.fields(node):
        value = getattr(node, f.name)
        key = f"{prefix}{f.name}"
        if dataclasses.is_dataclass(value):
            out.update(_leaves(value, key + "."))
        else:
            out[key] = value
    return out


def _get(config, key: str):
    node = config
    for part in key.split("."):
        node = getattr(node, part)
    return node


# --- the model ---------------------------------------------------------------


def test_defaults_are_appendix_a_with_em306_owning_the_tuned_numbers():
    cfg = Config()
    assert (cfg.paths.vault_path, cfg.paths.memory_db, cfg.paths.index_db) == ("", "", "")
    assert cfg.scope.mode == "auto"
    assert cfg.scope.owner_user_ids == []
    assert cfg.scope.guest_hidden_domains == ["People", "Finance"]
    assert cfg.prefetch.enabled is True
    assert cfg.prefetch.token_budget == 450
    assert cfg.prefetch.max_latency_ms == 1200
    assert cfg.prefetch.dedup_turns == 6
    assert cfg.prefetch.constraint_repeat_turns == 10
    assert cfg.prefetch.include_episodes is True
    assert cfg.prefetch.include_notes is False
    assert cfg.prefetch.include_shared is False
    assert cfg.prefetch.query_rewrite == "none"
    assert cfg.core.inject_mode == "system_prompt"
    assert cfg.core.token_budget == 800
    assert cfg.core.max_tokens_per_block == 400
    assert cfg.core.writable_by_agent is False
    assert cfg.embeddings.enabled is False
    assert cfg.embeddings.backend == "auto"
    assert cfg.embeddings.model == "BAAI/bge-small-en-v1.5"
    assert cfg.formation.mode == "session"
    assert cfg.formation.realtime_every_turns == 6
    assert cfg.formation.llm == "auto"
    assert cfg.formation.auto_commit_min_confidence == 0.75
    assert cfg.formation.auto_commit_kinds == [
        "preference",
        "profile",
        "constraint",
        "procedure",
        "fact",
    ]
    assert cfg.formation.insights is False
    assert cfg.formation.insights_auto_commit is False
    assert cfg.formation.max_llm_calls_per_hour == 60
    assert cfg.formation.pending_ttl_days == 30
    assert cfg.mirror.builtin_memory is True
    assert cfg.mirror.background_review is True
    assert cfg.jobs.run_in_primary is True
    assert cfg.jobs.run_in_cron is True
    assert cfg.jobs.cron_budget_s == 120
    assert cfg.vault.projection == "entities+journal"
    assert cfg.vault.ingest_human_edits is False
    assert cfg.trust.injection_policy_extracted == "quarantine"
    assert cfg.trust.injection_policy_direct == "flag"
    assert cfg.privacy.pii_locales == []
    assert cfg.privacy.transcript_retention_days == 30
    assert cfg.privacy.log_content is False
    assert cfg.sync.publish_scope == "shared"
    assert cfg.sync.recall_shared is False
    assert cfg.entities.seed_builtin is False
    assert cfg.timezone == "UTC"


def test_gate_and_ranking_defaults_are_em306s_calibrated_scalars():
    cfg = Config()
    assert cfg.gate.min_score == em_config.GATE_MIN_SCORE == 0.30
    assert cfg.gate.min_coverage == em_config.GATE_MIN_COVERAGE == 0.34
    # The Appendix's spec table says 0.60/0.15; EM-306's dev objective chose the
    # importance-heavy preset and the holdout confirmed it. The typed default is
    # the calibrated number — that is what "reaches call sites" means.
    assert cfg.ranking.w_rrf == em_config.RANKING_RRF == 0.50
    assert cfg.ranking.w_importance == em_config.RANKING_IMPORTANCE == 0.25
    assert (
        cfg.ranking.w_recency,
        cfg.ranking.w_confidence,
        cfg.ranking.w_feedback,
    ) == (em_config.RANKING_RECENCY, em_config.RANKING_CONFIDENCE, em_config.RANKING_FEEDBACK)
    assert cfg.ranking.standard_half_life_days == 180.0
    assert cfg.ranking.volatile_half_life_days == 14.0
    assert cfg.ranking.standard_floor == 0.5
    assert cfg.ranking.mmr_lambda == 0.7


def test_min_cosine_default_matches_the_gate_modules_spec_table():
    """One table, two homes: a drift here would change gating silently."""
    from em.retrieval.gate import GATE_MIN_COSINE

    assert Config().gate.min_cosine == dict(GATE_MIN_COSINE)


def test_every_typed_leaf_has_a_rule_and_every_rule_resolves():
    leaves = _leaves(Config())
    assert set(RULES) == set(leaves), (
        "RULES and the Config model must be the same surface: "
        f"rules-only={sorted(set(RULES) - set(leaves))} "
        f"leaves-only={sorted(set(leaves) - set(RULES))}"
    )


# --- the §3.8 read order -----------------------------------------------------


def test_later_sources_win_and_env_paths_beat_the_files():
    legacy = {
        "owner_user_ids": ["owned-1"],
        "core_inject_mode": "prefetch",
        "vault_path": "/legacy/vault",
        "min_relevance_score": 0.4,  # a v2 knob: not ours, ignored
    }
    preferred = {"scope": {"mode": "profile"}, "prefetch": {"token_budget": 700}}
    dashboard = {"prefetch.token_budget": "800", "scope.mode": "user", "gate.min_score": "0.4"}
    env = {"paths.memory_db": "/env/memory.db"}

    loaded = load_config([legacy, preferred, dashboard, env])
    assert loaded.errors == ()
    cfg = loaded.config
    assert cfg.scope.mode == "user", "the dashboard (later) beats memory.entropicmem"
    assert cfg.scope.owner_user_ids == ["owned-1"], "legacy flat keys map into v3 paths"
    assert cfg.core.inject_mode == "prefetch"
    assert cfg.paths.vault_path == "/legacy/vault"
    assert cfg.prefetch.token_budget == 800, "dashboard strings coerce"
    assert cfg.gate.min_score == 0.4
    assert cfg.paths.memory_db == "/env/memory.db"

    overridden = load_config([legacy, preferred, dashboard, env], overrides={"scope.mode": "chat"})
    assert overridden.config.scope.mode == "chat", "constructor overrides are last"


@pytest.mark.parametrize(
    ("flat", "dotted", "value"),
    (
        ("vault_path", "paths.vault_path", "/v"),
        ("memory_db", "paths.memory_db", "/m.db"),
        ("index_db", "paths.index_db", "/i.db"),
        ("owner_user_ids", "scope.owner_user_ids", ["u1"]),
        ("guest_hidden_domains", "scope.guest_hidden_domains", ["Secret"]),
        ("core_inject_mode", "core.inject_mode", "prefetch"),
        ("embeddings_enabled", "embeddings.enabled", True),
        ("prefetch_max_latency_ms", "prefetch.max_latency_ms", 900),
    ),
)
def test_legacy_flat_keys_map_to_their_v3_paths(flat, dotted, value):
    loaded = load_config([{flat: value}])
    assert loaded.errors == ()
    assert _get(loaded.config, dotted) == value


def test_the_legacy_prefetch_token_budget_folds_chars_into_tokens():
    """v2 counted characters; the typed key counts tokens (§4.2's ÷4)."""
    loaded = load_config([{"prefetch_token_budget": 3000}])
    assert loaded.errors == ()
    assert loaded.config.prefetch.token_budget == 750
    # a typed key beats the legacy fold in the same source
    loaded = load_config([{"prefetch_token_budget": 3000, "prefetch.token_budget": 900}])
    assert loaded.config.prefetch.token_budget == 900
    # a value outside the token band clamps to the nearest valid budget — the
    # EM-403 AC drives an "effectively unlimited" legacy budget this way
    assert load_config([{"prefetch_token_budget": 200_000}]).config.prefetch.token_budget == 2000
    assert load_config([{"prefetch_token_budget": 10}]).config.prefetch.token_budget == 100
    # a legacy value that is not a character count is a collected error
    loaded = load_config([{"prefetch_token_budget": "banana"}])
    assert [e.key for e in loaded.errors] == ["prefetch.token_budget"]
    assert loaded.config.prefetch.token_budget == 450


def test_a_nested_key_beats_its_legacy_flat_spelling_within_one_source():
    """The host merges both YAML locations into one dict; the nested spelling is
    the one the user means in ``memory.entropicmem``."""
    loaded = load_config([{"owner_user_ids": ["flat"], "scope": {"owner_user_ids": ["nested"]}}])
    assert loaded.errors == ()
    assert loaded.config.scope.owner_user_ids == ["nested"]


def test_unknown_keys_are_ignored_silently():
    """The same dict carries the whole legacy v2 surface; none of it is an error."""
    loaded = load_config(
        [
            {
                "min_relevance_score": 0.4,
                "decay_half_life_days": 90,
                "evergreen_domains": ["a"],
                "paths": {"nonsense": 1},
                "unsectioned": {"deep": {"thing": 1}},
            }
        ]
    )
    assert loaded.errors == ()
    assert loaded.config == Config()


# --- validation --------------------------------------------------------------


def test_invalid_values_are_collected_and_the_default_stands():
    loaded = load_config(
        [
            {
                "prefetch": {"token_budget": "banana", "enabled": "maybe", "query_rewrite": "sometimes"},
                "gate": {"min_score": 1.5},
                "ranking": {"w_rrf": "not-a-number"},
                "privacy": {"transcript_retention_days": -1},
                "scope": {"owner_user_ids": [1, 2]},
            }
        ]
    )
    assert {e.key for e in loaded.errors} == {
        "prefetch.token_budget",
        "prefetch.enabled",
        "prefetch.query_rewrite",
        "gate.min_score",
        "ranking.w_rrf",
        "privacy.transcript_retention_days",
        "scope.owner_user_ids",
    }
    for error in loaded.errors:
        assert error.message, error
    cfg = loaded.config
    assert cfg.prefetch.token_budget == 450
    assert cfg.prefetch.enabled is True
    assert cfg.prefetch.query_rewrite == "none"
    assert cfg.gate.min_score == em_config.GATE_MIN_SCORE
    assert cfg.ranking.w_rrf == em_config.RANKING_RRF
    assert cfg.privacy.transcript_retention_days == 30
    assert cfg.scope.owner_user_ids == []


def test_an_invalid_later_value_does_not_clobber_a_valid_earlier_one():
    loaded = load_config(
        [{"prefetch": {"token_budget": 700}}, {"prefetch.token_budget": "banana"}]
    )
    assert loaded.config.prefetch.token_budget == 700
    assert [e.key for e in loaded.errors] == ["prefetch.token_budget"]


def test_validate_values_coerces_known_keys_and_names_every_problem():
    """The save path's gate: the loader's surface, and all problems at once."""
    coerced, errors = em_config.validate_values(
        {
            "prefetch.token_budget": "777",
            "prefetch_token_budget": 4800,  # legacy spelling + fold; the dotted one wins
            "gate.min_scoer": 0.2,  # a typo is refused, not written
            "gate.min_score": 2.0,  # out of range
        }
    )
    assert coerced == {"prefetch.token_budget": 777}
    assert [e.key for e in errors] == ["gate.min_scoer", "gate.min_score"]
    assert all(e.message for e in errors)


def test_validate_values_folds_the_legacy_character_budget():
    coerced, errors = em_config.validate_values({"prefetch_token_budget": 3200})
    assert errors == []
    assert coerced == {"prefetch.token_budget": 800}


def test_dashboard_strings_coerce_to_typed_values():
    loaded = load_config(
        [
            {
                "prefetch.token_budget": "450",
                "prefetch.enabled": "false",
                "gate.min_score": "0.25",
                "ranking.w_importance": "0.25",
            }
        ]
    )
    assert loaded.errors == ()
    assert loaded.config.prefetch.token_budget == 450
    assert loaded.config.prefetch.enabled is False
    assert loaded.config.gate.min_score == 0.25
    assert loaded.config.ranking.w_importance == 0.25


@pytest.mark.parametrize("bad", ("4.5", True, [1], None))
def test_integer_fields_reject_non_integers(bad):
    loaded = load_config([{"prefetch.token_budget": bad}])
    assert [e.key for e in loaded.errors] == ["prefetch.token_budget"]
    assert loaded.config.prefetch.token_budget == 450


def test_float_map_values_are_validated_per_entry():
    loaded = load_config(
        [{"gate": {"min_cosine": {"bge-small-en-v1.5": 0.62, "other": "nope"}}}]
    )
    assert [e.key for e in loaded.errors] == ["gate.min_cosine"]
    assert loaded.config.gate.min_cosine == Config().gate.min_cosine


# --- the schema --------------------------------------------------------------


def test_the_curated_schema_covers_the_cards_required_keys():
    fields = config_schema_fields()
    keys = [f["key"] for f in fields]
    assert len(keys) >= 20 and len(keys) == len(set(keys)), "top ~20 user-facing keys"
    assert REQUIRED_SCHEMA_KEYS <= set(keys)
    kinds = {f["kind"] for f in fields}
    assert kinds == {"text", "select", "bool", "integer", "number", "json"}


def test_schema_entries_agree_with_the_rules_and_the_defaults():
    defaults = Config()
    for field in config_schema_fields():
        key = field["key"]
        rule = RULES[key]
        # the UI kind is the rule kind, except the two JSON-rendered ones
        if rule.kind in ("string_list", "float_map"):
            assert field["kind"] == "json", key
        else:
            assert field["kind"] == rule.kind, key
        assert field["default"] == _get(defaults, key), key
        assert field["choices"] == tuple(rule.choices), key
        assert field["minimum"] == rule.minimum, key
        assert field["maximum"] == rule.maximum, key
        assert field["description"], key


def test_a_select_schema_entry_carries_its_choices_in_rule_order():
    field = next(f for f in config_schema_fields() if f["key"] == "scope.mode")
    assert field["kind"] == "select"
    assert list(field["choices"]) == ["auto", "profile", "user", "chat"]


# --- config_schema.py, the dashboard's declaration ---------------------------


def _stub_host_schema_module() -> types.ModuleType:
    """The host's ``plugins.memory.config_schema``, mirrored field-for-field.

    CI has no Hermes install, so the test pins the *usage* against this copy of
    the host API (kind constants, ``ProviderField``/``ProviderFieldOption``/
    ``ProviderConfigSchema`` dataclasses) — the same shape the host's web server
    loads by path.
    """
    module = types.ModuleType("plugins.memory.config_schema")
    module.KIND_TEXT = "text"
    module.KIND_SELECT = "select"
    module.KIND_SECRET = "secret"
    module.KIND_BOOL = "bool"
    module.KIND_NUMBER = "number"
    module.KIND_JSON = "json"
    module.STORAGE_FLAT_JSON = "flat_json"
    module.STORAGE_HONCHO_HOST_BLOCK = "honcho_host_block"

    @dataclasses.dataclass(frozen=True)
    class ProviderFieldOption:
        value: str
        label: str
        description: str = ""

    @dataclasses.dataclass(frozen=True)
    class ProviderField:
        key: str
        label: str
        kind: str = "text"
        default: str = ""
        description: str = ""
        placeholder: str = ""
        options: tuple = ()
        env_key: str = None
        aliases: tuple = ()
        env_fallbacks: tuple = ()
        inline: bool = False
        group: str = ""
        info: str = ""
        scope: str = "host"

    @dataclasses.dataclass(frozen=True)
    class ProviderConfigSchema:
        name: str
        label: str
        storage: str = "flat_json"
        docs_url: str = ""
        fields: tuple = ()

    module.ProviderFieldOption = ProviderFieldOption
    module.ProviderField = ProviderField
    module.ProviderConfigSchema = ProviderConfigSchema
    return module


def _load_config_schema_module(monkeypatch):
    for name in ("plugins", "plugins.memory"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "plugins.memory.config_schema", _stub_host_schema_module())
    path = REPO / "plugins" / "entropicmem" / "config_schema.py"
    spec = importlib.util.spec_from_file_location("entropicmem_config_schema_em407", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_config_schema_imports_only_the_pure_host_module():
    tree = ast.parse((REPO / "plugins" / "entropicmem" / "config_schema.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert imported <= {"plugins.memory.config_schema", "__future__"}, imported


def test_config_schema_declares_flat_json_and_the_same_fields(monkeypatch):
    module = _load_config_schema_module(monkeypatch)
    schema = module.CONFIG_SCHEMA
    assert schema.name == "entropicmem"
    assert schema.storage == "flat_json", "$HERMES_HOME/entropicmem/config.json"

    fields = config_schema_fields()
    assert [f.key for f in schema.fields] == [f["key"] for f in fields]

    kind_map = {
        "text": "text",
        "select": "select",
        "bool": "bool",
        "integer": "number",
        "number": "number",
        "json": "json",
    }
    for declared, spec in zip(schema.fields, fields):
        assert declared.kind == kind_map[spec["kind"]], declared.key
        expected_default = (
            json.dumps(spec["default"]) if spec["kind"] == "json" else str(spec["default"])
        )
        assert declared.default == expected_default, declared.key
        if spec["choices"]:
            assert [opt.value for opt in declared.options] == list(spec["choices"]), declared.key
        assert declared.label, declared.key
        assert declared.description, declared.key
        assert declared.group, declared.key


def test_config_schema_aliases_carry_the_legacy_flat_names(monkeypatch):
    module = _load_config_schema_module(monkeypatch)
    by_key = {f.key: f for f in module.CONFIG_SCHEMA.fields}
    assert "owner_user_ids" in by_key["scope.owner_user_ids"].aliases
    assert "guest_hidden_domains" in by_key["scope.guest_hidden_domains"].aliases
    assert "core_inject_mode" in by_key["core.inject_mode"].aliases
    assert "embeddings_enabled" in by_key["embeddings.enabled"].aliases
    assert "prefetch_max_latency_ms" in by_key["prefetch.max_latency_ms"].aliases
