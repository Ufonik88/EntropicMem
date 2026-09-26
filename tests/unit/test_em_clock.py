"""EM-201 unit tests for ``em.clock`` — time and ULID identifier primitives.

Covers the EM-201 acceptance criteria:
* ULIDs sort by creation time;
* property test ``parse_iso(to_iso(x)) == x`` at ms precision;
* legacy v2 timestamp formats parse.
"""
from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# tests run against plugins/entropicmem/scripts on the pytest pythonpath
# (pyproject [tool.pytest.ini_options]); mirror the repo conftest bootstrap so
# this file also runs standalone.
_SCRIPTS = Path(__file__).resolve().parents[2] / "plugins" / "entropicmem" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from em import clock  # noqa: E402
from em.clock import (  # noqa: E402
    freeze,
    new_id,
    parse_iso,
    short_id,
    to_iso,
    utc_now,
)

# ── utc_now / freeze ────────────────────────────────────────────────────────


def test_utc_now_is_aware_utc():
    now = utc_now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_freeze_pins_utc_now():
    pin = datetime(2026, 9, 23, 14, 5, 9, tzinfo=timezone.utc)
    with freeze(pin):
        assert utc_now() == pin
        # nested reads are stable (no clock drift inside the freeze)
        assert utc_now() == pin
    # restored after exit: back to a real, later-than-pin reading
    assert utc_now() > pin


def test_freeze_treats_naive_input_as_utc():
    with freeze(datetime(2026, 1, 1, 0, 0, 0)) as frozen:
        assert frozen.tzinfo is not None
        assert utc_now() == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_freeze_nests_and_restores_outer():
    outer = datetime(2026, 1, 1, tzinfo=timezone.utc)
    inner = datetime(2027, 6, 6, tzinfo=timezone.utc)
    with freeze(outer):
        assert utc_now() == outer
        with freeze(inner):
            assert utc_now() == inner
        assert utc_now() == outer  # outer restored, not the real clock
    assert utc_now() > outer


# ── to_iso ──────────────────────────────────────────────────────────────────


def test_to_iso_format_is_ms_precision_zulu():
    dt = datetime(2026, 9, 23, 14, 5, 9, 123000, tzinfo=timezone.utc)
    assert to_iso(dt) == "2026-09-23T14:05:09.123Z"


def test_to_iso_truncates_sub_ms_not_rounds():
    # 999_999 us must truncate to .999, never round up to the next second
    dt = datetime(2026, 9, 23, 14, 5, 9, 999999, tzinfo=timezone.utc)
    assert to_iso(dt) == "2026-09-23T14:05:09.999Z"


def test_to_iso_converts_offsets_to_utc():
    dt = datetime(2026, 9, 23, 16, 5, 9, tzinfo=timezone(timedelta(hours=2)))
    assert to_iso(dt) == "2026-09-23T14:05:09.000Z"


def test_to_iso_treats_naive_as_utc():
    dt = datetime(2026, 9, 23, 14, 5, 9)
    assert to_iso(dt) == "2026-09-23T14:05:09.000Z"


# ── parse_iso ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        # v3 canonical
        ("2026-09-23T14:05:09.123Z", datetime(2026, 9, 23, 14, 5, 9, 123000, tzinfo=timezone.utc)),
        ("2026-09-23T14:05:09Z", datetime(2026, 9, 23, 14, 5, 9, tzinfo=timezone.utc)),
        # SQLite CURRENT_TIMESTAMP (legacy v2 engine default) — space sep, naive UTC
        ("2026-09-23 14:05:09", datetime(2026, 9, 23, 14, 5, 9, tzinfo=timezone.utc)),
        # explicit +00:00 offset
        ("2026-09-23T14:05:09+00:00", datetime(2026, 9, 23, 14, 5, 9, tzinfo=timezone.utc)),
        # non-UTC offset converts to UTC
        ("2026-09-23T16:05:09+02:00", datetime(2026, 9, 23, 14, 5, 9, tzinfo=timezone.utc)),
        # microsecond precision parses (truncated to us by datetime)
        ("2026-09-23T14:05:09.123456Z", datetime(2026, 9, 23, 14, 5, 9, 123456, tzinfo=timezone.utc)),
        # lowercase z
        ("2026-09-23T14:05:09.123z", datetime(2026, 9, 23, 14, 5, 9, 123000, tzinfo=timezone.utc)),
    ],
)
def test_parse_iso_accepts_v3_and_legacy_formats(text, expected):
    assert parse_iso(text) == expected


def test_parse_iso_always_returns_aware_utc():
    for text in ("2026-09-23 14:05:09", "2026-09-23T14:05:09Z", "2026-09-23T16:05:09+02:00"):
        dt = parse_iso(text)
        assert dt.tzinfo is not None
        assert dt.utcoffset() == timedelta(0)


@pytest.mark.parametrize("bad", ["", "   ", "not-a-date", "2026-13-45T99:99:99Z", None])
def test_parse_iso_rejects_garbage(bad):
    with pytest.raises((ValueError, TypeError)):
        parse_iso(bad)


def test_parse_iso_to_iso_roundtrip_property():
    """AC: parse_iso(to_iso(x)) == x at millisecond precision, for random times."""
    rng = random.Random(20260923)
    base = datetime(1970, 1, 2, tzinfo=timezone.utc)
    for _ in range(500):
        span = rng.randrange(0, (2100 - 1970) * 365 * 24 * 3600)
        micros = rng.randrange(0, 1_000_000)
        dt = base + timedelta(seconds=span, microseconds=micros)
        # to_iso truncates to ms, so compare against the ms-truncated input
        expected = dt.replace(microsecond=(dt.microsecond // 1000) * 1000)
        assert parse_iso(to_iso(dt)) == expected


# ── new_id (ULID) ───────────────────────────────────────────────────────────


def test_new_id_shape_and_prefix():
    with freeze(datetime(2026, 9, 23, 14, 5, 9, tzinfo=timezone.utc)):
        ident = new_id("mem")
    assert ident.startswith("mem_")
    body = ident.split("_", 1)[1]
    assert len(body) == 26  # 10 time chars + 16 random chars
    # Crockford base32 alphabet only (no I, L, O, U)
    assert set(body) <= set(clock._ALPHABET)


def test_new_id_normalises_trailing_underscore_prefix():
    with freeze(datetime(2026, 9, 23, tzinfo=timezone.utc)):
        assert new_id("mem_").count("_") == 1


def test_ulids_sort_by_creation_time():
    """AC: ULIDs sort by creation time (lexicographic == chronological)."""
    base = datetime(2026, 9, 23, 14, 5, 9, tzinfo=timezone.utc)
    ids = []
    for i in range(50):
        with freeze(base + timedelta(milliseconds=i * 7)):
            ids.append(new_id("mem"))
    assert ids == sorted(ids), "ULIDs generated in time order must already be sorted"
    # shuffled copy sorts back to the same chronological order
    shuffled = ids[:]
    random.Random(1).shuffle(shuffled)
    assert sorted(shuffled) == ids


def test_ulid_time_order_holds_across_large_gaps():
    early = datetime(2026, 1, 1, tzinfo=timezone.utc)
    late = datetime(2099, 12, 31, tzinfo=timezone.utc)
    with freeze(early):
        a = new_id("ep")
    with freeze(late):
        b = new_id("ep")
    assert a < b


def test_new_id_unique_under_same_frozen_ms():
    with freeze(datetime(2026, 9, 23, 14, 5, 9, tzinfo=timezone.utc)):
        batch = {new_id("mem") for _ in range(1000)}
    assert len(batch) == 1000  # random component keeps them distinct


def test_new_id_same_frozen_time_shares_time_component():
    with freeze(datetime(2026, 9, 23, 14, 5, 9, 123000, tzinfo=timezone.utc)):
        a = new_id("mem")
        b = new_id("mem")
    # identical 10-char time prefix, differing random suffix
    assert a.split("_", 1)[1][:10] == b.split("_", 1)[1][:10]
    assert a != b


@pytest.mark.parametrize("bad", ["", "mem space", "a-b", "1mem?", "mem__x", None, 123])
def test_new_id_rejects_bad_prefix(bad):
    with pytest.raises((ValueError, TypeError, AttributeError)):
        new_id(bad)


def test_new_id_rejects_out_of_range_time():
    with freeze(datetime(1960, 1, 1, tzinfo=timezone.utc)):  # pre-epoch -> negative ms
        with pytest.raises(ValueError):
            new_id("mem")


def test_new_id_uses_explicit_now_over_clock():
    explicit = datetime(2030, 1, 1, tzinfo=timezone.utc)
    with freeze(datetime(2026, 9, 23, tzinfo=timezone.utc)):
        a = new_id("mem", now=explicit)
        b = new_id("mem")  # uses the frozen 2026 clock
    assert a.split("_", 1)[1][:10] != b.split("_", 1)[1][:10]
    assert a > b  # 2030 sorts after 2026


# ── short_id ────────────────────────────────────────────────────────────────


def test_short_id_returns_last_eight():
    assert short_id("mem_0123456789ABCDEFGHIJKLMN") == "GHIJKLMN"
    assert short_id("01J8Z9ABCDEFGHJKMN") == "EFGHJKMN"


def test_short_id_of_generated_id_is_eight_chars():
    with freeze(datetime(2026, 9, 23, tzinfo=timezone.utc)):
        ident = new_id("mem")
    assert len(short_id(ident)) == 8


def test_short_id_handles_short_and_empty():
    assert short_id("abc") == "abc"
    assert short_id("") == ""


# ── module surface ──────────────────────────────────────────────────────────


def test_all_exports_are_present():
    for name in clock.__all__:
        assert hasattr(clock, name), name
