"""``TimeRange`` — the temporal filter §3.6 applies to candidates.

Only the *type* lives here today. Parsing ("since X", "last N days", "between
X and Y", …) is EM-310, which owns this file; §3.6 applies the resulting range
to ``COALESCE(valid_from, created_at)`` for memories and ``start_at`` for
episodes, and EM-302 does exactly that with the values below.

Stdlib only (plan §3.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

__all__ = ["TimeRange"]


@dataclass(frozen=True)
class TimeRange:
    """Inclusive window over *world* time.

    Both bounds are optional, so the three shapes §3.6 needs are expressible:
    ``start`` alone ("since X"), ``end`` alone ("before X"), and both
    ("between X and Y"). "Last 30 days" is deliberately a range and not a day
    (§3.6), which this models directly.
    """

    start: Optional[datetime] = None
    end: Optional[datetime] = None
