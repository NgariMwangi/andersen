"""Employee employment status helpers (including pre-join / pending join)."""
from __future__ import annotations

from datetime import date

from app.extensions import db
from app.models.employee import Employee

EMPLOYEE_STATUS_ACTIVE = 'active'
EMPLOYEE_STATUS_PENDING_JOIN = 'pending_join'
EMPLOYEE_STATUS_ON_LEAVE = 'on_leave'
EMPLOYEE_STATUS_SUSPENDED = 'suspended'
EMPLOYEE_STATUS_TERMINATED = 'terminated'
EMPLOYEE_STATUS_RESIGNED = 'resigned'
EMPLOYEE_STATUS_RETIRED = 'retired'

# Cannot sign in or receive new login accounts.
LOGIN_BLOCKED_EMPLOYEE_STATUSES = frozenset({
    EMPLOYEE_STATUS_PENDING_JOIN,
    EMPLOYEE_STATUS_SUSPENDED,
    EMPLOYEE_STATUS_TERMINATED,
    EMPLOYEE_STATUS_RESIGNED,
    EMPLOYEE_STATUS_RETIRED,
})

_STATUS_LABELS = {
    EMPLOYEE_STATUS_ACTIVE: 'Active',
    EMPLOYEE_STATUS_PENDING_JOIN: 'Pending join',
    EMPLOYEE_STATUS_ON_LEAVE: 'On leave',
    EMPLOYEE_STATUS_SUSPENDED: 'Suspended',
    EMPLOYEE_STATUS_TERMINATED: 'Terminated',
    EMPLOYEE_STATUS_RESIGNED: 'Resigned',
    EMPLOYEE_STATUS_RETIRED: 'Retired',
}


def employee_status_label(status: str | None) -> str:
    key = (status or '').strip().lower()
    return _STATUS_LABELS.get(key, key.replace('_', ' ').title() if key else '—')


def employee_has_started(employee: Employee | None, *, today: date | None = None) -> bool:
    """True when the employee is active and their hire date has been reached."""
    if not employee:
        return False
    if (employee.status or '').strip().lower() != EMPLOYEE_STATUS_ACTIVE:
        return False
    if not employee.hire_date:
        return True
    today = today or date.today()
    return employee.hire_date <= today


def employee_is_pending_join(employee: Employee | None, *, today: date | None = None) -> bool:
    """True while recorded as pending join (including before hire date)."""
    if not employee:
        return False
    return (employee.status or '').strip().lower() == EMPLOYEE_STATUS_PENDING_JOIN


def employee_is_operational(employee: Employee | None, *, today: date | None = None) -> bool:
    """Participates in day-to-day HR ops: leave, handover, headcount, mandatory leave."""
    return employee_has_started(employee, today=today)


def resolve_employee_status_on_save(status: str | None, hire_date: date | None) -> str:
    """
    Align status with hire date when HR saves an employee.
    Future hire + active → pending_join; past hire + pending_join → active.
    """
    resolved = (status or EMPLOYEE_STATUS_ACTIVE).strip().lower()
    if not hire_date:
        return resolved
    today = date.today()
    if hire_date > today and resolved == EMPLOYEE_STATUS_ACTIVE:
        return EMPLOYEE_STATUS_PENDING_JOIN
    if hire_date <= today and resolved == EMPLOYEE_STATUS_PENDING_JOIN:
        return EMPLOYEE_STATUS_ACTIVE
    return resolved


def operational_employee_filters(*, today: date | None = None):
    """SQLAlchemy filter clauses for started, active employees."""
    today = today or date.today()
    return (
        Employee.status == EMPLOYEE_STATUS_ACTIVE,
        Employee.hire_date <= today,
    )


def apply_operational_employee_filter(query, *, today: date | None = None):
    return query.filter(*operational_employee_filters(today=today))


def activate_due_pending_join_employees(company_id: int | None = None, *, commit: bool = True) -> int:
    """
    Promote pending_join → active when hire_date is today or earlier.
    Returns the number of employees activated.
    """
    today = date.today()
    q = db.session.query(Employee).filter(
        Employee.status == EMPLOYEE_STATUS_PENDING_JOIN,
        Employee.hire_date <= today,
    )
    if company_id is not None:
        q = q.filter(Employee.company_id == company_id)
    rows = q.all()
    if not rows:
        return 0
    for emp in rows:
        emp.status = EMPLOYEE_STATUS_ACTIVE
    if commit:
        db.session.commit()
    return len(rows)


def employee_may_receive_login(employee: Employee | None) -> bool:
    """False when employment status or hire date must not get a login."""
    if not employee:
        return False
    status = (employee.status or '').strip().lower()
    if status in LOGIN_BLOCKED_EMPLOYEE_STATUSES:
        return False
    if status == EMPLOYEE_STATUS_ACTIVE and not employee_has_started(employee):
        return False
    return True
