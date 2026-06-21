"""Date helpers for payroll and leave."""
from datetime import date, timedelta
from calendar import monthrange


def last_day_of_month(year: int, month: int) -> date:
    """Last day of month."""
    _, last = monthrange(year, month)
    return date(year, month, last)


def first_day_of_month(year: int, month: int) -> date:
    """First day of month."""
    return date(year, month, 1)


def months_between(start: date, end: date) -> int:
    """Number of full months between two dates (inclusive of partial months)."""
    if start > end:
        return 0
    return (end.year - start.year) * 12 + (end.month - start.month) + 1


def working_days_between(start: date, end: date, exclude_dates: set = None) -> int:
    """Count working days (Mon-Fri) between start and end, inclusive. exclude_dates = dates to skip (e.g. holidays)."""
    exclude_dates = exclude_dates or set()
    count = 0
    d = start
    while d <= end:
        if d.weekday() < 5 and d not in exclude_dates:
            count += 1
        d += timedelta(days=1)
    return count


def calendar_days_between(start: date, end: date, exclude_dates: set = None) -> int:
    """Count calendar days from start through end, inclusive, excluding explicit dates when provided."""
    if start > end:
        return 0
    exclude_dates = exclude_dates or set()
    count = 0
    d = start
    while d <= end:
        if d not in exclude_dates:
            count += 1
        d += timedelta(days=1)
    return count


def leave_days_between(start: date, end: date, basis: str, exclude_dates: set = None) -> int:
    """
    basis: 'working' — Mon–Fri only; 'calendar' — every day in range.
    """
    if basis == 'calendar':
        return calendar_days_between(start, end, exclude_dates=exclude_dates)
    return working_days_between(start, end, exclude_dates=exclude_dates)


def approved_leave_remaining_days(
    start: date,
    end: date,
    basis: str,
    today: date | None = None,
    exclude_dates: set = None,
) -> int:
    """
    Days still to run in an approved leave window (same basis as the request).
    Before leave starts: full period length. During leave: from today through end. After end: 0.
    """
    today = today or date.today()
    if start > end:
        return 0
    if end < today:
        return 0
    period_start = start if today < start else today
    return leave_days_between(period_start, end, basis, exclude_dates=exclude_dates)


def end_date_for_inclusive_leave_days(
    start: date,
    total_days: int,
    basis: str,
    exclude_dates: set = None,
) -> date:
    """
    Last calendar date of a period of `total_days` leave days starting on `start` (inclusive).
    Example: 90 calendar days from 1 Jan -> 30 Mar; 14 working days from Thu -> following Wed if weekends skip.
    """
    if total_days <= 0:
        return start
    if total_days == 1:
        return start
    exclude_dates = exclude_dates or set()
    if basis == 'calendar':
        # Calendar basis can still skip explicit excluded dates (e.g. configured public holidays).
        remaining = total_days - 1
        d = start
        while remaining > 0:
            d += timedelta(days=1)
            if d not in exclude_dates:
                remaining -= 1
        return d
    # working days: start is day 1
    remaining = total_days - 1
    d = start
    while remaining > 0:
        d += timedelta(days=1)
        if d.weekday() < 5 and d not in exclude_dates:
            remaining -= 1
    return d
