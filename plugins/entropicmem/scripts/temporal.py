"""
temporal.py — Natural language date parsing for EntropicMem (Phase 8).

Parses NL date expressions like "last Tuesday", "in March", "2 weeks ago"
into ISO date ranges for SQL filtering.

Stdlib-only. No external dependencies.
"""

import re
from datetime import date, timedelta
from typing import Optional, Tuple


def parse_temporal_query(text: str) -> Optional[Tuple[str, str]]:
    """
    Parse a natural language date expression into (from_date, to_date) ISO strings.

    Supported patterns:
      - "last Tuesday" / "last friday"
      - "yesterday" / "today"
      - "2 weeks ago" / "3 days ago" / "1 month ago"
      - "in March" / "in 2026"
      - "last week" / "last month" / "last year"
      - "this week" / "this month"

    Returns None if no temporal pattern is detected.
    """
    text_lower = text.lower().strip()
    today = date.today()

    # "yesterday"
    if "yesterday" in text_lower:
        d = today - timedelta(days=1)
        return (d.isoformat(), d.isoformat())

    # "today"
    if "today" in text_lower:
        return (today.isoformat(), today.isoformat())

    # "last week"
    if "last week" in text_lower:
        # Monday of last week to Sunday of last week
        days_since_monday = today.weekday()
        this_monday = today - timedelta(days=days_since_monday)
        last_monday = this_monday - timedelta(days=7)
        last_sunday = this_monday - timedelta(days=1)
        return (last_monday.isoformat(), last_sunday.isoformat())

    # "this week"
    if "this week" in text_lower:
        days_since_monday = today.weekday()
        this_monday = today - timedelta(days=days_since_monday)
        this_sunday = this_monday + timedelta(days=6)
        return (this_monday.isoformat(), this_sunday.isoformat())

    # "last month"
    if "last month" in text_lower:
        first_of_this_month = today.replace(day=1)
        last_of_prev_month = first_of_this_month - timedelta(days=1)
        first_of_prev_month = last_of_prev_month.replace(day=1)
        return (first_of_prev_month.isoformat(), last_of_prev_month.isoformat())

    # "this month"
    if "this month" in text_lower:
        first = today.replace(day=1)
        return (first.isoformat(), today.isoformat())

    # "last year"
    if "last year" in text_lower:
        prev_year = today.year - 1
        return (f"{prev_year}-01-01", f"{prev_year}-12-31")

    # "N days/weeks/months ago"
    m = re.search(r"(\d+)\s+(day|week|month|year)s?\s+ago", text_lower)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit == "day":
            d = today - timedelta(days=n)
        elif unit == "week":
            d = today - timedelta(weeks=n)
        elif unit == "month":
            # Approximate: 30 days per month
            d = today - timedelta(days=n * 30)
        elif unit == "year":
            d = today - timedelta(days=n * 365)
        else:
            return None
        return (d.isoformat(), d.isoformat())

    # "last <weekday>"
    weekdays = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    for name, wd in weekdays.items():
        if f"last {name}" in text_lower:
            days_back = (today.weekday() - wd) % 7
            if days_back == 0:
                days_back = 7
            d = today - timedelta(days=days_back)
            return (d.isoformat(), d.isoformat())

    # "in March" / "in 2026"
    months = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }
    for name, month_num in months.items():
        if f"in {name}" in text_lower:
            year = today.year
            # If the month is in the future this year, assume last year
            if month_num > today.month:
                year -= 1
            # Last day of month
            if month_num == 12:
                last_day = date(year, 12, 31)
            else:
                last_day = date(year, month_num + 1, 1) - timedelta(days=1)
            return (f"{year}-{month_num:02d}-01", last_day.isoformat())

    # "in YYYY"
    m = re.search(r"\bin\s+(20\d{2})\b", text_lower)
    if m:
        year = int(m.group(1))
        return (f"{year}-01-01", f"{year}-12-31")

    return None


def extract_temporal_filter(query: str) -> Tuple[str, Optional[Tuple[str, str]]]:
    """
    Extract temporal filter from a query, returning (cleaned_query, date_range).

    The cleaned query has temporal phrases removed so FTS5 doesn't choke on them.
    """
    date_range = parse_temporal_query(query)
    if date_range is None:
        return (query, None)

    # Remove temporal phrases from the query for FTS5
    cleaned = query
    temporal_phrases = [
        r"\blast\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\blast\s+(week|month|year)\b",
        r"\bthis\s+(week|month)\b",
        r"\byesterday\b",
        r"\btoday\b",
        r"\b\d+\s+(day|week|month|year)s?\s+ago\b",
        r"\bin\s+(january|february|march|april|may|june|july|august|september|october|november|december)\b",
        r"\bin\s+20\d{2}\b",
    ]
    for pattern in temporal_phrases:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    # Clean up extra whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return (cleaned, date_range)
