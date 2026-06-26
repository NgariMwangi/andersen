"""Two-step leave approval: supervisor (manager) then HR."""
from __future__ import annotations

from app.models.employee import Employee
from app.models.leave import LeaveRequest
from app.services.employee_relations_service import (
    employee_has_any_supervisor,
    employee_has_supervisor,
    employee_supervisor_names,
)

LEAVE_STATUS_PENDING = 'pending'
LEAVE_STATUS_PENDING_HR = 'pending_hr'
LEAVE_STATUS_APPROVED = 'approved'
LEAVE_STATUS_REJECTED = 'rejected'
LEAVE_STATUS_CANCELLED = 'cancelled'

EDITABLE_STATUSES = frozenset({LEAVE_STATUS_PENDING, LEAVE_STATUS_PENDING_HR})
RESUBMITTABLE_STATUSES = frozenset({LEAVE_STATUS_REJECTED})


def leave_request_is_editable(leave_request: LeaveRequest) -> bool:
    """True while the request is not yet fully approved (employee may edit or delete)."""
    status = (leave_request.status or '').strip().lower()
    return status in EDITABLE_STATUSES or status in RESUBMITTABLE_STATUSES


def leave_request_is_resubmittable(leave_request: LeaveRequest) -> bool:
    return (leave_request.status or '').strip().lower() in RESUBMITTABLE_STATUSES


def reset_leave_request_for_resubmission(leave_request: LeaveRequest, employee: Employee) -> None:
    """Clear prior rejection and re-enter the approval workflow."""
    leave_request.status = initial_leave_status_for_employee(employee)
    leave_request.supervisor_reviewed_by_id = None
    leave_request.supervisor_reviewed_at = None
    leave_request.supervisor_notes = None
    leave_request.reviewed_by_id = None
    leave_request.reviewed_at = None
    leave_request.review_notes = None


def reset_leave_request_after_employee_edit(leave_request: LeaveRequest, employee: Employee) -> None:
    """
    After an employee changes a request that had advanced in approval, rewind as needed.

    Pending (supervisor not yet acted): no change.
    Pending HR after supervisor approval: clear supervisor step and return to pending.
    Pending HR with no supervisor on file: remain with HR.
    """
    status = (leave_request.status or '').strip().lower()
    if status != LEAVE_STATUS_PENDING_HR or not leave_request.supervisor_reviewed_at:
        return
    leave_request.supervisor_reviewed_by_id = None
    leave_request.supervisor_reviewed_at = None
    leave_request.supervisor_notes = None
    leave_request.status = LEAVE_STATUS_PENDING


def initial_leave_status_for_employee(employee: Employee | None) -> str:
    """If no supervisor is assigned, skip supervisor step and go straight to HR."""
    if employee_has_any_supervisor(employee):
        return LEAVE_STATUS_PENDING
    return LEAVE_STATUS_PENDING_HR


def is_supervisor_for_request(user, leave_request: LeaveRequest) -> bool:
    """True when the logged-in user is one of the requester's supervisors."""
    if not getattr(user, 'employee_id', None):
        return False
    emp = leave_request.employee
    if not emp:
        return False
    return employee_has_supervisor(emp, user.employee_id)


def user_is_line_manager(user, company_id: int) -> bool:
    """True when at least one active employee lists this user as a supervisor."""
    if not getattr(user, 'employee_id', None):
        return False
    from app.extensions import db
    from app.models.employee_relations import EmployeeSupervisor

    via_links = (
        db.session.query(EmployeeSupervisor.employee_id)
        .join(Employee, EmployeeSupervisor.employee_id == Employee.id)
        .filter(
            Employee.company_id == company_id,
            EmployeeSupervisor.supervisor_id == user.employee_id,
            Employee.status == 'active',
        )
        .limit(1)
        .first()
    )
    if via_links:
        return True
    return (
        db.session.query(Employee.id)
        .filter(
            Employee.company_id == company_id,
            Employee.manager_id == user.employee_id,
            Employee.status == 'active',
        )
        .limit(1)
        .first()
        is not None
    )


def approval_stage_for_user(user, leave_request: LeaveRequest) -> str | None:
    """
    Return 'supervisor' or 'hr' if this user may act on the request now, else None.

    Supervisor step: any employee who is the requester's manager (any role, e.g. EMPLOYEE).
    HR step: users with approve_leave permission.
    """
    status = (leave_request.status or '').strip().lower()
    if getattr(user, 'is_superuser', False):
        if status in (LEAVE_STATUS_PENDING, LEAVE_STATUS_PENDING_HR):
            return 'hr'

    if status == LEAVE_STATUS_PENDING_HR and user.has_permission('approve_leave'):
        return 'hr'

    # HR may approve/reject even before the supervisor responds (supervisor unavailable).
    if status == LEAVE_STATUS_PENDING and user.has_permission('approve_leave'):
        return 'hr'

    if status == LEAVE_STATUS_PENDING and is_supervisor_for_request(user, leave_request):
        return 'supervisor'

    return None


def leave_status_label(status: str) -> str:
    labels = {
        LEAVE_STATUS_PENDING: 'Pending supervisor',
        LEAVE_STATUS_PENDING_HR: 'Pending HR',
        LEAVE_STATUS_APPROVED: 'Approved',
        LEAVE_STATUS_REJECTED: 'Rejected',
        LEAVE_STATUS_CANCELLED: 'Cancelled',
    }
    return labels.get((status or '').strip().lower(), status or '—')


def count_pending_leave_for_user(user, company_id: int) -> int:
    """Badge count: supervisor queue + HR queue for the current user."""
    from app.extensions import db
    from app.models.employee import Employee
    from app.models.leave import LeaveRequest

    total = 0
    base = (
        db.session.query(LeaveRequest)
        .join(Employee, LeaveRequest.employee_id == Employee.id)
        .filter(Employee.company_id == company_id)
    )
    if getattr(user, 'employee_id', None):
        from app.models.employee_relations import EmployeeSupervisor

        subordinate_ids = {
            row[0]
            for row in db.session.query(EmployeeSupervisor.employee_id)
            .join(Employee, EmployeeSupervisor.employee_id == Employee.id)
            .filter(
                Employee.company_id == company_id,
                EmployeeSupervisor.supervisor_id == user.employee_id,
                Employee.status == 'active',
            )
            .all()
        }
        subordinate_ids.update(
            row[0]
            for row in db.session.query(Employee.id)
            .filter(
                Employee.company_id == company_id,
                Employee.manager_id == user.employee_id,
                Employee.status == 'active',
            )
            .all()
        )
        if subordinate_ids:
            total += base.filter(
                LeaveRequest.status == LEAVE_STATUS_PENDING,
                LeaveRequest.employee_id.in_(subordinate_ids),
            ).count()
    if user.has_permission('approve_leave'):
        total += base.filter(
            LeaveRequest.status.in_((LEAVE_STATUS_PENDING, LEAVE_STATUS_PENDING_HR))
        ).count()
    return total


def supervisor_step_summary(leave_request: LeaveRequest) -> dict:
    """
    Display status of the supervisor (manager) step for HR and audit.
    Returns keys: state, label, manager_name, reviewed_at, notes, reviewer_label.
    """
    emp = leave_request.employee
    manager_name = employee_supervisor_names(emp) or None

    if not emp or not employee_has_any_supervisor(emp):
        return {
            'state': 'not_applicable',
            'label': 'No supervisor on file',
            'manager_name': None,
            'reviewed_at': None,
            'notes': None,
            'reviewer_label': None,
        }

    if leave_request.supervisor_reviewed_at:
        reviewer = getattr(leave_request, 'supervisor_reviewed_by', None)
        reviewer_label = None
        if reviewer and getattr(reviewer, 'email', None):
            reviewer_label = reviewer.email
        return {
            'state': 'completed',
            'label': 'Supervisor responded',
            'manager_name': manager_name,
            'reviewed_at': leave_request.supervisor_reviewed_at,
            'notes': leave_request.supervisor_notes,
            'reviewer_label': reviewer_label,
        }

    status = (leave_request.status or '').strip().lower()
    if (
        status == LEAVE_STATUS_REJECTED
        and leave_request.supervisor_reviewed_at
        and not leave_request.reviewed_at
    ):
        return {
            'state': 'rejected',
            'label': 'Rejected by supervisor',
            'manager_name': manager_name,
            'reviewed_at': leave_request.supervisor_reviewed_at,
            'notes': leave_request.supervisor_notes,
            'reviewer_label': None,
        }

    return {
        'state': 'awaiting',
        'label': 'Awaiting supervisor',
        'manager_name': manager_name,
        'reviewed_at': None,
        'notes': None,
        'reviewer_label': None,
    }


def count_all_open_leave_approvals(company_id: int) -> int:
    """Executive reports: any request not yet fully approved."""
    from app.extensions import db
    from app.models.employee import Employee
    from app.models.leave import LeaveRequest

    return (
        db.session.query(LeaveRequest)
        .join(Employee, LeaveRequest.employee_id == Employee.id)
        .filter(
            Employee.company_id == company_id,
            LeaveRequest.status.in_((LEAVE_STATUS_PENDING, LEAVE_STATUS_PENDING_HR)),
        )
        .count()
    )
