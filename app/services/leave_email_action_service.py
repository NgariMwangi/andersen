"""Signed email links for supervisor leave approve/decline."""
from __future__ import annotations

from datetime import datetime

from flask import current_app, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.extensions import db
from app.models.employee import Employee
from app.models.leave import LeaveRequest
from app.models.user import User
from app.services.employee_relations_service import employee_has_supervisor
from app.services.leave_approval_service import (
    LEAVE_STATUS_PENDING,
    LEAVE_STATUS_PENDING_HR,
    LEAVE_STATUS_REJECTED,
)
from app.services.password_reset_service import external_base_url

LEAVE_EMAIL_ACTION_SALT = 'leave-supervisor-email-action-v1'
VALID_ACTIONS = frozenset({'approve', 'reject'})


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        current_app.config['SECRET_KEY'],
        salt=LEAVE_EMAIL_ACTION_SALT,
    )


def leave_email_action_max_age() -> int:
    return int(current_app.config.get('LEAVE_EMAIL_ACTION_EXPIRY_SECONDS', 7 * 24 * 3600))


def generate_leave_email_action_token(
    *,
    leave_request_id: int,
    action: str,
    supervisor_employee_id: int,
) -> str:
    action = (action or '').strip().lower()
    if action not in VALID_ACTIONS:
        raise ValueError(f'Invalid leave email action: {action}')
    return _serializer().dumps(
        {
            'lid': int(leave_request_id),
            'action': action,
            'sid': int(supervisor_employee_id),
        }
    )


def verify_leave_email_action_token(token: str) -> dict | None:
    """Return {leave_request_id, action, supervisor_employee_id} or None."""
    try:
        data = _serializer().loads(token, max_age=leave_email_action_max_age())
        lid = int(data['lid'])
        sid = int(data['sid'])
        action = str(data.get('action') or '').strip().lower()
        if action not in VALID_ACTIONS:
            return None
        return {
            'leave_request_id': lid,
            'action': action,
            'supervisor_employee_id': sid,
        }
    except (BadSignature, SignatureExpired, TypeError, ValueError, KeyError):
        return None


def build_leave_email_action_url(
    *,
    leave_request_id: int,
    action: str,
    supervisor_employee_id: int,
) -> str:
    token = generate_leave_email_action_token(
        leave_request_id=leave_request_id,
        action=action,
        supervisor_employee_id=supervisor_employee_id,
    )
    return external_base_url() + url_for('leave.email_action', token=token)


def load_leave_for_email_action(leave_request_id: int) -> LeaveRequest | None:
    return (
        db.session.query(LeaveRequest)
        .filter(LeaveRequest.id == leave_request_id)
        .first()
    )


def supervisor_user_for_employee(supervisor_employee_id: int) -> User | None:
    return (
        db.session.query(User)
        .filter(User.employee_id == supervisor_employee_id, User.is_active.is_(True))
        .first()
    )


def validate_supervisor_email_action(
    *,
    leave_request: LeaveRequest,
    action: str,
    supervisor_employee_id: int,
) -> tuple[bool, str]:
    """Return (ok, error_message)."""
    action = (action or '').strip().lower()
    if action not in VALID_ACTIONS:
        return False, 'Invalid action.'

    status = (leave_request.status or '').strip().lower()
    if status != LEAVE_STATUS_PENDING:
        if status == LEAVE_STATUS_PENDING_HR:
            return False, 'This leave request was already approved by a supervisor and is waiting for HR.'
        if status == LEAVE_STATUS_REJECTED:
            return False, 'This leave request has already been declined.'
        return False, 'This leave request is no longer awaiting supervisor action.'

    emp = leave_request.employee or db.session.get(Employee, leave_request.employee_id)
    if not emp:
        return False, 'Employee record for this leave request was not found.'

    if not employee_has_supervisor(emp, supervisor_employee_id):
        return False, 'You are not assigned as supervisor for this employee.'

    if not supervisor_user_for_employee(supervisor_employee_id):
        return False, 'No active login account is linked to your employee profile. Contact HR.'

    return True, ''


def apply_supervisor_email_action(
    *,
    leave_request: LeaveRequest,
    action: str,
    supervisor_employee_id: int,
) -> User:
    """
    Apply supervisor approve/reject from an email action.
    Caller must validate first. Returns the acting User.
    """
    ok, err = validate_supervisor_email_action(
        leave_request=leave_request,
        action=action,
        supervisor_employee_id=supervisor_employee_id,
    )
    if not ok:
        raise ValueError(err)

    user = supervisor_user_for_employee(supervisor_employee_id)
    if not user:
        raise ValueError('No active login account is linked to your employee profile. Contact HR.')

    now = datetime.utcnow()
    action = action.strip().lower()
    leave_request.supervisor_reviewed_by_id = user.id
    leave_request.supervisor_reviewed_at = now
    if action == 'reject':
        leave_request.status = LEAVE_STATUS_REJECTED
        if not (leave_request.supervisor_notes or '').strip():
            leave_request.supervisor_notes = 'Declined via email'
    else:
        leave_request.status = LEAVE_STATUS_PENDING_HR
        if not (leave_request.supervisor_notes or '').strip():
            leave_request.supervisor_notes = 'Approved via email'
    return user
