"""P0b at the provider layer: the flag must not move the turn, and with it on the
served block is S3's — rendered by the provider's existing renderer.

The byte-identity guard is the one P0a used, in the direction that matters here:
the v3 pipeline is a *new* branch, so "the flag does not change behaviour when off"
means the off transcript must equal the **pre-P0b** answer, byte for byte. The golden
below was captured from the commit before the flag existed (with the same fixture and
the same provider config), and a second test blocks ``pipeline.retrieve`` with a
raiser to show the off transcript cannot have come from the v3 path at all.

With the flag on, the block is exactly what the existing renderer produces for the
facts the facade maps back — no new renderer, and nothing EM-307 owns leaks in
(no superseded note, no token packer): asserted as exact lines, not a shape sniff.

Invented data only (rule 4). The live store is never touched.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
for _entry in (str(REPO), str(SCRIPTS)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from plugins.entropicmem import EntropicMemMemoryProvider  # noqa: E402

from em.facade.engine import V3_RETRIEVAL_ENV, V3Engine  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.episodes import EpisodeStore  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402
from memory_engine import StoredFact  # noqa: E402

PROFILE = Scope(profile="default")
STAMP = "2026-01-15T00:00:00Z"
QUERY = "what port does the staging server use"
STAGING = "the staging server runs on port 9090"
CONSTRAINT = "never deploy on fridays"

STAGING_V2_ID = StoredFact.make_id(STAGING)

#: The pre-P0b golden, captured from the commit before the flag existed. The
#: staging bullet's score (0.89) and the cached/abstaining answers are the parts
#: that were *recorded*; the id is content-derived and stable by construction.
GOLDEN = {
    "system_prompt": (
        "# EntropicMem (active)\n"
        "Standalone memory: use `entropicmem_remember` for durable facts, "
        "`entropicmem_recall` for fact search, `entropicmem_query` for cited vault notes.\n"
        "CLI: `entropicmem lint`, `hotcache`, `graph export` for maintenance.\n"
    ),
    "context_query": QUERY,
    "prefetch_first": (
        "## EntropicMem recall\n"
        f"- [{STAGING_V2_ID}] the staging server runs on port 9090 "
        "(Infrastructure · 2026-01-15) [score:0.89]"
    ),
    "prefetch_second": (
        "## EntropicMem recall\n"
        f"- [{STAGING_V2_ID}] the staging server runs on port 9090 "
        "(Infrastructure · 2026-01-15) [score:0.89]"
    ),
    "prefetch_other": "",
}


@dataclass
class Seeded:
    db: Path
    constraint_id: str


def seed(tmp_path: Path) -> Seeded:
    """The same fixture as the facade-level suite, kept local so this file reads
    standalone: staging fact + billing fact + one ``kind='constraint'`` row."""
    db = tmp_path / "memory.db"
    engine = V3Engine(db)
    engine.remember(
        STAGING, title="Staging server", domain="Infrastructure", importance=0.8
    )
    engine.remember(
        "nightly billing job reconciles invoices", domain="Knowledge", importance=0.5
    )
    engine.close()

    store = Store(str(db))
    with store.transaction() as conn:
        result = MemoryStore(conn).add(
            MemoryDraft(
                content=CONSTRAINT,
                kind="constraint",
                importance=0.9,
                source="agent",
                status="active",
            ),
            scope=PROFILE,
            actor="tester",
        )
        assert result.ok, result
        EpisodeStore(conn).add_episode(
            scope=PROFILE,
            kind="manual",
            title="Hub fleet migration",
            summary="decided the object numbers are hub ids",
        )
    with store.transaction() as conn:
        conn.execute(
            "UPDATE memories SET created_at=?, updated_at=?, last_accessed_at=NULL",
            (STAMP, STAMP),
        )
    store.close()
    return Seeded(db=db, constraint_id=result.id)


@pytest.fixture(autouse=True)
def _flag_off_by_default(monkeypatch):
    monkeypatch.delenv(V3_RETRIEVAL_ENV, raising=False)


def _provider(tmp_path: Path, db: Path) -> EntropicMemMemoryProvider:
    provider = EntropicMemMemoryProvider(
        config={
            "core_memory_enabled": False,
            "touch_on_inject": False,
            "cache_conversation_context": True,
        }
    )
    provider.initialize("p0b-session", hermes_home=str(tmp_path))
    # `initialize` leaves these unset when the skill tree is not in the temp home;
    # `prefetch` needs both, and this is what points it at the real facade.
    provider._scripts_dir = SCRIPTS
    provider._memory_db = db
    provider._profile_id = "default"
    return provider


def _transcript(provider: EntropicMemMemoryProvider) -> dict:
    """Everything the host receives for one turn, not just the rendered block."""
    return {
        "system_prompt": provider.system_prompt_block(),
        "context_query": provider._build_context_query(QUERY),
        "prefetch_first": provider.prefetch(QUERY),
        "prefetch_second": provider.prefetch(QUERY),  # the cache path
        "prefetch_other": provider.prefetch("an unrelated query about invoices"),
    }


# --- the flag off: the turn is the pre-P0b turn, byte for byte -------------


def test_the_full_response_is_byte_identical_to_the_pre_p0b_golden(tmp_path):
    seeded = seed(tmp_path)
    out = _transcript(_provider(tmp_path, seeded.db))
    assert out == GOLDEN
    assert out["prefetch_first"], "the fixture must actually inject something"


def test_the_off_transcript_cannot_have_come_from_the_v3_pipeline(tmp_path, monkeypatch):
    """Independent of the golden: a ``retrieve`` that raises is never called."""
    seeded = seed(tmp_path)

    import em.retrieval.pipeline as pipeline

    def explode(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("pipeline.retrieve ran with the flag off")

    monkeypatch.setattr(pipeline, "retrieve", explode)
    out = _transcript(_provider(tmp_path, seeded.db))
    assert out == GOLDEN


# --- the flag on: S3 serves the block, the existing renderer prints it -----


def test_the_flag_on_serves_the_constraint_through_the_existing_renderer(
    tmp_path, monkeypatch
):
    seeded = seed(tmp_path)

    import em.retrieval.pipeline as pipeline

    calls = []
    real = pipeline.retrieve

    def spy(conn, **kwargs):  # noqa: ANN001, ANN003
        calls.append(kwargs)
        return real(conn, **kwargs)

    monkeypatch.setattr(pipeline, "retrieve", spy)
    monkeypatch.setenv(V3_RETRIEVAL_ENV, "1")
    out = _transcript(_provider(tmp_path, seeded.db))

    # Two uncached prefetches (the first query, then the unrelated one); the
    # cached second prefetch must not re-query.
    assert len(calls) == 2
    assert all(call["with_gate"] is True for call in calls)

    staging_line = (
        f"- [{STAGING_V2_ID}] the staging server runs on port 9090 "
        "(Infrastructure · 2026-01-15) [score:0.68]"
    )
    constraint_line = (
        f"- [{seeded.constraint_id}] never deploy on fridays "
        "(Knowledge · 2026-01-15) [score:0.49]"
    )
    assert out["prefetch_first"].splitlines() == [
        "## EntropicMem recall",
        staging_line,
        constraint_line,
    ]
    assert out["prefetch_second"] == out["prefetch_first"], "the cache path still caches"
    # The pinned constraint is the only survivor of the unrelated query — §3.6's
    # "only pinned constraints may remain" — and the block is still v2's bullet
    # shape, with nothing EM-307 owns (no superseded note) leaking in.
    assert out["prefetch_other"] == "\n".join(
        ["## EntropicMem recall", constraint_line]
    )
    assert "(updated " not in out["prefetch_first"]
