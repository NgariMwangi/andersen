"""Book company mandatory annual leave for all active employees."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.employee import Employee
from app.models.leave import LeaveRequest, LeaveType
from app.services.leave_approval_service import (
    LEAVE_STATUS_APPROVED,
    LEAVE_STATUS_BOOKED,
    LEAVE_STATUSES_TAKEN,
)
from app.services.leave_balance_service import refresh_leave_balance_after_request_change
from app.services.leave_bulk_entry_service import (
    _leave_dates_in_request,
    merge_consecutive_dates,
)
from app.services.public_holiday_service import public_holiday_dates_in_range

DEFAULT_MANDATORY_REASON = 'Company mandatory annual leave'
MANDATORY_REVIEW_NOTES = 'Booked as company mandatory annual leave.'


@dataclass
class MandatoryLeaveResult:
    employees_processed: int = 0
    employees_booked: int = 0
    employees_skipped_covered: int = 0
    created_requests: int = 0
    total_days: Decimal = Decimal('0')
    errors: list[str] = field(default_factory=list)
    skipped_names: list[str] = field(default_factory=list)


def _country_for_employee(emp: Employee) -> str:
    if emp.branch and emp.branch.country_code:
        return (emp.branch.country_code or 'KE').upper()[:2]
    return 'KE'


def _mandatory_leave_query(company_id: int):
    """Leave requests created by company mandatory booking for this company."""
    return (
        db.session.query(LeaveRequest)
        .join(Employee, Employee.id == LeaveRequest.employee_id)
        .filter(
            Employee.company_id == company_id,
            db.or_(
                LeaveRequest.status == LEAVE_STATUS_BOOKED,
                LeaveRequest.review_notes == MANDATORY_REVIEW_NOTES,
            ),
        )
    )


def migrate_mandatory_leave_status_to_booked(company_id: int) -> int:
    """
    Flip legacy mandatory leave rows from approved → booked
    (identified by review notes written at booking time).
    """
    rows = (
        db.session.query(LeaveRequest)
        .join(Employee, Employee.id == LeaveRequest.employee_id)
        .filter(
            Employee.company_id == company_id,
            LeaveRequest.status == LEAVE_STATUS_APPROVED,
            LeaveRequest.review_notes == MANDATORY_REVIEW_NOTES,
        )
        .all()
    )
    if not rows:
        return 0
    for lr in rows:
        lr.status = LEAVE_STATUS_BOOKED
    db.session.commit()
    return len(rows)


def list_mandatory_leave_periods(company_id: int) -> list[dict]:
    """
    Distinct mandatory leave date windows for the company, with employee counts.
    Sorted newest start date first.
    """
    rows = (
        _mandatory_leave_query(company_id)
        .options(joinedload(LeaveRequest.employee))
        .order_by(LeaveRequest.start_date.desc(), LeaveRequest.end_date.desc(), LeaveRequest.id.desc())
        .all()
    )
    groups: dict[tuple, dict] = {}
    for lr in rows:
        key = (lr.start_date, lr.end_date, (lr.reason or '').strip())
        if key not in groups:
            groups[key] = {
                'start_date': lr.start_date,
                'end_date': lr.end_date,
                'reason': (lr.reason or '').strip() or DEFAULT_MANDATORY_REASON,
                'employee_count': 0,
                'request_count': 0,
                'total_days': Decimal('0'),
                'booked_at': lr.reviewed_at or getattr(lr, 'created_at', None),
                'employee_ids': set(),
            }
        g = groups[key]
        g['request_count'] += 1
        g['total_days'] += Decimal(str(lr.days_requested or 0))
        if lr.employee_id not in g['employee_ids']:
            g['employee_ids'].add(lr.employee_id)
            g['employee_count'] += 1
        stamped = lr.reviewed_at or getattr(lr, 'created_at', None)
        if stamped and (g['booked_at'] is None or stamped > g['booked_at']):
            g['booked_at'] = stamped

    periods = []
    for g in groups.values():
        g.pop('employee_ids', None)
        periods.append(g)
    periods.sort(key=lambda p: (p['start_date'] or date.min, p['end_date'] or date.min), reverse=True)
    return periods


def list_mandatory_leave_requests(company_id: int) -> list[LeaveRequest]:
    """Individual mandatory/booked leave rows for the company (newest first)."""
    return (
        _mandatory_leave_query(company_id)
        .options(
            joinedload(LeaveRequest.employee),
            joinedload(LeaveRequest.leave_type),
        )
        .order_by(
            LeaveRequest.start_date.desc(),
            LeaveRequest.end_date.desc(),
            Employee.last_name.asc(),
            Employee.first_name.asc(),
            LeaveRequest.id.desc(),
        )
        .all()
    )


def _chargeable_dates_in_range(
    start: date,
    end: date,
    *,
    basis: str,
    company_id: int,
    country_code: str,
) -> list[date]:
    """Leave-countable days in [start, end] for the given basis."""
    basis = (basis or 'working').strip().lower()
    if basis not in ('working', 'calendar'):
        basis = 'working'
    excl = public_holiday_dates_in_range(start, end, company_id, country_code)
    out: list[date] = []
    d = start
    while d <= end:
        if basis == 'calendar':
            if d not in excl:
                out.append(d)
        elif d.weekday() < 5 and d not in excl:
            out.append(d)
        d += timedelta(days=1)
    return out


def approved_leave_dates_in_range(
    employee_id: int,
    start: date,
    end: date,
) -> set[date]:
    """Days already covered by approved or booked leave overlapping [start, end]."""
    emp = db.session.get(Employee, employee_id)
    if not emp:
        return set()
    company_id = emp.company_id
    country_code = _country_for_employee(emp)
    rows = (
        db.session.query(LeaveRequest)
        .options(joinedload(LeaveRequest.leave_type))
        .filter(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.status.in_(tuple(LEAVE_STATUSES_TAKEN)),
            LeaveRequest.start_date <= end,
            LeaveRequest.end_date >= start,
        )
        .all()
    )
    covered: set[date] = set()
    for lr in rows:
        for d in _leave_dates_in_request(lr, company_id=company_id, country_code=country_code):
            if start <= d <= end:
                covered.add(d)
    return covered


def book_mandatory_annual_leave(
    company_id: int,
    start_date: date,
    end_date: date,
    *,
    reason: str | None = None,
    reviewed_by_user_id: int,
) -> MandatoryLeaveResult:
    """
    Create booked ANNUAL leave for all active employees for the date range.

    Days already covered by approved or booked leave are not charged again.
    Remaining days are stored as contiguous booked leave segments.
    """
    result = MandatoryLeaveResult()
    if not start_date or not end_date:
        result.errors.append('Start and end dates are required.')
        return result
    if end_date < start_date:
        result.errors.append('End date must be on or after the start date.')
        return result

    annual = (
        db.session.query(LeaveType)
        .filter(
            LeaveType.company_id == company_id,
            LeaveType.code == 'ANNUAL',
            LeaveType.is_active.is_(True),
        )
        .first()
    )
    if not annual:
        result.errors.append(
            'No active Annual leave type (code ANNUAL) is configured for this company.'
        )
        return result

    basis = (annual.days_count_basis or 'working').strip().lower()
    reason_text = (reason or '').strip() or DEFAULT_MANDATORY_REASON
    review_notes = MANDATORY_REVIEW_NOTES

    employees = (
        db.session.query(Employee)
        .options(joinedload(Employee.branch))
        .filter(Employee.company_id == company_id, Employee.status == 'active')
        .order_by(Employee.last_name, Employee.first_name)
        .all()
    )
    result.employees_processed = len(employees)

    for emp in employees:
        try:
            country = _country_for_employee(emp)
            chargeable = _chargeable_dates_in_range(
                start_date,
                end_date,
                basis=basis,
                company_id=company_id,
                country_code=country,
            )
            if not chargeable:
                result.employees_skipped_covered += 1
                result.skipped_names.append(emp.full_name)
                continue

            already = approved_leave_dates_in_range(emp.id, start_date, end_date)
            remaining = [d for d in chargeable if d not in already]
            if not remaining:
                result.employees_skipped_covered += 1
                result.skipped_names.append(emp.full_name)
                continue

            years_touched: set[int] = set()
            booked_any = False
            for segment in merge_consecutive_dates(remaining):
                days = Decimal(len(segment)).quantize(Decimal('0.01'))
                lr = LeaveRequest(
                    employee_id=emp.id,
                    leave_type_id=annual.id,
                    start_date=segment[0],
                    end_date=segment[-1],
                    days_requested=days,
                    reason=reason_text,
                    status=LEAVE_STATUS_BOOKED,
                    reviewed_by_id=reviewed_by_user_id,
                    reviewed_at=datetime.utcnow(),
                    review_notes=review_notes,
                )
                db.session.add(lr)
                result.created_requests += 1
                result.total_days += days
                years_touched.add(segment[0].year)
                years_touched.add(segment[-1].year)
                booked_any = True

            if booked_any:
                result.employees_booked += 1
                for y in years_touched:
                    refresh_leave_balance_after_request_change(emp.id, annual.id, y)
        except Exception as exc:
            result.errors.append(f'{emp.full_name}: {exc}')

    return result
