"""
Company leave utilization report: balances, usage, remaining, and approval backlog.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.department import Department
from app.models.employee import Employee
from app.models.leave import LeaveRequest, LeaveType
from app.services.leave_approval_service import (
    LEAVE_STATUS_PENDING,
    LEAVE_STATUS_PENDING_HR,
    leave_status_label,
)
from app.services.leave_stats_service import (
    leave_type_display_name,
    leave_types_visible_for_gender,
    normalize_gender,
    statistics_for_employee,
)


def _d(x) -> Decimal:
    return Decimal(str(x or 0)).quantize(Decimal('0.01'))


def _empty_bucket() -> dict:
    return {
        'entitlement': Decimal('0.00'),
        'used': Decimal('0.00'),
        'remaining': Decimal('0.00'),
        'employees_with_balance': 0,
        'employees_with_usage': 0,
    }


def build_leave_utilization_report(
    company_id: int,
    *,
    year: int | None = None,
    department_id: int | None = None,
    leave_type_id: int | None = None,
    branch_id: int | None = None,
) -> dict:
    """
    Aggregate leave utilization for active employees in a company/year.

    Returns summary KPIs, by-leave-type and by-department rollups, per-employee
    balance rows, and an open approval backlog.
    """
    year = year or date.today().year
    generated_at = datetime.utcnow()

    leave_types_q = (
        db.session.query(LeaveType)
        .filter(LeaveType.company_id == company_id, LeaveType.is_active.is_(True))
        .order_by(LeaveType.name)
    )
    if leave_type_id:
        leave_types_q = leave_types_q.filter(LeaveType.id == leave_type_id)
    leave_types = leave_types_q.all()
    leave_type_ids = {lt.id for lt in leave_types}
    leave_type_name = {lt.id: leave_type_display_name(lt) for lt in leave_types}

    emp_q = (
        db.session.query(Employee)
        .filter(Employee.company_id == company_id, Employee.status == 'active')
        .options(joinedload(Employee.department), joinedload(Employee.branch))
    )
    if department_id:
        emp_q = emp_q.filter(Employee.department_id == department_id)
    if branch_id:
        emp_q = emp_q.filter(Employee.branch_id == branch_id)
    employees = emp_q.order_by(Employee.last_name, Employee.first_name).all()

    by_type: dict[int, dict] = defaultdict(_empty_bucket)
    by_dept: dict[str, dict] = defaultdict(_empty_bucket)
    employee_rows: list[dict] = []
    employee_balance_rows: list[dict] = []

    total_entitlement = Decimal('0.00')
    total_used = Decimal('0.00')
    total_remaining = Decimal('0.00')
    employees_with_usage = 0

    for emp in employees:
        dept_name = emp.department.name if emp.department else 'Unassigned'
        gender = normalize_gender(emp.gender)
        visible = leave_types_visible_for_gender(leave_types, gender)
        if leave_type_id:
            visible = [lt for lt in visible if lt.id == leave_type_id]
        if not visible:
            continue

        stats = statistics_for_employee(emp.id, year)
        stat_map = {row['leave_type_id']: row for row in stats}

        emp_used = Decimal('0.00')
        emp_had_row = False
        balances_by_type = {}
        for lt in visible:
            st = stat_map.get(lt.id)
            if not st:
                continue
            used = _d(st.get('used'))
            entitlement = st.get('entitlement')
            remaining = st.get('remaining')
            entitlement_d = _d(entitlement) if entitlement is not None else None
            remaining_d = _d(remaining) if remaining is not None else None

            emp_had_row = True
            emp_used += used
            if used > 0:
                by_type[lt.id]['employees_with_usage'] += 1
                by_dept[dept_name]['employees_with_usage'] += 1

            by_type[lt.id]['used'] += used
            by_dept[dept_name]['used'] += used
            total_used += used

            if entitlement_d is not None:
                by_type[lt.id]['entitlement'] += entitlement_d
                by_dept[dept_name]['entitlement'] += entitlement_d
                total_entitlement += entitlement_d
            if remaining_d is not None:
                by_type[lt.id]['remaining'] += remaining_d
                by_dept[dept_name]['remaining'] += remaining_d
                total_remaining += remaining_d
                by_type[lt.id]['employees_with_balance'] += 1
                by_dept[dept_name]['employees_with_balance'] += 1

            employee_rows.append(
                {
                    'employee_id': emp.id,
                    'employee_number': emp.employee_number or '',
                    'employee_name': emp.full_name,
                    'department': dept_name,
                    'branch': emp.branch.name if emp.branch else '',
                    'leave_type_id': lt.id,
                    'leave_type': leave_type_name.get(lt.id) or lt.name,
                    'leave_code': (lt.code or '').upper(),
                    'entitlement': entitlement_d,
                    'used': used,
                    'remaining': remaining_d,
                }
            )
            balances_by_type[lt.id] = {
                'entitlement': entitlement_d,
                'used': used,
                'remaining': remaining_d,
            }

        if emp_had_row and emp_used > 0:
            employees_with_usage += 1
        if emp_had_row:
            employee_balance_rows.append(
                {
                    'employee_id': emp.id,
                    'employee_number': emp.employee_number or '',
                    'employee_name': emp.full_name,
                    'department': dept_name,
                    'branch': emp.branch.name if emp.branch else '',
                    'balances_by_type': balances_by_type,
                }
            )

    # Approval backlog (open requests; optional filters)
    backlog_requests = []
    if leave_type_id or leave_type_ids:
        backlog_q = (
            db.session.query(LeaveRequest)
            .join(Employee, LeaveRequest.employee_id == Employee.id)
            .options(
                joinedload(LeaveRequest.employee).joinedload(Employee.department),
                joinedload(LeaveRequest.leave_type),
            )
            .filter(
                Employee.company_id == company_id,
                LeaveRequest.status.in_((LEAVE_STATUS_PENDING, LEAVE_STATUS_PENDING_HR)),
            )
        )
        if department_id:
            backlog_q = backlog_q.filter(Employee.department_id == department_id)
        if branch_id:
            backlog_q = backlog_q.filter(Employee.branch_id == branch_id)
        if leave_type_id:
            backlog_q = backlog_q.filter(LeaveRequest.leave_type_id == leave_type_id)
        else:
            backlog_q = backlog_q.filter(LeaveRequest.leave_type_id.in_(leave_type_ids))
        backlog_requests = backlog_q.order_by(LeaveRequest.created_at.asc(), LeaveRequest.id.asc()).all()

    backlog = []
    pending_supervisor = 0
    pending_hr = 0
    pending_days = Decimal('0.00')
    today = date.today()

    for lr in backlog_requests:
        status = (lr.status or '').strip().lower()
        days = _d(lr.days_requested)
        pending_days += days
        if status == LEAVE_STATUS_PENDING:
            pending_supervisor += 1
        elif status == LEAVE_STATUS_PENDING_HR:
            pending_hr += 1
        age_days = (today - lr.created_at.date()).days if lr.created_at else 0
        emp = lr.employee
        backlog.append(
            {
                'id': lr.id,
                'employee_number': (emp.employee_number if emp else '') or '',
                'employee_name': emp.full_name if emp else f'Employee #{lr.employee_id}',
                'department': emp.department.name if emp and emp.department else 'Unassigned',
                'leave_type': leave_type_display_name(lr.leave_type) if lr.leave_type else '—',
                'start_date': lr.start_date,
                'end_date': lr.end_date,
                'days_requested': days,
                'status': status,
                'status_label': leave_status_label(status),
                'submitted_at': lr.created_at,
                'age_days': age_days,
            }
        )

    by_leave_type = []
    for lt in leave_types:
        b = by_type[lt.id]
        by_leave_type.append(
            {
                'leave_type_id': lt.id,
                'code': (lt.code or '').upper(),
                'name': leave_type_name[lt.id],
                'entitlement': b['entitlement'],
                'used': b['used'],
                'remaining': b['remaining'],
                'employees_with_usage': b['employees_with_usage'],
                'employees_with_balance': b['employees_with_balance'],
                'utilization_pct': _utilization_pct(b['used'], b['entitlement']),
            }
        )
    by_leave_type = _swap_sick_and_compassionate(by_leave_type)

    departments = (
        db.session.query(Department)
        .filter(Department.company_id == company_id)
        .order_by(Department.name)
        .all()
    )
    dept_order = [d.name for d in departments]
    if 'Unassigned' in by_dept and 'Unassigned' not in dept_order:
        dept_order.append('Unassigned')
    for name in sorted(by_dept.keys()):
        if name not in dept_order:
            dept_order.append(name)

    by_department = []
    for name in dept_order:
        if name not in by_dept:
            continue
        b = by_dept[name]
        by_department.append(
            {
                'department': name,
                'entitlement': b['entitlement'],
                'used': b['used'],
                'remaining': b['remaining'],
                'employees_with_usage': b['employees_with_usage'],
                'employees_with_balance': b['employees_with_balance'],
                'utilization_pct': _utilization_pct(b['used'], b['entitlement']),
            }
        )

    employee_rows.sort(
        key=lambda r: (r['department'], r['employee_name'].lower(), r['leave_type'])
    )
    employee_balance_rows.sort(
        key=lambda r: (r['department'], r['employee_name'].lower())
    )

    return {
        'generated_at': generated_at,
        'year': year,
        'filters': {
            'department_id': department_id,
            'leave_type_id': leave_type_id,
            'branch_id': branch_id,
        },
        'summary': {
            'active_employees': len(employees),
            'employees_with_usage': employees_with_usage,
            'total_entitlement': total_entitlement,
            'total_used': total_used,
            'total_remaining': total_remaining,
            'utilization_pct': _utilization_pct(total_used, total_entitlement),
            'pending_count': len(backlog),
            'pending_days': pending_days,
            'pending_supervisor': pending_supervisor,
            'pending_hr': pending_hr,
        },
        'by_leave_type': by_leave_type,
        'by_department': by_department,
        'employee_rows': employee_rows,
        'employee_balance_rows': employee_balance_rows,
        'backlog': backlog,
    }


def _utilization_pct(used: Decimal, entitlement: Decimal) -> Decimal | None:
    """Percent of entitlement consumed; None when entitlement is zero/unknown."""
    if entitlement is None or entitlement <= 0:
        return None
    return (used * Decimal('100') / entitlement).quantize(Decimal('0.1'))


def _swap_sick_and_compassionate(leave_type_rows: list[dict]) -> list[dict]:
    """Put Compassionate Leave where Sick Leave would alphabetically fall, and vice versa."""
    rows = list(leave_type_rows)
    sick_index = next((i for i, row in enumerate(rows) if row.get('code') == 'SICK'), None)
    compassionate_index = next(
        (i for i, row in enumerate(rows) if row.get('code') == 'COMPASSIONATE'),
        None,
    )
    if sick_index is not None and compassionate_index is not None:
        rows[sick_index], rows[compassionate_index] = rows[compassionate_index], rows[sick_index]
    return rows
