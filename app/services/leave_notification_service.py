"""Email notifications for leave requests (submitted and approved/rejected)."""
from __future__ import annotations

import logging
from decimal import Decimal
from html import escape

from flask import current_app, url_for
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.company import Company
from app.models.employee import Employee
from app.models.leave import LeaveRequest
from app.models.user import Role, User, UserRole
from app.services.brevo_service import brevo_configured, send_transactional_email
from app.services.leave_approval_service import (
    LEAVE_STATUS_APPROVED,
    LEAVE_STATUS_PENDING,
    LEAVE_STATUS_PENDING_HR,
    LEAVE_STATUS_REJECTED,
    leave_status_label,
)
from app.services.password_reset_service import external_base_url

logger = logging.getLogger(__name__)

BRAND_PRIMARY = '#ab0e1e'
BRAND_PRIMARY_DARK = '#8d0c18'
BRAND_SLATE = '#243444'
DEFAULT_PORTAL_URL = 'https://hrms.nexusafrica.co.ke'
HR_LEAVE_NOTIFY_ROLE_CODES = ('HR_MANAGER', 'HR_STAFF')


def _app_name() -> str:
    return (current_app.config.get('APP_NAME') or 'Andersen').strip() or 'Andersen'


def _portal_base() -> str:
    base = (external_base_url() or '').strip().rstrip('/')
    if not base:
        base = (current_app.config.get('APP_BASE_URL') or DEFAULT_PORTAL_URL).strip().rstrip('/')
    return base


def _portal_host() -> str:
    return _portal_base().replace('https://', '').replace('http://', '').split('/')[0]


def _company_display_name(employee: Employee | None) -> str:
    if not employee or not employee.company_id:
        return _app_name()
    company = db.session.get(Company, employee.company_id)
    if company and company.employer_profile and (company.employer_profile.name or '').strip():
        return company.employer_profile.name.strip()
    if company and (company.name or '').strip():
        return company.name.strip()
    return _app_name()


def _leave_url(leave_request_id: int) -> str:
    return _portal_base() + url_for('leave.approve', id=leave_request_id)


def _leave_index_url() -> str:
    return _portal_base() + url_for('leave.index')


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
    """Active login users with HR Manager or HR Staff role for this company."""
    rows = (
        db.session.query(User.email)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .filter(
            User.is_active.is_(True),
            User.company_id == company_id,
            Role.code.in_(HR_LEAVE_NOTIFY_ROLE_CODES),
        )
        .distinct()
        .all()
    )
    addresses: set[str] = set()
    for (email,) in rows:
        if email and str(email).strip():
            addresses.add(str(email).strip().lower())

    configured = (current_app.config.get('LEAVE_HR_NOTIFY_EMAIL') or '').strip()
    for addr in configured.split(','):
        cleaned = addr.strip().lower()
        if cleaned:
            addresses.add(cleaned)

    if not addresses:
        logger.warning(
            'No HR leave notification recipients for company_id=%s '
            '(assign HR Manager or HR Staff roles, or set LEAVE_HR_NOTIFY_EMAIL)',
            company_id,
        )

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


def _dates_phrase(lr: LeaveRequest) -> str:
    days = _format_leave_days(lr.days_requested)
    return f'{lr.start_date:%d %b %Y} to {lr.end_date:%d %b %Y} ({days} day{"s" if days != "1" else ""})'


def _leave_type_code(lr: LeaveRequest) -> str:
    lt = lr.leave_type
    return (lt.code or '').strip().upper() if lt else ''


def _hr_approval_closing(lr: LeaveRequest) -> tuple[str, str]:
    """Friendly closing line after HR final approval."""
    code = _leave_type_code(lr)
    if code == 'SICK':
        return (
            'Your leave has been approved by HR. We hope you feel better soon.',
            'Your leave has been approved by HR. We hope you feel better soon.',
        )
    if code == 'ANNUAL':
        return (
            'Your leave has been approved by HR. Have a nice leave!',
            'Your leave has been approved by HR. Have a nice leave!',
        )
    return (
        'Your leave has been approved by HR.',
        'Your leave has been approved by HR.',
    )


def _status_badge_html(status: str) -> str:
    st = (status or '').strip().lower()
    if st == LEAVE_STATUS_APPROVED:
        bg, fg = '#dcfce7', '#166534'
    elif st == LEAVE_STATUS_REJECTED:
        bg, fg = '#fee2e2', '#991b1b'
    elif st in (LEAVE_STATUS_PENDING, LEAVE_STATUS_PENDING_HR):
        bg, fg = '#fef3c7', '#92400e'
    else:
        bg, fg = '#f1f5f9', '#475569'
    label = escape(leave_status_label(status))
    return (
        f'<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
        f'font-size:12px;font-weight:700;background:{bg};color:{fg};">{label}</span>'
    )


def _summary_row(label: str, value: str, *, strong: bool = False) -> str:
    val = f'<strong>{value}</strong>' if strong else value
    return (
        f'<tr>'
        f'<td width="130" valign="top" style="padding:8px 0;font-size:13px;color:#64748b;'
        f'font-family:Helvetica,Arial,sans-serif;">{escape(label)}</td>'
        f'<td valign="top" style="padding:8px 0;font-size:14px;color:{BRAND_SLATE};'
        f'font-family:Helvetica,Arial,sans-serif;">{val}</td>'
        f'</tr>'
    )


def _leave_summary_html(lr: LeaveRequest, *, include_employee: bool = True) -> str:
    emp = lr.employee
    lt = lr.leave_type
    emp_name = escape(emp.full_name if emp else f'Employee #{lr.employee_id}')
    lt_name = escape(lt.name if lt else 'Leave')
    reason = escape((lr.reason or '').strip()) if (lr.reason or '').strip() else '—'
    rows = []
    if include_employee:
        rows.append(_summary_row('Employee', emp_name, strong=True))
    rows.extend(
        [
            _summary_row('Leave type', lt_name),
            _summary_row('Dates', f'{lr.start_date:%d %b %Y} – {lr.end_date:%d %b %Y}'),
            _summary_row('Days', _format_leave_days(lr.days_requested)),
            _summary_row('Reason', reason),
            f'<tr><td width="130" valign="top" style="padding:8px 0;font-size:13px;color:#64748b;'
            f'font-family:Helvetica,Arial,sans-serif;">Status</td>'
            f'<td valign="top" style="padding:8px 0;">{_status_badge_html(lr.status)}</td></tr>',
        ]
    )
    return (
        f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
        f'style="margin:20px 0;background-color:#f8fafc;border:1px solid #e2e8f0;border-left:4px solid {BRAND_PRIMARY};">'
        f'<tr><td style="padding:18px 20px;">'
        f'<p style="margin:0 0 12px;font-size:12px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.06em;color:{BRAND_SLATE};font-family:Helvetica,Arial,sans-serif;">Leave details</p>'
        f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">'
        + ''.join(rows)
        + '</table></td></tr></table>'
    )


def _highlight_box(message_html: str, *, tone: str = 'info') -> str:
    tones = {
        'info': ('#eff6ff', '#1d4ed8', '#bfdbfe'),
        'success': ('#f0fdf4', '#166534', '#bbf7d0'),
        'warning': ('#fffbeb', '#92400e', '#fde68a'),
        'danger': ('#fef2f2', '#991b1b', '#fecaca'),
    }
    bg, fg, border = tones.get(tone, tones['info'])
    return (
        f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
        f'style="margin:0 0 20px;background-color:{bg};border:1px solid {border};border-radius:6px;">'
        f'<tr><td style="padding:16px 18px;font-size:15px;line-height:1.6;color:{fg};'
        f'font-family:Helvetica,Arial,sans-serif;">{message_html}</td></tr></table>'
    )


def _email_button(label: str, href: str) -> str:
    href_safe = escape(href)
    label_safe = escape(label)
    return (
        f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center" '
        f'style="margin:8px auto 4px;">'
        f'<tr><td align="center" bgcolor="{BRAND_PRIMARY}" style="background-color:{BRAND_PRIMARY};border-radius:6px;">'
        f'<a href="{href_safe}" target="_blank" style="display:inline-block;padding:14px 32px;'
        f'font-family:Helvetica,Arial,sans-serif;font-size:15px;font-weight:700;color:#ffffff;'
        f'text-decoration:none;border-radius:6px;">{label_safe}</a>'
        f'</td></tr></table>'
    )


def _wrap_email(
    *,
    title: str,
    subtitle: str,
    body_html: str,
    preheader: str = '',
    employee: Employee | None = None,
) -> str:
    app_name = escape(_app_name())
    company_name = escape(_company_display_name(employee))
    title_safe = escape(title)
    subtitle_safe = escape(subtitle)
    preheader_html = ''
    if preheader:
        preheader_html = (
            f'<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">'
            f'{escape(preheader)}&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;</div>'
        )
    return f"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" lang="en">
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title_safe} — {app_name}</title>
</head>
<body style="margin:0;padding:0;background-color:#eef2f7;width:100%;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">
{preheader_html}
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color:#eef2f7;">
  <tr>
    <td align="center" style="padding:32px 16px;">
      <table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0" style="width:100%;max-width:600px;background-color:#ffffff;border:1px solid #e2e8f0;">

        <tr>
          <td align="center" bgcolor="{BRAND_PRIMARY}" style="background-color:{BRAND_PRIMARY};padding:28px 28px 24px;">
            <p style="margin:0 0 6px;font-size:11px;letter-spacing:0.14em;text-transform:uppercase;color:#ffffff;font-family:Helvetica,Arial,sans-serif;opacity:0.92;">Human Resource Management</p>
            <p style="margin:0 0 10px;font-size:26px;font-weight:700;color:#ffffff;letter-spacing:0.04em;font-family:Helvetica,Arial,sans-serif;">{app_name}</p>
            <p style="margin:0;font-size:16px;color:#ffffff;font-family:Helvetica,Arial,sans-serif;">{title_safe}</p>
            <p style="margin:8px 0 0;font-size:13px;color:#fecaca;font-family:Helvetica,Arial,sans-serif;">{subtitle_safe}</p>
          </td>
        </tr>

        <tr>
          <td style="padding:32px 28px 12px;font-family:Helvetica,Arial,sans-serif;font-size:15px;line-height:1.65;color:#475569;">
            {body_html}
          </td>
        </tr>

        <tr>
          <td align="center" bgcolor="#f8fafc" style="background-color:#f8fafc;padding:22px 28px;border-top:1px solid #e2e8f0;">
            <p style="margin:0 0 4px;font-size:13px;font-weight:600;color:{BRAND_SLATE};font-family:Helvetica,Arial,sans-serif;">{company_name}</p>
            <p style="margin:0;font-size:12px;line-height:1.5;color:#94a3b8;font-family:Helvetica,Arial,sans-serif;">
              {app_name} HRMS &middot; {_portal_host()} &middot; Automated message — please do not reply
            </p>
          </td>
        </tr>

      </table>
    </td>
  </tr>
</table>
</body>
</html>"""


def _send_leave_email(to_addresses: list[str], subject: str, html_body: str, text_body: str) -> None:
    if not brevo_configured():
        logger.warning('Leave notification skipped — Brevo not configured (%s)', subject)
        return
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
    """Confirm to employee; alert supervisor and HR that a request is waiting."""
    lr = _load_leave_request(leave_request_id)
    if not lr:
        return
    emp = lr.employee or db.session.get(Employee, lr.employee_id)
    if not emp:
        return

    app_name = _app_name()
    approve_link = _leave_url(lr.id)
    dates = _dates_phrase(lr)
    emp_name = emp.full_name
    summary = _leave_summary_html(lr)

    # HR — always notified on new submission
    hr_subject = f'{app_name} — {emp_name} applied for leave'
    hr_body = (
        f'<p style="margin:0 0 16px;font-size:17px;color:{BRAND_SLATE};">Hello,</p>'
        f'{_highlight_box(f"<strong>{escape(emp_name)}</strong> has applied for leave and is waiting for your response.", tone="warning")}'
        f'<p style="margin:0 0 8px;">Requested dates: <strong>{escape(dates)}</strong></p>'
        f'{summary}'
        f'{_email_button("Review leave request", approve_link)}'
    )
    hr_text = (
        f'{emp_name} has applied for leave and is waiting for your response.\n'
        f'Dates: {dates}\n'
        f'Review: {approve_link}\n'
    )
    _send_leave_email(
        _hr_notify_addresses(emp.company_id),
        hr_subject,
        _wrap_email(
            title='Leave request pending',
            subtitle='Action required from HR',
            body_html=hr_body,
            preheader=f'{emp_name} applied for leave — review required',
            employee=emp,
        ),
        hr_text,
    )

    # Supervisor — when supervisor step applies
    if lr.status == LEAVE_STATUS_PENDING:
        sup_subject = f'{app_name} — {emp_name} applied for leave (your approval needed)'
        sup_body = (
            f'<p style="margin:0 0 16px;font-size:17px;color:{BRAND_SLATE};">Hello,</p>'
            f'{_highlight_box(f"<strong>{escape(emp_name)}</strong> has applied for leave and is waiting for your response as their supervisor.", tone="warning")}'
            f'<p style="margin:0 0 8px;">Requested dates: <strong>{escape(dates)}</strong></p>'
            f'{summary}'
            f'{_email_button("Review leave request", approve_link)}'
        )
        sup_text = (
            f'{emp_name} has applied for leave and is waiting for your approval as supervisor.\n'
            f'Dates: {dates}\n'
            f'Review: {approve_link}\n'
        )
        _send_leave_email(
            _supervisor_inboxes(emp),
            sup_subject,
            _wrap_email(
                title='Supervisor approval needed',
                subtitle='Your team member is waiting',
                body_html=sup_body,
                preheader=f'{emp_name} needs your leave approval',
                employee=emp,
            ),
            sup_text,
        )

    # Employee confirmation
    employee_email = _employee_inbox(emp)
    if not employee_email:
        logger.warning('Leave submission confirmation skipped: no email for employee %s', emp.id)
        return

    if lr.status == LEAVE_STATUS_PENDING:
        wait_msg = (
            'Please wait for your <strong>supervisor</strong> and <strong>HR</strong> '
            'to review and confirm your leave.'
        )
        wait_text = (
            'Please wait for your supervisor and HR to review and confirm your leave.'
        )
    else:
        wait_msg = 'Please wait for <strong>HR</strong> to review and confirm your leave.'
        wait_text = 'Please wait for HR to review and confirm your leave.'

    emp_subject = f'{app_name} — Leave request received'
    emp_body = (
        f'<p style="margin:0 0 16px;font-size:17px;color:{BRAND_SLATE};">'
        f'Hello <strong>{escape(emp.first_name or emp.full_name)}</strong>,</p>'
        f'{_highlight_box(f"Your leave request has been received for <strong>{escape(dates)}</strong>.", tone="info")}'
        f'<p style="margin:0 0 16px;">{wait_msg}</p>'
        f'{_leave_summary_html(lr, include_employee=False)}'
        f'<p style="margin:16px 0 0;color:#64748b;font-size:13px;text-align:center;">'
        f'You will receive another email when your supervisor or HR responds.</p>'
        f'{_email_button("View my leave requests", _leave_index_url())}'
    )
    emp_text = (
        f'Hello {emp.first_name or emp.full_name},\n\n'
        f'Your leave request has been received.\n'
        f'You requested leave on {dates}.\n\n'
        f'{wait_text}\n\n'
        f'You will receive another email when your supervisor or HR responds.\n'
        f'View leave: {_leave_index_url()}\n'
    )
    _send_leave_email(
        [employee_email],
        emp_subject,
        _wrap_email(
            title='Leave request received',
            subtitle='We received your request',
            body_html=emp_body,
            preheader=f'Leave requested for {dates}',
            employee=emp,
        ),
        emp_text,
    )


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
    dates = _dates_phrase(lr)
    notes = ''
    if actor_stage == 'supervisor' and (lr.supervisor_notes or '').strip():
        notes = escape(lr.supervisor_notes.strip())
    elif actor_stage == 'hr' and (lr.review_notes or '').strip():
        notes = escape(lr.review_notes.strip())

    leave_index = _leave_index_url()
    tone = 'info'
    subtitle = 'Your request was updated'

    if action == 'reject':
        outcome = 'declined'
        detail_html = f'Your leave request for <strong>{escape(dates)}</strong> was <strong>declined</strong> by {actor_label}.'
        detail_text = f'Your leave request for {dates} was declined by {actor_label}.'
        title = 'Leave request declined'
        subtitle = f'Declined by {actor_label}'
        tone = 'danger'
    elif lr.status == LEAVE_STATUS_PENDING_HR and actor_stage == 'supervisor':
        outcome = 'supervisor approved'
        detail_html = (
            f'Your supervisor has approved your leave request for <strong>{escape(dates)}</strong>. '
            f'Please wait for <strong>HR approval</strong>.'
        )
        detail_text = (
            f'Your supervisor has approved your leave request for {dates}. '
            f'Please wait for HR approval.'
        )
        title = 'Supervisor approved'
        subtitle = 'Awaiting HR approval'
        tone = 'warning'
    elif lr.status == LEAVE_STATUS_APPROVED and actor_stage == 'hr':
        closing_html, closing_text = _hr_approval_closing(lr)
        outcome = 'approved'
        detail_html = (
            f'{escape(closing_html)} '
            f'Your approved leave is for <strong>{escape(dates)}</strong>.'
        )
        detail_text = f'{closing_text} Your approved leave is for {dates}.'
        title = 'Leave approved'
        subtitle = 'Approved by HR'
        tone = 'success'
    elif lr.status == LEAVE_STATUS_APPROVED:
        outcome = 'approved'
        detail_html = (
            f'Your leave request for <strong>{escape(dates)}</strong> was <strong>approved</strong> by {actor_label}.'
        )
        detail_text = f'Your leave request for {dates} was approved by {actor_label}.'
        title = 'Leave approved'
        subtitle = f'Approved by {actor_label}'
        tone = 'success'
    else:
        outcome = leave_status_label(lr.status)
        detail_html = f'Your leave request for <strong>{escape(dates)}</strong> was updated by {actor_label}.'
        detail_text = f'Your leave request for {dates} was updated by {actor_label}.'
        title = 'Leave request updated'

    summary = _leave_summary_html(lr, include_employee=False)
    subject = f'{app_name} — Leave request {outcome}'
    body = (
        f'<p style="margin:0 0 16px;font-size:17px;color:{BRAND_SLATE};">'
        f'Hello <strong>{escape(emp.first_name or emp.full_name)}</strong>,</p>'
        f'{_highlight_box(detail_html, tone=tone)}'
        f'{summary}'
    )
    if notes:
        body += (
            f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
            f'style="margin:0 0 16px;background:#fff;border:1px solid #e2e8f0;border-radius:6px;">'
            f'<tr><td style="padding:14px 16px;font-size:14px;color:#475569;">'
            f'<strong>Notes from {actor_label}:</strong> {notes}</td></tr></table>'
        )
    body += _email_button('View my leave requests', leave_index)

    text = f'Hello {emp.first_name or emp.full_name},\n\n{detail_text}\n'
    if notes:
        text += f'\nNotes from {actor_label}: {notes}\n'
    text += f'\nView leave: {leave_index}\n'

    _send_leave_email(
        [employee_email],
        subject,
        _wrap_email(
            title=title,
            subtitle=subtitle,
            body_html=body,
            preheader=detail_text,
            employee=emp,
        ),
        text,
    )
