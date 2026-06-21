"""Email notifications for leave requests (submitted and approved/rejected)."""
from __future__ import annotations

import logging
from decimal import Decimal
from html import escape

from flask import current_app, url_for
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.employee import Employee
from app.models.leave import LeaveRequest
from app.models.user import Permission, Role, RolePermission, User, UserRole
from app.services.brevo_service import normalize_hr_sender_email, send_transactional_email
from app.services.leave_approval_service import (
    LEAVE_STATUS_APPROVED,
    LEAVE_STATUS_PENDING,
    LEAVE_STATUS_PENDING_HR,
    LEAVE_STATUS_REJECTED,
    leave_status_label,
)
from app.services.password_reset_service import external_base_url

logger = logging.getLogger(__name__)


def _app_name() -> str:
    return (current_app.config.get('APP_NAME') or 'HRMS').strip() or 'HRMS'


def _leave_url(leave_request_id: int) -> str:
    return external_base_url() + url_for('leave.approve', id=leave_request_id)


def _employee_inbox(employee: Employee | None) -> str | None:
    if not employee:
        return None
    user = getattr(employee, 'user', None)
    if user and (user.email or '').strip():
        return user.email.strip().lower()
    for addr in (employee.email, employee.secondary_email):
        if addr and str(addr).strip():
            return str(addr).strip().lower()
    return None


def _supervisor_inboxes(employee: Employee | None) -> list[str]:
    """Email addresses for all assigned supervisors."""
    from app.services.employee_relations_service import employee_supervisors

    addresses: list[str] = []
    seen: set[str] = set()
    for supervisor in employee_supervisors(employee):
        inbox = _employee_inbox(supervisor)
        if inbox and inbox not in seen:
            seen.add(inbox)
            addresses.append(inbox)
    return addresses


def _hr_notify_addresses(company_id: int) -> list[str]:
    configured = (current_app.config.get('LEAVE_HR_NOTIFY_EMAIL') or '').strip()
    if not configured:
        configured = (current_app.config.get('BREVO_SENDER_EMAIL') or '').strip()
    addresses = {normalize_hr_sender_email(a) for a in configured.split(',') if a.strip()}

    perm = db.session.query(Permission).filter(Permission.code == 'approve_leave').first()
    if perm:
        rows = (
            db.session.query(User.email)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .filter(
                User.is_active.is_(True),
                User.company_id == company_id,
                RolePermission.permission_id == perm.id,
            )
            .distinct()
            .all()
        )
        for (email,) in rows:
            if email and str(email).strip():
                addresses.add(normalize_hr_sender_email(str(email).strip()))

    return sorted(addresses)


def _load_leave_request(leave_request_id: int) -> LeaveRequest | None:
    return (
        db.session.query(LeaveRequest)
        .options(
            joinedload(LeaveRequest.employee).joinedload(Employee.manager).joinedload(Employee.user),
            joinedload(LeaveRequest.employee).joinedload(Employee.user),
            joinedload(LeaveRequest.leave_type),
        )
        .filter(LeaveRequest.id == leave_request_id)
        .first()
    )


def _format_leave_days(days) -> str:
    """Show whole days without decimal places (e.g. 5.00 → 5)."""
    d = Decimal(str(days or 0))
    if d == d.to_integral_value():
        return str(int(d))
    return str(d.normalize()).rstrip('0').rstrip('.')


def _leave_summary_html(lr: LeaveRequest) -> str:
    emp = lr.employee
    lt = lr.leave_type
    emp_name = escape(emp.full_name if emp else f'Employee #{lr.employee_id}')
    lt_name = escape(lt.name if lt else 'Leave')
    reason = escape((lr.reason or '').strip()) if (lr.reason or '').strip() else '—'
    return f"""
    <table style="border-collapse:collapse;margin:12px 0;font-size:14px;">
      <tr><td style="padding:4px 12px 4px 0;color:#64748b;">Employee</td><td><strong>{emp_name}</strong></td></tr>
      <tr><td style="padding:4px 12px 4px 0;color:#64748b;">Leave type</td><td>{lt_name}</td></tr>
      <tr><td style="padding:4px 12px 4px 0;color:#64748b;">Dates</td><td>{lr.start_date:%d %b %Y} – {lr.end_date:%d %b %Y}</td></tr>
      <tr><td style="padding:4px 12px 4px 0;color:#64748b;">Days</td><td>{_format_leave_days(lr.days_requested)}</td></tr>
      <tr><td style="padding:4px 12px 4px 0;color:#64748b;">Reason</td><td>{reason}</td></tr>
      <tr><td style="padding:4px 12px 4px 0;color:#64748b;">Status</td><td>{escape(leave_status_label(lr.status))}</td></tr>
    </table>
    """


def _send_leave_email(to_addresses: list[str], subject: str, html_body: str, text_body: str) -> None:
    seen: set[str] = set()
    for addr in to_addresses:
        email = (addr or '').strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        ok = send_transactional_email(email, subject, html_body, text_content=text_body)
        if not ok:
            logger.warning('Leave notification not sent to %s (%s)', email, subject)


def notify_leave_submitted(leave_request_id: int) -> None:
    """Notify HR and the employee's supervisor when a leave request is submitted."""
    lr = _load_leave_request(leave_request_id)
    if not lr:
        return
    emp = lr.employee or db.session.get(Employee, lr.employee_id)
    if not emp:
        return

    app_name = _app_name()
    approve_link = _leave_url(lr.id)
    summary = _leave_summary_html(lr)
    subject = f'{app_name} — New leave request from {emp.full_name}'
    html = f"""
    <p>Hello,</p>
    <p>A new leave request has been submitted and requires your attention.</p>
    {summary}
    <p><a href="{approve_link}" style="display:inline-block;padding:10px 18px;background:#ab0e1e;color:#fff;text-decoration:none;border-radius:6px;">Review leave request</a></p>
    <p style="color:#64748b;font-size:12px;">{escape(app_name)}</p>
    """
    text = (
        f'New leave request from {emp.full_name}\n'
        f'{lr.start_date} to {lr.end_date} ({_format_leave_days(lr.days_requested)} days)\n'
        f'Review: {approve_link}\n'
    )

    hr_addresses = _hr_notify_addresses(emp.company_id)
    _send_leave_email(hr_addresses, subject, html, text)

    if lr.status == LEAVE_STATUS_PENDING:
        sup_subject = f'{app_name} — Leave request from {emp.full_name} (supervisor action)'
        sup_html = f"""
        <p>Hello,</p>
        <p><strong>{escape(emp.full_name)}</strong> has submitted a leave request that needs your approval as their supervisor.</p>
        {summary}
        <p><a href="{approve_link}" style="display:inline-block;padding:10px 18px;background:#ab0e1e;color:#fff;text-decoration:none;border-radius:6px;">Review leave request</a></p>
        <p style="color:#64748b;font-size:12px;">{escape(app_name)}</p>
        """
        sup_text = (
            f'Leave request from {emp.full_name} needs your approval.\n'
            f'{lr.start_date} to {lr.end_date}\n'
            f'Review: {approve_link}\n'
        )
        _send_leave_email(_supervisor_inboxes(emp), sup_subject, sup_html, sup_text)

    employee_email = _employee_inbox(emp)
    if employee_email:
        if lr.status == LEAVE_STATUS_PENDING:
            wait_msg = (
                'Your leave request has been received. Please wait for your '
                '<strong>supervisor</strong> and then <strong>HR</strong> to review and approve it.'
            )
            wait_text = (
                'Your leave request has been received. Please wait for your '
                'supervisor and then HR to review and approve it.'
            )
        else:
            wait_msg = (
                'Your leave request has been received. Please wait for '
                '<strong>HR</strong> to review and approve it.'
            )
            wait_text = (
                'Your leave request has been received. Please wait for HR to review and approve it.'
            )
        emp_subject = f'{app_name} — Leave request submitted'
        emp_html = f"""
        <p>Hello {escape(emp.first_name)},</p>
        <p>{wait_msg}</p>
        {summary}
        <p>You will receive another email when your supervisor or HR responds.</p>
        <p style="color:#64748b;font-size:12px;">{escape(app_name)}</p>
        """
        emp_text = (
            f'Hello {emp.first_name},\n\n'
            f'{wait_text}\n\n'
            f'{lr.start_date} to {lr.end_date} ({_format_leave_days(lr.days_requested)} days)\n'
            f'Status: {leave_status_label(lr.status)}\n\n'
            'You will receive another email when your supervisor or HR responds.\n'
        )
        _send_leave_email([employee_email], emp_subject, emp_html, emp_text)
    else:
        logger.warning('Leave submission confirmation skipped: no email for employee %s', emp.id)


def notify_leave_responded(
    leave_request_id: int,
    *,
    actor_stage: str,
    action: str,
) -> None:
    """Notify the employee after a supervisor or HR action."""
    lr = _load_leave_request(leave_request_id)
    if not lr:
        return
    emp = lr.employee or db.session.get(Employee, lr.employee_id)
    if not emp:
        return
    employee_email = _employee_inbox(emp)
    if not employee_email:
        logger.warning('Leave response notification skipped: no email for employee %s', emp.id)
        return

    app_name = _app_name()
    actor_label = 'Supervisor' if actor_stage == 'supervisor' else 'HR'
    notes = ''
    if actor_stage == 'supervisor' and (lr.supervisor_notes or '').strip():
        notes = escape(lr.supervisor_notes.strip())
    elif actor_stage == 'hr' and (lr.review_notes or '').strip():
        notes = escape(lr.review_notes.strip())

    if action == 'reject':
        outcome = 'rejected'
        detail = f'Your leave request was <strong>rejected</strong> by {actor_label}.'
    elif lr.status == LEAVE_STATUS_PENDING_HR:
        outcome = 'supervisor approved'
        detail = (
            f'Your leave request was <strong>approved by your supervisor</strong> '
            f'and is now pending final HR approval.'
        )
    elif lr.status == LEAVE_STATUS_APPROVED:
        outcome = 'approved'
        detail = f'Your leave request was <strong>approved</strong> by {actor_label}.'
    else:
        outcome = leave_status_label(lr.status)
        detail = f'Your leave request was updated by {actor_label}.'

    summary = _leave_summary_html(lr)
    subject = f'{app_name} — Leave request {outcome}'
    html = f"""
    <p>Hello {escape(emp.first_name)},</p>
    <p>{detail}</p>
    {summary}
    """
    if notes:
        html += f'<p><strong>Notes from {actor_label}:</strong> {notes}</p>'
    html += f'<p style="color:#64748b;font-size:12px;">{escape(app_name)}</p>'

    text = (
        f'Hello {emp.first_name},\n\n'
        f'{detail.replace("<strong>", "").replace("</strong>", "")}\n'
        f'{lr.start_date} to {lr.end_date} — {leave_status_label(lr.status)}\n'
    )
    if notes:
        text += f'Notes: {notes}\n'

    _send_leave_email([employee_email], subject, html, text)
