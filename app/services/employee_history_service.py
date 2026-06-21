"""Assignment history: effective-dated segments synced from Employee."""
from __future__ import annotations

from datetime import date, timedelta

from app.extensions import db
from app.models.employee import Employee
from app.models.employee_assignment_history import EmployeeAssignmentHistory


def _norm_employment_type(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s.lower() or None


def assignment_snapshot(emp: Employee) -> tuple:
    """Values that drive assignment history segments (incl. employment type)."""
    return (
        emp.branch_id,
        emp.department_id,
        emp.job_title_id,
        emp.manager_id,
        (emp.status or '').strip().lower(),
        _norm_employment_type(emp.employment_type),
    )


def _fmt_label(normalized: str | None) -> str:
    if not normalized:
        return '—'
    return str(normalized).replace('_', ' ').title()


def _describe_assignment_change(before: tuple, after: tuple) -> str:
    """Default note when no reason was entered on the edit form."""
    b_br, b_dept, b_jt, b_mgr, b_st, b_et = before
    a_br, a_dept, a_jt, a_mgr, a_st, a_et = after
    parts: list[str] = []
    if b_et != a_et:
        parts.append(f'Employment type: {_fmt_label(b_et)} → {_fmt_label(a_et)}')
    if b_st != a_st:
        parts.append(f'Status: {b_st or "—"} → {a_st or "—"}')
    if (b_br, b_dept, b_jt, b_mgr) != (a_br, a_dept, a_jt, a_mgr):
        if not parts:  # org/role only
            parts.append('Role or organization change')
        else:
            parts.append('role/org updated')
    if parts:
        return ' · '.join(parts)
    return 'Assignment / role update'


def backfill_assignment_history_if_missing(emp: Employee, *, created_by_id: int | None = None) -> bool:
    """Ensure at least one open segment exists (for legacy employees). Returns True if a row was added."""
    n = (
        db.session.query(EmployeeAssignmentHistory)
        .filter(EmployeeAssignmentHistory.employee_id == emp.id)
        .count()
    )
    if n > 0:
        return False
    db.session.add(
        EmployeeAssignmentHistory(
            employee_id=emp.id,
            effective_from=emp.hire_date or date.today(),
            effective_to=None,
            branch_id=emp.branch_id,
            department_id=emp.department_id,
            job_title_id=emp.job_title_id,
            manager_id=emp.manager_id,
            status=emp.status,
            employment_type=emp.employment_type,
            change_reason='Initial record (backfilled from employee profile)',
            created_by_id=created_by_id,
        )
    )
    return True


def record_initial_assignment(emp: Employee, *, created_by_id: int | None = None) -> None:
    """Call after new employee flush — first segment from hire date."""
    db.session.add(
        EmployeeAssignmentHistory(
            employee_id=emp.id,
            effective_from=emp.hire_date or date.today(),
            effective_to=None,
            branch_id=emp.branch_id,
            department_id=emp.department_id,
            job_title_id=emp.job_title_id,
            manager_id=emp.manager_id,
            status=emp.status,
            employment_type=emp.employment_type,
            change_reason='Hire / initial assignment',
            created_by_id=created_by_id,
        )
    )


def sync_assignment_history_after_edit(
    emp: Employee,
    before: tuple,
    *,
    change_reason: str | None = None,
    created_by_id: int | None = None,
) -> None:
    """If org/role fields changed, close open segment and append a new one (or update same-day segment)."""
    after = assignment_snapshot(emp)
    if before == after:
        return

    resolved_reason = (change_reason or '').strip() or _describe_assignment_change(before, after)

    today = date.today()

    open_row = (
        db.session.query(EmployeeAssignmentHistory)
        .filter(
            EmployeeAssignmentHistory.employee_id == emp.id,
            EmployeeAssignmentHistory.effective_to.is_(None),
        )
        .order_by(EmployeeAssignmentHistory.effective_from.desc())
        .first()
    )

    if open_row and open_row.effective_from == today:
        open_row.branch_id = emp.branch_id
        open_row.department_id = emp.department_id
        open_row.job_title_id = emp.job_title_id
        open_row.manager_id = emp.manager_id
        open_row.status = emp.status
        open_row.employment_type = emp.employment_type
        open_row.change_reason = resolved_reason
        return

    if open_row:
        end_d = today - timedelta(days=1)
        open_row.effective_to = end_d
        if open_row.effective_to < open_row.effective_from:
            open_row.effective_to = open_row.effective_from

    db.session.add(
        EmployeeAssignmentHistory(
            employee_id=emp.id,
            effective_from=today,
            effective_to=None,
            branch_id=emp.branch_id,
            department_id=emp.department_id,
            job_title_id=emp.job_title_id,
            manager_id=emp.manager_id,
            status=emp.status,
            employment_type=emp.employment_type,
            change_reason=resolved_reason,
            created_by_id=created_by_id,
        )
    )
