"""EM-306's calibration output and EM-407's typed configuration.

**Calibration (EM-306).** The tuned scalars for the v3 retrieval pipeline,
calibrated 2026-10-08 on the **hard** suite's dev split (70% of the 60 scenarios, by id
hash) against the card's objective. ``RESULT_FILE`` holds the grid, the split ids, the
dev table and the never-optimised holdout numbers; the selected candidate was the
dev-best, and ties prefer the spec — a flat objective never moves a threshold.

**The typed config (EM-407).** Appendix A's model lives here too: one nested
dataclass per section, :func:`load_config` implementing §3.8's read order (later
sources win; within one source a nested or dotted key beats its legacy flat
spelling), per-key validation whose failures are collected as
:class:`ConfigError` (the default stands — nothing raises; the future ``doctor``
reads the collected list), and :func:`config_schema_fields`, the curated
user-facing subset ``get_config_schema()`` renders. ``gate.*`` and ``ranking.*``
default to the calibrated scalars above rather than the plan's spec table: those
are the numbers the pipeline actually runs.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

#: The calibration record this file is derived from — grid, split ids, holdout numbers.
RESULT_FILE = "evals/results/tune-hard-4eb8097.json"

#: `gate.min_score` / `gate.min_coverage` — unchanged from §3.6's defaults. The dev
#: objective was flat across the grid's band, so the spec values stand rather than
#: moving a threshold on no evidence.
GATE_MIN_SCORE = 0.30
GATE_MIN_COVERAGE = 0.34

#: `ranking.*` — the rerank weights. Chosen by the dev objective and confirmed on the
#: holdout: mrr 0.881 against the spec's 0.865, with the same recall and noise.
RANKING_RRF = 0.50
RANKING_IMPORTANCE = 0.25
RANKING_RECENCY = 0.10
RANKING_CONFIDENCE = 0.10
RANKING_FEEDBACK = 0.05


# --- the model (Appendix A) --------------------------------------------------


@dataclass
class PathsConfig:
    """`paths.*` — empty means "the host resolver decides" (its own precedence
    stays: explicit value, then ``ENTROPICMEM_*``, then ``$HERMES_HOME``)."""

    vault_path: str = ""
    memory_db: str = ""
    index_db: str = ""


@dataclass
class ScopeConfig:
    """`scope.*` — whose memories are visible by default (§3.5)."""

    mode: str = "auto"
    owner_user_ids: List[str] = field(default_factory=list)
    guest_hidden_domains: List[str] = field(default_factory=lambda: ["People", "Finance"])


@dataclass
class PrefetchConfig:
    """`prefetch.*` — §4.2's synchronous block."""

    enabled: bool = True
    token_budget: int = 450
    max_latency_ms: int = 1200
    dedup_turns: int = 6
    constraint_repeat_turns: int = 10
    include_episodes: bool = True
    include_notes: bool = False
    include_shared: bool = False
    query_rewrite: str = "none"


@dataclass
class GateConfig:
    """`gate.*` — §3.6's thresholds; defaults are EM-306's calibrated scalars."""

    min_score: float = GATE_MIN_SCORE
    min_coverage: float = GATE_MIN_COVERAGE
    min_cosine: Dict[str, float] = field(
        #: Pinned equal to ``em.retrieval.gate.GATE_MIN_COSINE`` by a test; kept as a
        #: literal so this module stays stdlib-only.
        default_factory=lambda: {"bge-small-en-v1.5": 0.62, "all-MiniLM-L6-v2": 0.38}
    )


@dataclass
class RankingConfig:
    """`ranking.*` — §3.6's rerank weights and half-lives; the weights default to
    EM-306's calibrated scalars (the plan's spec table listed 0.60/0.15)."""

    w_rrf: float = RANKING_RRF
    w_importance: float = RANKING_IMPORTANCE
    w_recency: float = RANKING_RECENCY
    w_confidence: float = RANKING_CONFIDENCE
    w_feedback: float = RANKING_FEEDBACK
    standard_half_life_days: float = 180.0
    standard_floor: float = 0.5
    volatile_half_life_days: float = 14.0
    mmr_lambda: float = 0.7


@dataclass
class CoreConfig:
    """`core.*` — the core-memory block (§4.4)."""

    inject_mode: str = "system_prompt"
    token_budget: int = 800
    max_tokens_per_block: int = 400
    writable_by_agent: bool = False


@dataclass
class EmbeddingsConfig:
    """`embeddings.*` — EM-108's backend. ``enabled`` carries the legacy
    ``embeddings_enabled`` flat key (default off, as v2 shipped it)."""

    enabled: bool = False
    backend: str = "auto"
    model: str = "BAAI/bge-small-en-v1.5"


@dataclass
class FormationConfig:
    """`formation.*` — memory formation policy (§3.7)."""

    mode: str = "session"
    realtime_every_turns: int = 6
    llm: str = "auto"
    auto_commit_min_confidence: float = 0.75
    auto_commit_kinds: List[str] = field(
        default_factory=lambda: ["preference", "profile", "constraint", "procedure", "fact"]
    )
    insights: bool = False
    insights_auto_commit: bool = False
    max_llm_calls_per_hour: int = 60
    pending_ttl_days: int = 30


@dataclass
class MirrorConfig:
    """`mirror.*` — the v2 core-memory mirror (§3.3)."""

    builtin_memory: bool = True
    background_review: bool = True


@dataclass
class JobsConfig:
    """`jobs.*` — where the worker runs (§3.7)."""

    run_in_primary: bool = True
    run_in_cron: bool = True
    cron_budget_s: int = 120


@dataclass
class VaultConfig:
    """`vault.*` — the Obsidian projection (EM-210)."""

    projection: str = "entities+journal"
    ingest_human_edits: bool = False


@dataclass
class TrustConfig:
    """`trust.*` — injection defence policy (§3.5)."""

    injection_policy_extracted: str = "quarantine"
    injection_policy_direct: str = "flag"


@dataclass
class PrivacyConfig:
    """`privacy.*` — retention and content logging (EM-201)."""

    pii_locales: List[str] = field(default_factory=list)
    transcript_retention_days: int = 30
    log_content: bool = False


@dataclass
class SyncConfig:
    """`sync.*` — shared-store publishing (§3.7)."""

    publish_scope: str = "shared"
    recall_shared: bool = False


@dataclass
class EntitiesConfig:
    """`entities.*` — not in Appendix A; carries the REMAINING_PLAN note's
    ``entities.seed_builtin`` (default off). Its consumer is the entities
    feature's call site, which does not exist yet.`"""

    seed_builtin: bool = False


@dataclass
class Config:
    """Appendix A's configuration tree, one attribute per section."""

    paths: PathsConfig = field(default_factory=PathsConfig)
    scope: ScopeConfig = field(default_factory=ScopeConfig)
    prefetch: PrefetchConfig = field(default_factory=PrefetchConfig)
    gate: GateConfig = field(default_factory=GateConfig)
    ranking: RankingConfig = field(default_factory=RankingConfig)
    core: CoreConfig = field(default_factory=CoreConfig)
    embeddings: EmbeddingsConfig = field(default_factory=EmbeddingsConfig)
    formation: FormationConfig = field(default_factory=FormationConfig)
    mirror: MirrorConfig = field(default_factory=MirrorConfig)
    jobs: JobsConfig = field(default_factory=JobsConfig)
    vault: VaultConfig = field(default_factory=VaultConfig)
    trust: TrustConfig = field(default_factory=TrustConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    entities: EntitiesConfig = field(default_factory=EntitiesConfig)
    timezone: str = "UTC"


# --- the rules ---------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    """One typed leaf's contract: its kind, and the bounds a value must meet."""

    kind: str
    label: str = ""
    description: str = ""
    choices: Tuple[str, ...] = ()
    minimum: Optional[float] = None
    maximum: Optional[float] = None


#: Every typed leaf, keyed by its dotted path. The model and this table are the
#: same surface — a test walks ``Config()`` and fails on any drift either way.
RULES: Mapping[str, Rule] = {
    "paths.vault_path": Rule("text", "Vault path", "Where the Markdown vault lives (empty = $HERMES_HOME/entropicmem/vault)."),
    "paths.memory_db": Rule("text", "Memory DB path", "The SQLite store (empty = under $HERMES_HOME/entropicmem)."),
    "paths.index_db": Rule("text", "Index DB path", "The v2 index database (empty = under $HERMES_HOME/entropicmem)."),
    "scope.mode": Rule(
        "select", "Scoping mode", "How reads are scoped when a gateway user id is present.",
        choices=("auto", "profile", "user", "chat"),
    ),
    "scope.owner_user_ids": Rule("string_list", "Owner user ids", "Gateway user ids treated as the owner."),
    "scope.guest_hidden_domains": Rule("string_list", "Guest-hidden domains", "Domains guests never see."),
    "prefetch.enabled": Rule("bool", "Prefetch enabled", "Inject the memory block before each turn."),
    "prefetch.token_budget": Rule("integer", "Prefetch budget (tokens)", "Token budget for the synchronous block.", minimum=100, maximum=2000),
    "prefetch.max_latency_ms": Rule("integer", "Prefetch latency cap (ms)", "Internal cap; the host hard limit is 8000 ms.", minimum=200, maximum=6000),
    "prefetch.dedup_turns": Rule("integer", "Dedup window (turns)", "How many recent turns a block entry stays deduplicated.", minimum=0, maximum=100),
    "prefetch.constraint_repeat_turns": Rule("integer", "Constraint repeat window", "Turns a constraint may repeat inside.", minimum=0, maximum=100),
    "prefetch.include_episodes": Rule("bool", "Include episodes", "Let episode summaries into the block."),
    "prefetch.include_notes": Rule("bool", "Include notes", "Let note-kind memories into the block."),
    "prefetch.include_shared": Rule("bool", "Include shared", "Let shared-store memories into the block."),
    "prefetch.query_rewrite": Rule(
        "select", "Query rewrite", "Rewrite queries in the background precompute only.",
        choices=("none", "hermes"),
    ),
    "gate.min_score": Rule("number", "Gate: min score", "Minimum fused score for a fact to pass §3.6's gate.", minimum=0.0, maximum=1.0),
    "gate.min_coverage": Rule("number", "Gate: min coverage", "Minimum token coverage of the query.", minimum=0.0, maximum=1.0),
    "gate.min_cosine": Rule("float_map", "Gate: cosine floors", "Per-model cosine floor (the third support condition, still off)."),
    "ranking.w_rrf": Rule("number", "Ranking: RRF weight", "Weight of the reciprocal-rank-fusion term.", minimum=0.0, maximum=1.0),
    "ranking.w_importance": Rule("number", "Ranking: importance weight", "Weight of the importance term.", minimum=0.0, maximum=1.0),
    "ranking.w_recency": Rule("number", "Ranking: recency weight", "Weight of the recency term.", minimum=0.0, maximum=1.0),
    "ranking.w_confidence": Rule("number", "Ranking: confidence weight", "Weight of the confidence term.", minimum=0.0, maximum=1.0),
    "ranking.w_feedback": Rule("number", "Ranking: feedback weight", "Weight of the feedback term.", minimum=0.0, maximum=1.0),
    "ranking.standard_half_life_days": Rule("number", "Standard half-life (days)", "Decay half-life for standard memories.", minimum=1.0, maximum=3650.0),
    "ranking.standard_floor": Rule("number", "Standard decay floor", "The max(0.5, …) floor for a standard memory.", minimum=0.0, maximum=1.0),
    "ranking.volatile_half_life_days": Rule("number", "Volatile half-life (days)", "Decay half-life for volatile memories.", minimum=1.0, maximum=3650.0),
    "ranking.mmr_lambda": Rule("number", "MMR lambda", "Diversity/weight trade-off for the MMR rerank.", minimum=0.0, maximum=1.0),
    "core.inject_mode": Rule(
        "select", "Core inject mode", "How the core block is delivered.",
        choices=("system_prompt", "prefetch"),
    ),
    "core.token_budget": Rule("integer", "Core budget (tokens)", "Token budget for the core block.", minimum=50, maximum=4000),
    "core.max_tokens_per_block": Rule("integer", "Core block cap (tokens)", "Maximum size of one core block.", minimum=50, maximum=2000),
    "core.writable_by_agent": Rule("bool", "Core writable by agent", "Let the agent write core memory."),
    "embeddings.enabled": Rule("bool", "Embeddings enabled", "Opt in to the embedding backend."),
    "embeddings.backend": Rule(
        "select", "Embeddings backend", "Which backend serves embeddings.",
        choices=("auto", "fastembed", "sentence_transformers", "openai_compat", "none"),
    ),
    "embeddings.model": Rule("text", "Embeddings model", "The embedding model name."),
    "formation.mode": Rule(
        "select", "Formation mode", "When formation runs.",
        choices=("off", "session", "realtime"),
    ),
    "formation.realtime_every_turns": Rule("integer", "Realtime cadence (turns)", "Run realtime formation every N turns.", minimum=1, maximum=100),
    "formation.llm": Rule(
        "select", "Formation LLM", "Which LLM serves formation.",
        choices=("auto", "hermes", "openai_compat", "none"),
    ),
    "formation.auto_commit_min_confidence": Rule("number", "Auto-commit confidence", "Confidence a candidate needs to auto-commit.", minimum=0.0, maximum=1.0),
    "formation.auto_commit_kinds": Rule("string_list", "Auto-commit kinds", "Candidate kinds that may auto-commit."),
    "formation.insights": Rule("bool", "Insights", "Enable insight formation."),
    "formation.insights_auto_commit": Rule("bool", "Insights auto-commit", "Let insights auto-commit."),
    "formation.max_llm_calls_per_hour": Rule("integer", "LLM calls per hour", "Budget for formation LLM calls.", minimum=0, maximum=10000),
    "formation.pending_ttl_days": Rule("integer", "Pending TTL (days)", "How long a pending candidate survives.", minimum=1, maximum=3650),
    "mirror.builtin_memory": Rule("bool", "Mirror builtin memory", "Mirror writes into Hermes' builtin memory."),
    "mirror.background_review": Rule("bool", "Background review", "Let the background reviewer promote candidates."),
    "jobs.run_in_primary": Rule("bool", "Jobs in primary", "Run background jobs in the primary process."),
    "jobs.run_in_cron": Rule("bool", "Jobs in cron", "Run background jobs from the cron worker."),
    "jobs.cron_budget_s": Rule("integer", "Cron budget (s)", "Wall-clock budget for one cron job run.", minimum=5, maximum=3600),
    "vault.projection": Rule(
        "select", "Vault projection", "What the vault projection writes.",
        choices=("none", "entities", "entities+journal", "legacy"),
    ),
    "vault.ingest_human_edits": Rule("bool", "Ingest human edits", "Read human vault edits back into the store."),
    "trust.injection_policy_extracted": Rule(
        "select", "Extracted-content policy", "What happens to instruction-looking extracted content.",
        choices=("flag", "quarantine", "drop"),
    ),
    "trust.injection_policy_direct": Rule(
        "select", "Direct-content policy", "What happens to instruction-looking direct content.",
        choices=("flag", "quarantine", "drop"),
    ),
    "privacy.pii_locales": Rule("string_list", "PII locales", "Opt-in PII locale packs (EM-115)."),
    "privacy.transcript_retention_days": Rule("integer", "Transcript retention (days)", "How long transcript chunks are kept.", minimum=1, maximum=3650),
    "privacy.log_content": Rule("bool", "Log content", "Allow content in logs (off: redacted)."),
    "sync.publish_scope": Rule(
        "select", "Publish scope", "What this instance publishes to the shared store.",
        choices=("none", "shared", "all"),
    ),
    "sync.recall_shared": Rule("bool", "Recall shared", "Let shared-store memories into recall."),
    "entities.seed_builtin": Rule("bool", "Seed builtin entities", "Seed the builtin entity set on first use."),
    "timezone": Rule("text", "Timezone", "Timezone for world-time stamps (UTC unless set)."),
}


#: Legacy v2 flat keys mapped onto their v3 paths. Applied *before* the direct
#: dotted keys of the same source, so a nested spelling always wins.
LEGACY_KEY_MAP: Mapping[str, str] = {
    "vault_path": "paths.vault_path",
    "memory_db": "paths.memory_db",
    "index_db": "paths.index_db",
    "owner_user_ids": "scope.owner_user_ids",
    "guest_hidden_domains": "scope.guest_hidden_domains",
    "core_inject_mode": "core.inject_mode",
    "embeddings_enabled": "embeddings.enabled",
    "prefetch_max_latency_ms": "prefetch.max_latency_ms",
    "prefetch_token_budget": "prefetch.token_budget",
}


def _chars_to_tokens(value: Any) -> int:
    """v2's ``prefetch_token_budget`` counted characters; the typed key counts
    tokens. §4.2's ÷4 is the migration, clamped to the rule's 100..2000 band: a
    v2 value outside it becomes the nearest valid token budget rather than an
    error — "far above the cap" must stay far above, not fall back to 450."""
    return max(100, min(2000, int(str(value).strip()) // 4))


#: Legacy keys whose units changed on the way to their typed path.
LEGACY_TRANSFORMS: Mapping[str, Any] = {"prefetch_token_budget": _chars_to_tokens}

#: Dotted keys whose value is a mapping leaf, not a section to flatten.
_MAPPING_LEAVES = frozenset({"gate.min_cosine"})

_TRUE = frozenset({"true", "1", "yes", "on"})
_FALSE = frozenset({"false", "0", "no", "off"})
_INT_RE = re.compile(r"^[+-]?\d+$")


# --- loading and validation --------------------------------------------------


@dataclass(frozen=True)
class ConfigError:
    """One rejected value: the key, what was there, and why it was rejected."""

    key: str
    value: Any
    message: str


@dataclass(frozen=True)
class ConfigLoad:
    """The loaded :class:`Config` plus every value that was rejected on the way."""

    config: Config
    errors: Tuple[ConfigError, ...]


def _flatten(source: Mapping[str, Any], prefix: str = "") -> Dict[str, Any]:
    """Nested mappings become dotted keys; mapping leaves stay whole."""
    flat: Dict[str, Any] = {}
    for key, value in source.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, Mapping) and dotted not in _MAPPING_LEAVES:
            flat.update(_flatten(value, dotted + "."))
        else:
            flat[dotted] = value
    return flat


def _get(config: Config, key: str) -> Any:
    node: Any = config
    for part in key.split("."):
        node = getattr(node, part)
    return node


def _set(config: Config, key: str, value: Any) -> None:
    parts = key.split(".")
    node: Any = config
    for part in parts[:-1]:
        node = getattr(node, part)
    setattr(node, parts[-1], value)


def _range_error(rule: Rule, what: str) -> Optional[str]:
    if rule.minimum is None and rule.maximum is None:
        return None
    low = "-inf" if rule.minimum is None else f"{rule.minimum:g}"
    high = "inf" if rule.maximum is None else f"{rule.maximum:g}"
    return f"expected {what} in [{low}, {high}]"


def _validate(rule: Rule, value: Any) -> Tuple[Any, Optional[str]]:
    """Return ``(coerced, None)`` or ``(None, why)``. Never raises."""
    kind = rule.kind

    if kind == "text":
        if isinstance(value, str):
            return value, None
        return None, "expected text"

    if kind == "select":
        if isinstance(value, str) and value in rule.choices:
            return value, None
        return None, "expected one of: " + ", ".join(rule.choices)

    if kind == "bool":
        if isinstance(value, bool):
            return value, None
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in _TRUE:
                return True, None
            if lowered in _FALSE:
                return False, None
        return None, "expected true or false"

    if kind == "integer":
        if isinstance(value, bool):
            return None, "expected an integer"
        if isinstance(value, int):
            number = value
        elif isinstance(value, float) and value.is_integer():
            number = int(value)
        elif isinstance(value, str) and _INT_RE.match(value.strip()):
            number = int(value.strip())
        else:
            return None, "expected an integer"
        if (rule.minimum is not None and number < rule.minimum) or (
            rule.maximum is not None and number > rule.maximum
        ):
            return None, _range_error(rule, "an integer")
        return number, None

    if kind == "number":
        if isinstance(value, bool):
            return None, "expected a number"
        if isinstance(value, (int, float)):
            number = float(value)
        elif isinstance(value, str):
            try:
                number = float(value.strip())
            except ValueError:
                return None, "expected a number"
        else:
            return None, "expected a number"
        if not math.isfinite(number):
            return None, "expected a finite number"
        if (rule.minimum is not None and number < rule.minimum) or (
            rule.maximum is not None and number > rule.maximum
        ):
            return None, _range_error(rule, "a number")
        return number, None

    if kind == "string_list":
        if isinstance(value, (list, tuple)) and all(
            isinstance(item, str) and item.strip() for item in value
        ):
            return list(value), None
        return None, "expected a list of non-empty strings"

    if kind == "float_map":
        if not isinstance(value, Mapping) or not value:
            return None, "expected a mapping of model name to cosine floor"
        coerced: Dict[str, float] = {}
        for name, floor in value.items():
            if not isinstance(name, str) or not name.strip():
                return None, "expected model-name keys"
            if isinstance(floor, bool) or not isinstance(floor, (int, float)):
                return None, f"expected a number for {name!r}"
            number = float(floor)
            if not math.isfinite(number) or not 0.0 <= number <= 1.0:
                return None, f"expected 0..1 for {name!r}"
            coerced[name] = number
        return coerced, None

    return None, f"unknown rule kind {kind!r}"  # pragma: no cover — rules are fixed


def _apply(config: Config, key: str, value: Any, errors: List[ConfigError]) -> None:
    coerced, why = _validate(RULES[key], value)
    if why is not None:
        errors.append(ConfigError(key=key, value=value, message=why))
        return
    _set(config, key, coerced)


def load_config(
    sources: Sequence[Optional[Mapping[str, Any]]] = (),
    *,
    overrides: Optional[Mapping[str, Any]] = None,
) -> ConfigLoad:
    """Merge §3.8's sources in order — later sources win.

    Sources are flat or nested mappings: `plugins.entropicmem`'s legacy flat
    keys map onto their v3 paths first (the one with changed units — ``prefetch_
    token_budget``'s characters — folds through §4.2's ÷4), then every dotted
    key applies, so a nested spelling beats the legacy one inside a single
    source. Unknown keys are ignored silently (the same dict carries the whole
    legacy v2 surface); invalid values are collected and the default — or the
    last valid value — stands. Nothing raises.
    """
    config = Config()
    errors: List[ConfigError] = []
    chain: List[Optional[Mapping[str, Any]]] = list(sources) + [overrides]
    for source in chain:
        if not source:
            continue
        flat = _flatten(source)
        legacy: List[Tuple[str, Any, Any]] = []
        direct: List[Tuple[str, Any, Any]] = []
        for key, value in flat.items():
            target = LEGACY_KEY_MAP.get(key)
            if target is not None:
                legacy.append((target, value, LEGACY_TRANSFORMS.get(key)))
            else:
                direct.append((key, value, None))
        for key, value, transform in legacy + direct:
            if key not in RULES:
                continue
            if transform is not None:
                try:
                    value = transform(value)
                except Exception:
                    errors.append(
                        ConfigError(
                            key=key,
                            value=value,
                            message="expected the legacy character count",
                        )
                    )
                    continue
            _apply(config, key, value, errors)
    return ConfigLoad(config=config, errors=tuple(errors))


def validate_values(values: Mapping[str, Any]) -> Tuple[Dict[str, Any], List[ConfigError]]:
    """Validate a save before anything touches disk; returns ``(coerced, errors)``.

    ``save_config`` writes exactly the surface :func:`load_config` reads: the
    typed dotted keys, plus the legacy flat spellings :data:`LEGACY_KEY_MAP`
    carries (the ``prefetch_token_budget`` unit fold included), with the dotted
    spelling beating its legacy twin inside one call. Same coercion as the
    loader, so what lands in ``config.yaml`` is what the next load makes of it.
    Unknown keys are errors here — the loader ignores them silently, but the save
    path must not file a user's setup under a key nothing reads. Never raises.
    """
    errors: List[ConfigError] = []
    direct: Dict[str, Any] = {}
    legacy: Dict[str, Any] = {}
    for raw_key in sorted(values, key=str):
        original = values[raw_key]
        key = str(raw_key)
        target = LEGACY_KEY_MAP.get(key)
        if target is not None:
            value = original
            transform = LEGACY_TRANSFORMS.get(key)
            if transform is not None:
                try:
                    value = transform(value)
                except Exception:
                    errors.append(
                        ConfigError(
                            key=key,
                            value=original,
                            message="expected the legacy character count",
                        )
                    )
                    continue
            folded, why = _validate(RULES[target], value)
            if why is not None:
                errors.append(ConfigError(key=key, value=original, message=why))
                continue
            legacy[target] = folded
            continue
        rule = RULES.get(key)
        if rule is None:
            errors.append(ConfigError(key=key, value=original, message="unknown key"))
            continue
        coerced, why = _validate(rule, value=original)
        if why is not None:
            errors.append(ConfigError(key=key, value=original, message=why))
            continue
        direct[key] = coerced
    merged = dict(legacy)
    merged.update(direct)  # the dotted spelling wins, as it does at load
    return merged, errors


# --- the curated schema -------------------------------------------------------

#: The user-facing subset ``get_config_schema()`` renders — the card's ten
#: required keys among them. Everything else stays file-editable.
SCHEMA_KEYS: Tuple[str, ...] = (
    "paths.vault_path",
    "paths.memory_db",
    "scope.mode",
    "scope.owner_user_ids",
    "scope.guest_hidden_domains",
    "prefetch.enabled",
    "prefetch.token_budget",
    "prefetch.max_latency_ms",
    "prefetch.query_rewrite",
    "gate.min_score",
    "gate.min_coverage",
    "ranking.w_rrf",
    "ranking.w_importance",
    "core.inject_mode",
    "core.writable_by_agent",
    "embeddings.enabled",
    "embeddings.backend",
    "formation.mode",
    "formation.llm",
    "vault.projection",
    "trust.injection_policy_extracted",
    "trust.injection_policy_direct",
    "privacy.transcript_retention_days",
    "sync.publish_scope",
)


#: Rule kinds that render as one UI kind (the host's shapes are fewer).
_UI_KIND = {"string_list": "json", "float_map": "json"}


def config_schema_fields() -> Tuple[Dict[str, Any], ...]:
    """The curated keys with kind, default and bounds — host-shape free."""
    defaults = Config()
    out: List[Dict[str, Any]] = []
    for key in SCHEMA_KEYS:
        rule = RULES[key]
        out.append(
            {
                "key": key,
                "label": rule.label,
                "kind": _UI_KIND.get(rule.kind, rule.kind),
                "description": rule.description,
                "default": _get(defaults, key),
                "choices": tuple(rule.choices),
                "minimum": rule.minimum,
                "maximum": rule.maximum,
            }
        )
    return tuple(out)


def iter_leaf_keys(config: Optional[Config] = None) -> Tuple[str, ...]:
    """Every typed leaf's dotted key, in declaration order (tests and tooling)."""
    node = config if config is not None else Config()
    keys: List[str] = []

    def walk(current: Any, prefix: str) -> None:
        for f in fields(current):
            value = getattr(current, f.name)
            key = f"{prefix}{f.name}"
            if is_dataclass(value):
                walk(value, key + ".")
            else:
                keys.append(key)

    walk(node, "")
    return tuple(keys)
