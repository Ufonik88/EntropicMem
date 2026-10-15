"""EM-407, the wiring half: the typed config reaches ``initialize`` and the pipeline.

One group per claim:

* **initialize loads the §3.8 sources** — the host's merged
  ``plugins.entropicmem``/``memory.entropicmem`` view, the dashboard's
  flat_json, ``ENTROPICMEM_*`` paths, then constructor overrides; invalid values
  are collected on the provider and logged once, and the default stands.
* **``get_config_schema`` is typed** — dotted keys with
  ``type``/``choices``/``minimum``/``maximum``, and there is no ``post_setup``
  (it would replace the host wizard and skip saving ``memory.provider``).
* **``save_config`` nests into ``memory.entropicmem``** — atomically, with every
  other key untouched, and it round-trips through the next ``initialize``. A
  write failure raises: the host must see a failed setup, and the old
  swallow-at-debug is gone.
* **the tuned scalars reach the v3 call sites** — the tool search path, the
  ``PrefetchService``, and the facade's flag-on recall each pass the configured
  ``gate_config``/``rank_weights`` into ``retrieve``; a service or engine built
  without them passes neither (the EM-403 fakes stay byte-identical).
* **initialize auto-bootstraps** — on a fresh home the store directory is
  created at init and the first engine open creates the store, so a fresh
  install works without the CLI; and ``entropicmem init`` prints the Hermes
  cron line for ``worker run``.

Invented data only (rule 4). The live store is never touched.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
for _entry in (str(REPO), str(SCRIPTS)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from plugins.entropicmem import EntropicMemMemoryProvider  # noqa: E402

import em.config as em_config  # noqa: E402
from em.facade.engine import V3_RETRIEVAL_ENV, V3Engine  # noqa: E402
from em.facade.select import open_engine  # noqa: E402
from em.provider.prefetch_service import PrefetchService  # noqa: E402
from em.retrieval.fusion import RankWeights  # noqa: E402
from em.retrieval.gate import GateConfig  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import Scope  # noqa: E402

#: Parsing and writing the host config file needs PyYAML — the same optional
#: dependency ``_backend.load_plugin_config``/``save_config`` carry (CI's test
#: jobs install it; the windows-import job runs ``tests/unit`` with pytest
#: alone, where these skip like the numpy-gated tests do).
needs_yaml = pytest.mark.skipif(
    importlib.util.find_spec("yaml") is None, reason="PyYAML not installed"
)

SCOPE = Scope(profile="em407")
QUERY = "what is the staging port?"


def _spawn(target, name):
    thread = threading.Thread(target=target, name=name, daemon=True)
    thread.start()
    return thread


def _v3_db(tmp_path: Path) -> Path:
    db = tmp_path / "memory.db"
    V3Engine(db).close()
    return db


def _outcome():
    return SimpleNamespace(
        rankings=[], rows={}, predecessors={}, partial=False, generators_skipped=()
    )


class _Recorder:
    """A ``pipeline.retrieve`` stand-in that keeps every call's kwargs."""

    def __init__(self):
        self.calls = []
        self.outcome = _outcome()

    def __call__(self, conn, **kwargs):
        self.calls.append(kwargs)
        return self.outcome


def _initialize(tmp_path: Path, *, session: str = "sess-em407", config: dict | None = None):
    provider = EntropicMemMemoryProvider(config=config or {})
    provider.initialize(session, hermes_home=str(tmp_path))
    return provider


def _home_with_skill_tree(tmp_path: Path) -> Path:
    """A home whose ``plugins/entropicmem`` is this repo's tree, as installed."""
    home = tmp_path / "hermes"
    home.mkdir()
    (home / "plugins").mkdir()
    (home / "plugins" / "entropicmem").symlink_to(
        REPO / "plugins" / "entropicmem", target_is_directory=True
    )
    return home


def _provider_with_v3_store(tmp_path: Path, db: Path, config: dict | None = None):
    provider = _initialize(tmp_path, config=config)
    # `initialize` leaves these unset when the skill tree is not in the temp
    # home; point them at the real tree and the temp store, as EM-405's tests do.
    provider._scripts_dir = SCRIPTS
    provider._profile_id = "default"
    provider._memory_db = db
    provider._spawn = _spawn
    return provider


# --- initialize: the §3.8 sources -------------------------------------------


@needs_yaml
def test_initialize_reads_memory_entropicmem_over_plugins_entropicmem(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "plugins:\n"
        "  entropicmem:\n"
        '    owner_user_ids: ["owned-1"]\n'
        "    core_inject_mode: prefetch\n"
        "  homeassistant:\n"
        "    enabled: true\n"
        "memory:\n"
        "  provider: entropicmem\n"
        "  entropicmem:\n"
        "    scope:\n"
        "      mode: profile\n"
        "    gate:\n"
        "      min_score: 0.42\n"
        "    ranking:\n"
        "      w_rrf: 0.25\n",
        encoding="utf-8",
    )
    provider = _initialize(tmp_path)
    cfg = provider._typed_config
    assert cfg.scope.mode == "profile", "the nested memory.entropicmem spelling wins"
    assert cfg.scope.owner_user_ids == ["owned-1"], "the legacy flat spelling still maps"
    assert cfg.core.inject_mode == "prefetch"
    assert provider._gate_config.min_score == 0.42
    assert provider._gate_config.min_coverage == em_config.GATE_MIN_COVERAGE
    assert provider._gate_config.min_cosine == em_config.Config().gate.min_cosine
    assert provider._rank_weights.rrf == 0.25
    assert provider._rank_weights.importance == em_config.RANKING_IMPORTANCE
    # the legacy flat dict the v2 knobs read is untouched
    assert provider._config["core_inject_mode"] == "prefetch"
    assert provider._config["owner_user_ids"] == ["owned-1"]


def test_initialize_reads_the_dashboard_json_after_the_yaml(tmp_path):
    (tmp_path / "entropicmem").mkdir()
    (tmp_path / "entropicmem" / "config.json").write_text(
        '{"prefetch.token_budget": "900", "scope.mode": "user"}', encoding="utf-8"
    )
    (tmp_path / "config.yaml").write_text(
        "memory:\n  entropicmem:\n    scope:\n      mode: profile\n", encoding="utf-8"
    )
    provider = _initialize(tmp_path)
    assert provider._typed_config.prefetch.token_budget == 900
    assert provider._typed_config.scope.mode == "user", "flat_json comes last of the files"


def test_env_paths_beat_the_files_and_reach_resolve_paths(tmp_path, monkeypatch):
    home = _home_with_skill_tree(tmp_path)
    monkeypatch.setenv("ENTROPICMEM_MEMORY_DB", str(tmp_path / "env.db"))
    (home / "config.yaml").write_text(
        "memory:\n  entropicmem:\n    paths:\n      memory_db: "
        f'"{tmp_path / "yaml.db"}"\n',
        encoding="utf-8",
    )
    provider = _initialize(home)
    assert provider._typed_config.paths.memory_db == str(tmp_path / "env.db")
    assert provider._memory_db == tmp_path / "env.db", (
        "the typed paths (env last) are what resolve_paths receives"
    )


def test_constructor_overrides_are_last_and_accept_dotted_keys(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "memory:\n  entropicmem:\n    gate:\n      min_score: 0.42\n", encoding="utf-8"
    )
    provider = _initialize(tmp_path, config={"gate.min_score": 0.9, "prefetch.token_budget": 777})
    assert provider._typed_config.gate.min_score == 0.9
    assert provider._typed_config.prefetch.token_budget == 777


@needs_yaml
def test_invalid_values_fall_back_and_are_logged_once(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(EntropicMemMemoryProvider, "_config_errors_logged", False, raising=False)
    (tmp_path / "config.yaml").write_text(
        "memory:\n  entropicmem:\n    gate:\n      min_score: nope\n", encoding="utf-8"
    )
    with caplog.at_level(logging.WARNING):
        first = _initialize(tmp_path, session="sess-a")
        _initialize(tmp_path, session="sess-b")
    assert first._typed_config.gate.min_score == em_config.GATE_MIN_SCORE
    assert [e.key for e in first._config_errors] == ["gate.min_score"]
    warnings = [r for r in caplog.records if "config value(s) rejected" in r.getMessage()]
    assert len(warnings) == 1, "logged once at init, not once per session"


# --- the schema and save_config ---------------------------------------------


def test_get_config_schema_is_typed_with_dotted_keys():
    provider = EntropicMemMemoryProvider(config={})
    schema = {item["key"]: item for item in provider.get_config_schema()}
    assert len(schema) >= 20
    assert {
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
    } <= set(schema)
    assert schema["scope.mode"]["type"] == "text"
    assert schema["scope.mode"]["choices"] == ["auto", "profile", "user", "chat"]
    assert schema["prefetch.token_budget"]["type"] == "integer"
    assert schema["prefetch.token_budget"]["minimum"] == 100
    assert schema["prefetch.token_budget"]["maximum"] == 2000
    assert schema["prefetch.enabled"]["type"] == "boolean"
    assert schema["prefetch.enabled"]["default"] is True
    assert schema["gate.min_score"]["type"] == "number"
    assert schema["gate.min_score"]["default"] == em_config.GATE_MIN_SCORE
    assert schema["scope.owner_user_ids"]["type"] == "json"


def test_there_is_no_post_setup():
    """The card: post_setup would replace the whole host wizard and skip saving
    ``memory.provider``; the bootstrap path is ``initialize`` + ``init`` instead."""
    assert not hasattr(EntropicMemMemoryProvider, "post_setup")


@needs_yaml
def test_save_config_nests_into_memory_entropicmem_and_touches_nothing_else(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(
        "plugins:\n"
        "  entropicmem:\n"
        "    min_relevance_score: 0.3\n"
        "  homeassistant:\n"
        "    enabled: true\n"
        "memory:\n"
        "  provider: entropicmem\n",
        encoding="utf-8",
    )
    provider = EntropicMemMemoryProvider(config={})
    provider.save_config({"scope.mode": "profile", "prefetch.token_budget": 800}, str(tmp_path))

    import yaml

    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert data["memory"]["entropicmem"]["scope"]["mode"] == "profile"
    assert data["memory"]["entropicmem"]["prefetch"]["token_budget"] == 800
    # merge-only: provider selection and every other section survive
    assert data["memory"]["provider"] == "entropicmem"
    assert data["plugins"]["entropicmem"]["min_relevance_score"] == 0.3
    assert data["plugins"]["homeassistant"]["enabled"] is True


@needs_yaml
def test_save_config_round_trips_through_initialize(tmp_path):
    """The card's AC: save, then the next init reads the saved values back."""
    provider = EntropicMemMemoryProvider(config={})
    provider.save_config(
        {"scope.mode": "profile", "prefetch.token_budget": 800, "gate.min_score": 0.42},
        str(tmp_path),
    )
    fresh = _initialize(tmp_path)
    assert fresh._typed_config.scope.mode == "profile"
    assert fresh._typed_config.prefetch.token_budget == 800
    assert fresh._gate_config.min_score == 0.42


@needs_yaml
def test_save_config_raises_when_the_file_cannot_be_written(tmp_path):
    home_as_file = tmp_path / "home-as-file"
    home_as_file.write_text("not a directory", encoding="utf-8")
    provider = EntropicMemMemoryProvider(config={})
    with pytest.raises(OSError):
        provider.save_config({"scope.mode": "profile"}, str(home_as_file))


@needs_yaml
def test_save_config_raises_when_the_atomic_replace_fails(tmp_path, monkeypatch):
    """Also the last step fails loudly: a half-written config the host counts as
    saved would be worse than a visible setup error."""
    config = tmp_path / "config.yaml"
    config.write_text("memory:\n  provider: entropicmem\n", encoding="utf-8")
    provider = EntropicMemMemoryProvider(config={})

    real_replace = Path.replace

    def flaky_replace(self, target):
        if Path(target).name == "config.yaml":
            raise OSError("disk went away")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    with pytest.raises(OSError):
        provider.save_config({"scope.mode": "profile"}, str(tmp_path))

    # and the original file is exactly as it was
    import yaml

    assert yaml.safe_load(config.read_text(encoding="utf-8")) == {
        "memory": {"provider": "entropicmem"}
    }


# --- the tuned scalars reach the call sites ---------------------------------


def test_the_tool_search_path_passes_the_configured_scalars(tmp_path, monkeypatch):
    import em.retrieval.pipeline as pipeline

    db = _v3_db(tmp_path)
    provider = _provider_with_v3_store(tmp_path, db)
    recorder = _Recorder()
    monkeypatch.setattr(pipeline, "retrieve", recorder)

    payload = json.loads(provider.handle_tool_call("entropicmem_search", {"query": QUERY}))
    assert payload.get("ok") is not False, payload
    assert recorder.calls, "the v3 search path must reach the pipeline"
    kwargs = recorder.calls[0]
    assert kwargs["gate_config"] is provider._gate_config
    assert kwargs["rank_weights"] is provider._rank_weights
    # the defaults the provider built ARE EM-306's calibrated scalars
    assert kwargs["gate_config"].min_score == em_config.GATE_MIN_SCORE
    assert kwargs["rank_weights"].rrf == em_config.RANKING_RRF
    assert kwargs["rank_weights"].importance == em_config.RANKING_IMPORTANCE


def test_a_configured_gate_and_ranking_win_over_the_defaults(tmp_path, monkeypatch):
    import em.retrieval.pipeline as pipeline

    db = _v3_db(tmp_path)
    provider = _provider_with_v3_store(
        tmp_path, db, config={"gate.min_score": 0.9, "ranking.w_rrf": 0.1}
    )
    recorder = _Recorder()
    monkeypatch.setattr(pipeline, "retrieve", recorder)

    provider.handle_tool_call("entropicmem_search", {"query": QUERY})
    assert recorder.calls[0]["gate_config"].min_score == 0.9
    assert recorder.calls[0]["rank_weights"].rrf == 0.1


@pytest.fixture()
def store(tmp_path):
    store = Store(str(tmp_path / "prefetch.db"))
    with store.writer() as writer:
        migrate(writer)
    yield store
    store.close()


def _service(store, *, retrieve=None, **kwargs):
    return PrefetchService(
        connect=store.reader,
        spawn_thread=_spawn,
        retrieve=retrieve,
        **kwargs,
    )


def test_the_prefetch_service_passes_the_configured_scalars(store):
    gate = GateConfig(min_score=0.11, min_coverage=0.22)
    weights = RankWeights(rrf=0.31)
    recorder = _Recorder()
    service = _service(store, retrieve=recorder, gate_config=gate, rank_weights=weights, token_budget=200)
    try:
        service.prefetch(QUERY, scope=SCOPE, session_id="s1")
    finally:
        service.close()
    assert recorder.calls
    assert recorder.calls[0]["gate_config"] is gate
    assert recorder.calls[0]["rank_weights"] is weights


def test_a_prefetch_service_without_settings_passes_neither(store):
    """EM-403 fakes observe the same call shape as before EM-407."""
    recorder = _Recorder()
    service = _service(store, retrieve=recorder, token_budget=200)
    try:
        service.prefetch(QUERY, scope=SCOPE, session_id="s1")
    finally:
        service.close()
    assert recorder.calls
    assert "gate_config" not in recorder.calls[0]
    assert "rank_weights" not in recorder.calls[0]


def test_the_facade_recall_passes_the_configured_scalars(tmp_path, monkeypatch):
    import em.retrieval.pipeline as pipeline

    db = _v3_db(tmp_path)
    gate = GateConfig(min_score=0.11)
    weights = RankWeights(rrf=0.31)
    engine = V3Engine(db, gate_config=gate, rank_weights=weights)
    recorder = _Recorder()
    monkeypatch.setattr(pipeline, "retrieve", recorder)
    monkeypatch.setenv(V3_RETRIEVAL_ENV, "1")
    try:
        engine.recall_with_relevance(QUERY, top_k=3)
    finally:
        engine.close()
    assert recorder.calls
    assert recorder.calls[0]["gate_config"] is gate
    assert recorder.calls[0]["rank_weights"] is weights


def test_open_engine_routes_the_settings_to_the_v3_engine(tmp_path):
    v3 = _v3_db(tmp_path)
    gate = GateConfig(min_score=0.11)
    weights = RankWeights(rrf=0.31)
    engine = open_engine(v3, gate_config=gate, rank_weights=weights)
    try:
        assert engine._gate_config is gate
        assert engine._rank_weights is weights
    finally:
        engine.close()

    # a v2 store accepts the same call shape and ignores the two (its scorer is
    # the v2 formula, which has no gate or rank weights to take)
    from memory_engine import MemoryEngine

    v2 = tmp_path / "v2.db"
    MemoryEngine(v2, profile_id="default").close()
    engine = open_engine(v2, gate_config=gate, rank_weights=weights)
    engine.close()


# --- bootstrap and the CLI ---------------------------------------------------


def test_initialize_bootstraps_the_store_directory_on_a_fresh_home(tmp_path, monkeypatch):
    home = _home_with_skill_tree(tmp_path)
    monkeypatch.delenv("ENTROPICMEM_MEMORY_DB", raising=False)
    provider = _initialize(home)
    assert provider._scripts_dir is not None
    assert provider._memory_db == home / "entropicmem" / "memory.db"
    assert provider._memory_db.parent.is_dir(), "init creates the store directory"
    with provider._open_engine() as engine:
        assert engine is not None
    assert provider._memory_db.is_file(), "first use creates the store — no CLI needed"


def test_cmd_init_prints_the_worker_cron_line(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    (tmp_path / "hermes").mkdir()
    spec = importlib.util.spec_from_file_location(
        "entropicmem_cli_em407", SCRIPTS / "entropicmem.py"
    )
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    args = SimpleNamespace(
        vault=str(tmp_path / "vault"),
        index_db=str(tmp_path / "index.db"),
        dry_run=False,
        force=False,
    )
    assert cli.cmd_init(args) == 0
    out = capsys.readouterr().out
    assert "EntropicMem initialized." in out
    assert "hermes cron create" in out
    assert "worker run" in out
