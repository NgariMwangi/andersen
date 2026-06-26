"""Bulk historical leave entry — select many calendar days at once for data migration."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.employee import Employee
from app.models.leave import LeaveRequest, LeaveType
from app.services.leave_balance_service import refresh_leave_balance_after_request_change
from app.services.public_holiday_service import public_holiday_dates_in_range
from app.utils.date_helpers import parse_leave_day_portion


@dataclass
class BulkLeaveEntryResult:
    created_requests: int = 0
    total_days: Decimal = Decimal('0')
    conflict_dates: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _leave_dates_in_request(lr: LeaveRequest, *, company_id: int, country_code: str) -> set[date]:
    """Individual leave days covered by an approved request."""
    lt = lr.leave_type or db.session.get(LeaveType, lr.leave_type_id)
    basis = (lt.days_count_basis if lt else 'working') or 'working'
    if basis not in ('working', 'calendar'):
        basis = 'working'
    excl = public_holiday_dates_in_range(lr.start_date, lr.end_date, company_id, country_code)
    out: set[date] = set()
    d = lr.start_date
    while d <= lr.end_date:
        if basis == 'calendar':
            if d not in excl:
                out.add(d)
        elif d.weekday() < 5 and d not in excl:
            out.add(d)
        d += timedelta(days=1)
    return out


def approved_leave_dates_for_employee(
    employee_id: int,
    year: int,
    *,
    leave_type_id: int | None = None,
) -> set[date]:
    """All calendar days already covered by approved leave in `year`."""
    y0 = date(year, 1, 1)
    y1 = date(year, 12, 31)
    q = (
        db.session.query(LeaveRequest)
        .filter(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.status == 'approved',
            LeaveRequest.start_date <= y1,
            LeaveRequest.end_date >= y0,
        )
    )
    if leave_type_id:
        q = q.filter(LeaveRequest.leave_type_id == leave_type_id)

    emp = db.session.get(Employee, employee_id)
    company_id = emp.company_id if emp else 0
    country_code = (emp.branch.country_code if emp and emp.branch else 'KE') or 'KE'

    out: set[date] = set()
    for lr in q.options(joinedload(LeaveRequest.leave_type)).all():
        for d in _leave_dates_in_request(lr, company_id=company_id, country_code=country_code):
            if y0 <= d <= y1:
                out.add(d)
    return out


def merge_consecutive_dates(dates: list[date]) -> list[list[date]]:
    """Group selected dates into runs of consecutive calendar days."""
    if not dates:
        return []
    unique = sorted(set(dates))
    groups: list[list[date]] = [[unique[0]]]
    for d in unique[1:]:
        if (d - groups[-1][-1]).days == 1:
            groups[-1].append(d)
        else:
            groups.append([d])
    return groups


def parse_bulk_selected_dates(raw: str) -> list[tuple[date, Decimal]]:
    """Parse JSON [{date, portion}] or '2026-01-15:0.5,2026-01-16:0.5' or legacy '2026-01-15'."""
    text = (raw or '').strip()
    if not text:
        return []

    if text.startswith('['):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, list):
            out: list[tuple[date, Decimal]] = []
            for item in payload:
                if not isinstance(item, dict):
                    continue
                date_s = item.get('date')
                if not date_s:
                    continue
                try:
                    out.append(
                        (
                            date.fromisoformat(str(date_s).strip()),
                            parse_leave_day_portion(item.get('portion', '1')),
                        )
                    )
                except ValueError:
                    continue
            if out:
                return out

    out = []
    for part in text.split(','):
        part = part.strip()
        if not part:
            continue
        if ':' in part:
            date_s, portion_s = part.split(':', 1)
            try:
                out.append((date.fromisoformat(date_s.strip()), parse_leave_day_portion(portion_s.strip())))
            except ValueError:
                continue
        else:
            try:
                out.append((date.fromisoformat(part), Decimal('1')))
            except ValueError:
                continue
    return out


def merge_consecutive_day_portions(
    items: list[tuple[date, Decimal]],
) -> list[tuple[list[date], Decimal]]:
    """
    Group consecutive full-day (1.0) selections into one request.

    Partial days (0.5, 0.25) always become separate single-day records so each
    calendar day keeps its chosen length.
    """
    if not items:
        return []
    sorted_items = sorted(items, key=lambda item: item[0])
    groups: list[list[tuple[date, Decimal]]] = []

    for d, portion in sorted_items:
        if portion != Decimal('1'):
            groups.append([(d, portion)])
            continue
        if (
            groups
            and all(p == Decimal('1') for _, p in groups[-1])
            and (d - groups[-1][-1][0]).days == 1
        ):
            groups[-1].append((d, portion))
        else:
            groups.append([(d, portion)])

    merged: list[tuple[list[date], Decimal]] = []
    for group in groups:
        dates = [item[0] for item in group]
        total = sum((item[1] for item in group), Decimal('0')).quantize(Decimal('0.01'))
        merged.append((dates, total))
    return merged


def bulk_entry_context(
    employee_id: int,
    leave_type_id: int,
    year: int,
) -> dict | None:
    emp = db.session.get(Employee, employee_id)
    lt = db.session.get(LeaveType, leave_type_id)
    if not emp or not lt or lt.company_id != emp.company_id or not lt.is_active:
        return None

    company_id = emp.company_id
    country_code = (emp.branch.country_code if emp.branch else 'KE') or 'KE'
    holidays = public_holiday_dates_in_range(date(year, 1, 1), date(year, 12, 31), company_id, country_code)
    booked = approved_leave_dates_for_employee(employee_id, year)
    same_type = approved_leave_dates_for_employee(employee_id, year, leave_type_id=leave_type_id)

    from app.models.leave import LeaveRequest as LR

    used = (
        db.session.query(func.coalesce(func.sum(LR.days_requested), 0))
        .filter(
            LR.employee_id == employee_id,
            LR.leave_type_id == leave_type_id,
            LR.status == 'approved',
            LR.start_date >= date(year, 1, 1),
            LR.start_date <= date(year, 12, 31),
        )
        .scalar()
    )

    return {
        'basis': (lt.days_count_basis or 'working').lower(),
        'leave_type_name': lt.name,
        'holidays': sorted(d.isoformat() for d in holidays),
        'booked_dates': sorted(d.isoformat() for d in booked),
        'same_type_dates': sorted(d.isoformat() for d in same_type),
        'used_days': str(Decimal(str(used or 0)).quantize(Decimal('0.01'))),
        'entitlement': str(lt.days_per_year) if lt.days_per_year is not None else None,
    }


def record_bulk_historical_leave(
    *,
    employee_id: int,
    leave_type_id: int,
    year: int,
    selected_days: list[tuple[date, Decimal]],
    recorded_by_user_id: int,
    notes: str | None = None,
) -> BulkLeaveEntryResult:
    result = BulkLeaveEntryResult()
    emp = db.session.get(Employee, employee_id)
    lt = db.session.get(LeaveType, leave_type_id)
    if not emp or not lt or lt.company_id != emp.company_id or not lt.is_active:
        result.errors.append('Invalid employee or leave type.')
        return result

    y0 = date(year, 1, 1)
    y1 = date(year, 12, 31)
    in_year = sorted({d for d, _ in selected_days if y0 <= d <= y1}, key=lambda d: d)
    if not in_year:
        result.errors.append('Select at least one day in the chosen year.')
        return result

    in_year_set = set(in_year)
    selected_in_year = [(d, p) for d, p in selected_days if d in in_year_set]

    booked = approved_leave_dates_for_employee(employee_id, year)
    conflicts = [d for d in in_year if d in booked]
    if conflicts:
        result.conflict_dates = [d.isoformat() for d in conflicts]
        result.errors.append(
            f'{len(conflicts)} selected day(s) already have approved leave. Clear those dates or remove them from your selection.'
        )
        return result

    note_text = (notes or '').strip()
    review_notes = 'Historical leave data entry (calendar bulk).'
    if note_text:
        review_notes = f'{review_notes} {note_text}'

    years_touched: set[int] = set()
    for dates, days in merge_consecutive_day_portions(selected_in_year):
        lr = LeaveRequest(
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            start_date=dates[0],
            end_date=dates[-1],
            days_requested=days,
            reason=note_text or 'Leave taken (recorded during HR data entry).',
            status='approved',
            reviewed_by_id=recorded_by_user_id,
            reviewed_at=datetime.utcnow(),
            review_notes=review_notes,
        )
        db.session.add(lr)
        result.created_requests += 1
        result.total_days += days
        years_touched.add(dates[0].year)
        if dates[-1].year != dates[0].year:
            years_touched.add(dates[-1].year)

    for y in years_touched:
        refresh_leave_balance_after_request_change(employee_id, leave_type_id, y)

    return result
