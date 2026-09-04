"""Deterministic US equity-session calendar used by scheduled automation.

It covers recurring full-day NYSE holidays. Exceptional exchange closures are
still surfaced by the freshness watchdog instead of being guessed.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta


def _observed(day):
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _nth_weekday(year, month, weekday, occurrence):
    current = date(year, month, 1)
    current += timedelta(days=(weekday - current.weekday()) % 7)
    return current + timedelta(weeks=occurrence - 1)


def _last_weekday(year, month, weekday):
    if month == 12:
        current = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        current = date(year, month + 1, 1) - timedelta(days=1)
    return current - timedelta(days=(current.weekday() - weekday) % 7)


def easter_sunday(year):
    """Gregorian computus, valid for the modern NYSE calendar."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def us_equity_holidays(year):
    holidays = {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),       # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),       # Washington's Birthday
        easter_sunday(year) - timedelta(days=2),
        _last_weekday(year, 5, 0),         # Memorial Day
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),       # Labor Day
        _nth_weekday(year, 11, 3, 4),      # Thanksgiving
        _observed(date(year, 12, 25)),
    }
    if year >= 2022:
        holidays.add(_observed(date(year, 6, 19)))
    # New Year's Day can be observed on December 31 of the prior year.
    next_new_year = _observed(date(year + 1, 1, 1))
    if next_new_year.year == year:
        holidays.add(next_new_year)
    return holidays


def is_us_equity_session(value):
    day = value.date() if isinstance(value, datetime) else value
    return isinstance(day, date) and day.weekday() < 5 and day not in us_equity_holidays(day.year)


def previous_us_equity_session(value):
    day = value.date() if isinstance(value, datetime) else value
    candidate = day - timedelta(days=1)
    while not is_us_equity_session(candidate):
        candidate -= timedelta(days=1)
    return candidate


def expected_market_date(now, cutoff_minutes):
    """Latest session whose scheduled cutoff should already have passed."""
    minutes = now.hour * 60 + now.minute
    if is_us_equity_session(now) and minutes >= int(cutoff_minutes):
        return now.date()
    return previous_us_equity_session(now)
