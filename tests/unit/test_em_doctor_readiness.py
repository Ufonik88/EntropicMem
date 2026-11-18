"""The doctor's embeddings readiness (the re-armed P0c's precondition).

Three facts, read-only, each measured the way the serving path would measure
it: the backend the selection would make, the flag as the config stands, and
the store's existing vectors with their model stamps. The P0c readout's
finding makes this load-bearing: the live store carries a historical
backfill's rows while no backend exists, and the cutover decision needs that
state visible in one command instead of an evidence dig.

Nothing the doctor does here enables, installs or embeds — a backend that is
present while the flag is off is the READY state, and the advisory says the
flip is the owner's word, never a doctor act. An enabled flag with no backend
is a FAIL: semantic recall silently cannot run.

Synthetic data only. ``HERMES_HOME`` is pinned to a tmp home in every test:
this box carries a real ``~/.hermes/config.yaml``, and a test must not borrow
the machine's live config (CI's fresh runner has none, so an unpinned test
would also pass green on CI while reading whatever the dev box happens to
have).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import entropicmem  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "db"


class _StubBackend:
    """The shape of a backend the doctor may report: name + availability."""

    def __init__(self, available: bool, name: str = "sentence_transformers"):
        self._available = available
        self.name = name

    def available(self) -> bool:
        return self._available


def _copy_v2_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "memory.db"
    target.write_bytes((FIXTURES / "v2_7_0.db").read_bytes())
    return target


def _seed_vectors(store: Path, model: str, count: int = 3) -> None:
    with sqlite3.connect(store) as conn:
        fact_id = conn.execute("SELECT id FROM facts LIMIT 1").fetchone()[0]
        conn.execute(
            "CREATE TABLE IF NOT EXISTS embeddings ("
            "fact_id TEXT PRIMARY KEY, vector BLOB NOT NULL, "
            "model TEXT DEFAULT 'all-MiniLM-L6-v2', dim INTEGER DEFAULT 384, "
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
            "FOREIGN KEY (fact_id) REFERENCES facts(id) ON DELETE CASCADE)"
        )
        for i in range(count):
            conn.execute(
                "INSERT INTO embeddings (fact_id, vector, model, dim) VALUES (?, ?, ?, ?)",
                (f"{fact_id}-{i}", b"\x00" * 8, model, 384),
            )


def _run_doctor(capsys, monkeypatch, tmp_path: Path, *argv: str) -> tuple[int, str]:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ENTROPICMEM_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("ENTROPICMEM_VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setenv("ENTROPICMEM_INDEX_DB", str(tmp_path / "index.db"))
    monkeypatch.setattr(sys, "argv", ["entropicmem.py", "doctor", *argv])
    code = entropicmem.main()
    return code, capsys.readouterr().out


def _stub_config(monkeypatch, *, enabled: bool, backend: str = "auto",
                 model: str = "BAAI/bge-small-en-v1.5") -> None:
    """The typed config the doctor reads: the ConfigLoad shape, leaves pinned."""
    monkeypatch.setattr(
        "em.config.load_config",
        lambda sources: SimpleNamespace(
            config=SimpleNamespace(
                embeddings=SimpleNamespace(enabled=enabled, backend=backend, model=model),
            ),
            errors=[],
        ),
    )


def test_no_backend_with_inert_vectors_is_a_warn_naming_them(tmp_path, monkeypatch, capsys):
    store = _copy_v2_fixture(tmp_path)
    _seed_vectors(store, "all-MiniLM-L6-v2", count=3)
    monkeypatch.setattr(
        "em.embeddings.backends.select_backend",
        lambda preference, env=None, model=None: _StubBackend(False, "none"),
    )
    code, out = _run_doctor(capsys, monkeypatch, tmp_path)
    assert code == 0  # a missing backend is the documented default, not a failure
    assert "[WARN] embeddings" in out
    assert "no embeddings backend" in out
    assert "3 row(s) stamped 'all-MiniLM-L6-v2'" in out
    assert "inert" in out


def test_enabled_with_no_backend_is_a_fail(tmp_path, monkeypatch, capsys):
    _copy_v2_fixture(tmp_path)
    _stub_config(monkeypatch, enabled=True)
    monkeypatch.setattr(
        "em.embeddings.backends.select_backend",
        lambda preference, env=None, model=None: _StubBackend(False, "none"),
    )
    code, out = _run_doctor(capsys, monkeypatch, tmp_path)
    assert code == 1
    assert "[FAIL] embeddings" in out
    assert "silently cannot run" in out


def test_backend_available_flag_off_is_the_ready_state(tmp_path, monkeypatch, capsys):
    _copy_v2_fixture(tmp_path)
    _stub_config(monkeypatch, enabled=False, model="all-MiniLM-L6-v2")
    monkeypatch.setattr(
        "em.embeddings.backends.select_backend",
        lambda preference, env=None, model=None: _StubBackend(True, "sentence_transformers"),
    )
    code, out = _run_doctor(capsys, monkeypatch, tmp_path)
    assert code == 0
    line = [ln for ln in out.splitlines() if "embeddings" in ln and ln.startswith("[")][0]
    assert line.startswith("[PASS] embeddings")
    assert "embeddings.enabled is OFF" in line
    assert "backend 'sentence_transformers' available" in line
    assert "never a doctor act" in line  # the flip is the owner's word


def test_backend_available_flag_on_passes(tmp_path, monkeypatch, capsys):
    _copy_v2_fixture(tmp_path)
    _stub_config(monkeypatch, enabled=True, model="all-MiniLM-L6-v2")
    monkeypatch.setattr(
        "em.embeddings.backends.select_backend",
        lambda preference, env=None, model=None: _StubBackend(True, "sentence_transformers"),
    )
    code, out = _run_doctor(capsys, monkeypatch, tmp_path)
    assert code == 0
    line = [ln for ln in out.splitlines() if "embeddings" in ln and ln.startswith("[")][0]
    assert line.startswith("[PASS] embeddings")
    assert "embeddings.enabled is ON" in line
    assert "never a doctor act" not in line  # the flip already happened


def test_a_model_mismatch_names_the_backfill_requirement(tmp_path, monkeypatch, capsys):
    store = _copy_v2_fixture(tmp_path)
    _seed_vectors(store, "all-MiniLM-L6-v2", count=2)
    _stub_config(monkeypatch, enabled=False, model="BAAI/bge-small-en-v1.5")
    monkeypatch.setattr(
        "em.embeddings.backends.select_backend",
        lambda preference, env=None, model=None: _StubBackend(True, "fastembed"),
    )
    code, out = _run_doctor(capsys, monkeypatch, tmp_path)
    assert code == 0
    line = [ln for ln in out.splitlines() if "embeddings" in ln and ln.startswith("[")][0]
    assert "do not match the config model" in line
    assert "model-switch backfill" in line
    assert "2 row(s) stamped 'all-MiniLM-L6-v2'" in line
