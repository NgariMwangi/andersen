"""Public holidays: excluded from working-day leave counts (per company + country)."""
from __future__ import annotations

import calendar
from datetime import date

from app.extensions import db
from app.models.leave import PublicHoliday
from sqlalchemy import func, or_


def recurring_holiday_date_in_year(year: int, month: int, day: int) -> date:
    """
    Calendar date for a recurring holiday in `year`.
    Feb 29 in a non-leap year becomes Feb 28 (observed).
    """
    last = calendar.monthrange(year, month)[1]
    d = min(day, last)
    return date(year, month, d)


def public_holiday_dates_in_range(
    start: date,
    end: date,
    company_id: int,
    country_code: str,
) -> set[date]:
    """All public holiday dates in [start, end] for tenant `company_id` and branch country."""
    if start > end:
        return set()
    cc = (country_code or 'KE').upper()[:2]
    accepted_countries = {cc, 'KE'}
    out: set[date] = set()
    y0, y1 = start.year, end.year
    # Match holiday country in a tolerant way for legacy rows:
    # - case-insensitive (ke == KE)
    # - blank/null treated as KE
    country_match = or_(
        func.upper(func.coalesce(PublicHoliday.country_code, 'KE')).in_(accepted_countries),
        func.trim(func.coalesce(PublicHoliday.country_code, '')) == '',
    )

    one_offs = (
        db.session.query(PublicHoliday)
        .filter(
            PublicHoliday.company_id == company_id,
            country_match,
            PublicHoliday.kind == 'one_off',
            PublicHoliday.date.isnot(None),
            PublicHoliday.date >= start,
            PublicHoliday.date <= end,
        )
        .all()
    )
    for h in one_offs:
        out.add(h.date)

    recurring = (
        db.session.query(PublicHoliday)
        .filter(
            PublicHoliday.company_id == company_id,
            country_match,
            PublicHoliday.kind == 'recurring',
            PublicHoliday.recurring_month.isnot(None),
            PublicHoliday.recurring_day.isnot(None),
        )
        .all()
    )
    for h in recurring:
        m, d = h.recurring_month, h.recurring_day
        for y in range(y0, y1 + 1):
            try:
                occ = recurring_holiday_date_in_year(y, m, d)
            except ValueError:
                continue
            if start <= occ <= end:
                out.add(occ)

    return out
