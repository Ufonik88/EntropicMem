"""EntropicMem's dashboard config surface (EM-407) — Appendix A's typed keys.

Loaded **by path** by the host's web server (``plugins.memory.config_schema``
is the only import: this file is data, not code) and stored as flat JSON at
``$HERMES_HOME/entropicmem/config.json`` — dotted keys with string values, which
``em/config.py``'s loader coerces and validates on the next ``initialize``.

The key list mirrors ``em.config.config_schema_fields()`` (a test pins them
field-for-field); ``aliases`` carry the legacy flat names so the panel shows a
value a v2 config already set. ``default`` is always a string here: JSON for the
``json`` kinds, ``str()`` for everything else.
"""

from __future__ import annotations

from plugins.memory.config_schema import (
    KIND_BOOL,
    KIND_JSON,
    KIND_NUMBER,
    KIND_SELECT,
    KIND_TEXT,
    STORAGE_FLAT_JSON,
    ProviderConfigSchema,
    ProviderField,
    ProviderFieldOption,
)

DOCS_URL = "https://github.com/Ufonik88/EntropicMem#configuration"


def _options(*values: str) -> tuple:
    return tuple(ProviderFieldOption(value=value, label=value) for value in values)


CONFIG_SCHEMA = ProviderConfigSchema(
    name="entropicmem",
    label="EntropicMem",
    storage=STORAGE_FLAT_JSON,
    docs_url=DOCS_URL,
    fields=(
        ProviderField(
            key="paths.vault_path",
            label="Vault path",
            kind=KIND_TEXT,
            default="",
            description="Where the Markdown vault lives (empty = $HERMES_HOME/entropicmem/vault).",
            placeholder="~/.hermes/entropicmem/vault",
            aliases=("vault_path",),
            group="Paths",
        ),
        ProviderField(
            key="paths.memory_db",
            label="Memory DB path",
            kind=KIND_TEXT,
            default="",
            description="The SQLite store (empty = under $HERMES_HOME/entropicmem).",
            aliases=("memory_db",),
            group="Paths",
        ),
        ProviderField(
            key="scope.mode",
            label="Scoping mode",
            kind=KIND_SELECT,
            default="auto",
            description="How reads are scoped when a gateway user id is present.",
            options=_options("auto", "profile", "user", "chat"),
            inline=True,
            group="Scope",
        ),
        ProviderField(
            key="scope.owner_user_ids",
            label="Owner user ids",
            kind=KIND_JSON,
            default="[]",
            description="Gateway user ids treated as the owner.",
            aliases=("owner_user_ids",),
            group="Scope",
        ),
        ProviderField(
            key="scope.guest_hidden_domains",
            label="Guest-hidden domains",
            kind=KIND_JSON,
            default='["People", "Finance"]',
            description="Domains guests never see.",
            aliases=("guest_hidden_domains",),
            group="Scope",
        ),
        ProviderField(
            key="prefetch.enabled",
            label="Prefetch enabled",
            kind=KIND_BOOL,
            default="True",
            description="Inject the memory block before each turn.",
            inline=True,
            group="Prefetch",
        ),
        ProviderField(
            key="prefetch.token_budget",
            label="Prefetch budget (tokens)",
            kind=KIND_NUMBER,
            default="450",
            description="Token budget for the synchronous block.",
            inline=True,
            group="Prefetch",
        ),
        ProviderField(
            key="prefetch.max_latency_ms",
            label="Prefetch latency cap (ms)",
            kind=KIND_NUMBER,
            default="1200",
            description="Internal cap; the host hard limit is 8000 ms.",
            aliases=("prefetch_max_latency_ms",),
            group="Prefetch",
        ),
        ProviderField(
            key="prefetch.query_rewrite",
            label="Query rewrite",
            kind=KIND_SELECT,
            default="none",
            description="Rewrite queries in the background precompute only.",
            options=_options("none", "hermes"),
            group="Prefetch",
        ),
        ProviderField(
            key="gate.min_score",
            label="Gate: min score",
            kind=KIND_NUMBER,
            default="0.3",
            description="Minimum fused score for a fact to pass §3.6's gate.",
            inline=True,
            group="Gate",
        ),
        ProviderField(
            key="gate.min_coverage",
            label="Gate: min coverage",
            kind=KIND_NUMBER,
            default="0.34",
            description="Minimum token coverage of the query.",
            group="Gate",
        ),
        ProviderField(
            key="ranking.w_rrf",
            label="Ranking: RRF weight",
            kind=KIND_NUMBER,
            default="0.5",
            description="Weight of the reciprocal-rank-fusion term.",
            inline=True,
            group="Ranking",
        ),
        ProviderField(
            key="ranking.w_importance",
            label="Ranking: importance weight",
            kind=KIND_NUMBER,
            default="0.25",
            description="Weight of the importance term.",
            group="Ranking",
        ),
        ProviderField(
            key="core.inject_mode",
            label="Core inject mode",
            kind=KIND_SELECT,
            default="system_prompt",
            description="How the core block is delivered.",
            options=_options("system_prompt", "prefetch"),
            aliases=("core_inject_mode",),
            group="Core",
        ),
        ProviderField(
            key="core.writable_by_agent",
            label="Core writable by agent",
            kind=KIND_BOOL,
            default="False",
            description="Let the agent write core memory.",
            group="Core",
        ),
        ProviderField(
            key="embeddings.enabled",
            label="Embeddings enabled",
            kind=KIND_BOOL,
            default="False",
            description="Opt in to the embedding backend.",
            aliases=("embeddings_enabled",),
            inline=True,
            group="Embeddings",
        ),
        ProviderField(
            key="embeddings.backend",
            label="Embeddings backend",
            kind=KIND_SELECT,
            default="auto",
            description="Which backend serves embeddings.",
            options=_options("auto", "fastembed", "sentence_transformers", "openai_compat", "none"),
            group="Embeddings",
        ),
        ProviderField(
            key="formation.mode",
            label="Formation mode",
            kind=KIND_SELECT,
            default="off",
            description="When formation runs.",
            options=_options("off", "session", "realtime"),
            group="Formation",
        ),
        ProviderField(
            key="formation.llm",
            label="Formation LLM",
            kind=KIND_SELECT,
            default="auto",
            description="Which LLM serves formation.",
            options=_options("auto", "hermes", "openai_compat", "none"),
            group="Formation",
        ),
        ProviderField(
            key="vault.projection",
            label="Vault projection",
            kind=KIND_SELECT,
            default="entities+journal",
            description="What the vault projection writes.",
            options=_options("none", "entities", "entities+journal", "legacy"),
            inline=True,
            group="Vault",
        ),
        ProviderField(
            key="trust.injection_policy_extracted",
            label="Extracted-content policy",
            kind=KIND_SELECT,
            default="quarantine",
            description="What happens to instruction-looking extracted content.",
            options=_options("flag", "quarantine", "drop"),
            group="Trust",
        ),
        ProviderField(
            key="trust.injection_policy_direct",
            label="Direct-content policy",
            kind=KIND_SELECT,
            default="flag",
            description="What happens to instruction-looking direct content.",
            options=_options("flag", "quarantine", "drop"),
            group="Trust",
        ),
        ProviderField(
            key="privacy.transcript_retention_days",
            label="Transcript retention (days)",
            kind=KIND_NUMBER,
            default="30",
            description="How long transcript chunks are kept.",
            group="Privacy",
        ),
        ProviderField(
            key="sync.publish_scope",
            label="Publish scope",
            kind=KIND_SELECT,
            default="shared",
            description="What this instance publishes to the shared store.",
            options=_options("none", "shared", "all"),
            group="Sync",
        ),
    ),
)
