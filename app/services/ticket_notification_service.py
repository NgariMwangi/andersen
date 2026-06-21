"""In-app and email notifications for IT tickets (Brevo)."""
from __future__ import annotations

import logging
from html import escape

from flask import current_app, url_for
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.it_ticket import TICKET_STATUS_LABELS, Ticket, TicketComment
from app.models.notification import Notification
from app.models.user import Permission, Role, RolePermission, User, UserRole
from app.services.brevo_service import normalize_hr_sender_email, send_transactional_email
from app.services.password_reset_service import external_base_url
from app.services.ticket_service import get_ticket_for_company

logger = logging.getLogger(__name__)


def _app_name() -> str:
    return (current_app.config.get('APP_NAME') or 'HRMS').strip() or 'HRMS'


def _ticket_url(ticket_id: int) -> str:
    return external_base_url() + url_for('it_tickets.view', id=ticket_id)


def _user_email(user: User | None) -> str | None:
    if not user:
        return None
    email = (user.email or '').strip().lower()
    if email:
        return email
    emp = getattr(user, 'employee', None)
    if emp:
        for addr in (emp.email, emp.secondary_email):
            if addr and str(addr).strip():
                return str(addr).strip().lower()
    return None


def _users_with_permission(company_id: int, permission_code: str) -> list[User]:
    perm = db.session.query(Permission).filter(Permission.code == permission_code).first()
    if not perm:
        return []
    return (
        db.session.query(User)
        .options(joinedload(User.employee))
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


def _it_staff_users(company_id: int) -> list[User]:
    seen: set[int] = set()
    users: list[User] = []
    for code in ('view_tickets', 'manage_tickets'):
        for user in _users_with_permission(company_id, code):
            if user.id not in seen:
                seen.add(user.id)
                users.append(user)
    return users


def _it_staff_emails(company_id: int) -> list[str]:
    configured = (current_app.config.get('IT_NOTIFY_EMAIL') or '').strip()
    if not configured:
        configured = (current_app.config.get('BREVO_SENDER_EMAIL') or '').strip()
    addresses = {normalize_hr_sender_email(a) for a in configured.split(',') if a.strip()}

    for user in _it_staff_users(company_id):
        email = _user_email(user)
        if email:
            addresses.add(email)
    return sorted(addresses)


def _create_in_app_notification(
    *,
    user_id: int,
    title: str,
    message: str | None,
    link: str,
    ticket_id: int,
) -> None:
    db.session.add(
        Notification(
            user_id=user_id,
            title=title,
            message=message,
            link=link,
            read=False,
            related_type='it_ticket',
            related_id=ticket_id,
        )
    )


def _send_ticket_email(to_addresses: list[str], subject: str, html: str, text: str) -> None:
    seen: set[str] = set()
    for addr in to_addresses:
        email = (addr or '').strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        ok = send_transactional_email(email, subject, html, text_content=text)
        if not ok:
            logger.warning('Ticket notification not sent to %s (%s)', email, subject)


def _ticket_summary_html(ticket: Ticket) -> str:
    requester_name = '—'
    if ticket.requester and ticket.requester.employee:
        requester_name = ticket.requester.employee.full_name
    elif ticket.requester:
        requester_name = ticket.requester.email or 'User'
    category = ticket.category.name if ticket.category else '—'
    asset_line = ''
    if ticket.related_asset:
        asset = ticket.related_asset
        asset_label = asset.asset_tag
        if asset.name:
            asset_label += f' — {asset.name}'
        asset_line = f'<tr><td style="padding:4px 12px 4px 0;color:#64748b;">Asset</td><td>{escape(asset_label)}</td></tr>'
    return f"""
    <table style="border-collapse:collapse;margin:12px 0;font-size:14px;">
      <tr><td style="padding:4px 12px 4px 0;color:#64748b;">Ticket</td><td><strong>{escape(ticket.ticket_number)}</strong></td></tr>
      <tr><td style="padding:4px 12px 4px 0;color:#64748b;">Subject</td><td>{escape(ticket.subject)}</td></tr>
      <tr><td style="padding:4px 12px 4px 0;color:#64748b;">Category</td><td>{escape(category)}</td></tr>
      {asset_line}
      <tr><td style="padding:4px 12px 4px 0;color:#64748b;">Priority</td><td>{escape(ticket.priority_label)}</td></tr>
      <tr><td style="padding:4px 12px 4px 0;color:#64748b;">Status</td><td>{escape(ticket.status_label)}</td></tr>
      <tr><td style="padding:4px 12px 4px 0;color:#64748b;">Requester</td><td>{escape(requester_name)}</td></tr>
    </table>
    """


def _notify_it_staff_in_app(ticket: Ticket, *, title: str, message: str) -> None:
    link = url_for('it_tickets.view', id=ticket.id)
    requester_id = int(ticket.requester_user_id or 0)
    for user in _it_staff_users(ticket.company_id):
        if user.id == requester_id:
            continue
        _create_in_app_notification(
            user_id=user.id,
            title=title,
            message=message,
            link=link,
            ticket_id=ticket.id,
        )


def notify_ticket_created(ticket_id: int) -> None:
    ticket = get_ticket_for_company(ticket_id, _load_company_id(ticket_id))
    if not ticket:
        return

    app_name = _app_name()
    link = _ticket_url(ticket.id)
    summary = _ticket_summary_html(ticket)
    subject = f'{app_name} — New IT ticket {ticket.ticket_number}'
    html = f"""
    <p>Hello,</p>
    <p>A new IT support ticket has been submitted.</p>
    {summary}
    <p style="white-space:pre-wrap;">{escape(ticket.description)}</p>
    <p><a href="{link}" style="display:inline-block;padding:10px 18px;background:#ab0e1e;color:#fff;text-decoration:none;border-radius:6px;">View ticket</a></p>
    <p style="color:#64748b;font-size:12px;">{escape(app_name)}</p>
    """
    text = (
        f'New IT ticket {ticket.ticket_number}\n'
        f'Subject: {ticket.subject}\n'
        f'View: {link}\n'
    )

    _notify_it_staff_in_app(
        ticket,
        title=f'New ticket {ticket.ticket_number}',
        message=ticket.subject,
    )

    if ticket.requester_user_id:
        _create_in_app_notification(
            user_id=ticket.requester_user_id,
            title=f'Ticket {ticket.ticket_number} submitted',
            message='Your IT request has been received.',
            link=url_for('it_tickets.view', id=ticket.id),
            ticket_id=ticket.id,
        )

    _send_ticket_email(_it_staff_emails(ticket.company_id), subject, html, text)

    requester_email = _user_email(ticket.requester)
    if requester_email:
        emp_subject = f'{app_name} — IT ticket {ticket.ticket_number} submitted'
        emp_html = f"""
        <p>Hello,</p>
        <p>Your IT support request has been received. The IT team will review it shortly.</p>
        {summary}
        <p><a href="{link}" style="display:inline-block;padding:10px 18px;background:#ab0e1e;color:#fff;text-decoration:none;border-radius:6px;">View ticket</a></p>
        <p style="color:#64748b;font-size:12px;">{escape(app_name)}</p>
        """
        emp_text = f'Your IT ticket {ticket.ticket_number} was submitted.\nView: {link}\n'
        _send_ticket_email([requester_email], emp_subject, emp_html, emp_text)


def notify_ticket_assigned(ticket_id: int) -> None:
    ticket = get_ticket_for_company(ticket_id, _load_company_id(ticket_id))
    if not ticket or not ticket.assigned_to_user_id:
        return

    app_name = _app_name()
    link = _ticket_url(ticket.id)
    assignee = ticket.assigned_to
    assignee_name = assignee.email if assignee else 'IT staff'
    if assignee and assignee.employee:
        assignee_name = assignee.employee.full_name

    summary = _ticket_summary_html(ticket)
    subject = f'{app_name} — Ticket {ticket.ticket_number} assigned'
    html = f"""
    <p>Hello,</p>
    <p>Ticket <strong>{escape(ticket.ticket_number)}</strong> has been assigned to <strong>{escape(assignee_name)}</strong>.</p>
    {summary}
    <p><a href="{link}" style="display:inline-block;padding:10px 18px;background:#ab0e1e;color:#fff;text-decoration:none;border-radius:6px;">View ticket</a></p>
    <p style="color:#64748b;font-size:12px;">{escape(app_name)}</p>
    """
    text = f'Ticket {ticket.ticket_number} assigned to {assignee_name}.\nView: {link}\n'

    if ticket.assigned_to_user_id:
        _create_in_app_notification(
            user_id=ticket.assigned_to_user_id,
            title=f'Assigned: {ticket.ticket_number}',
            message=ticket.subject,
            link=url_for('it_tickets.view', id=ticket.id),
            ticket_id=ticket.id,
        )
    if ticket.requester_user_id:
        _create_in_app_notification(
            user_id=ticket.requester_user_id,
            title=f'{ticket.ticket_number} assigned',
            message=f'Assigned to {assignee_name}',
            link=url_for('it_tickets.view', id=ticket.id),
            ticket_id=ticket.id,
        )

    recipients = []
    assignee_email = _user_email(assignee)
    if assignee_email:
        recipients.append(assignee_email)
    requester_email = _user_email(ticket.requester)
    if requester_email:
        recipients.append(requester_email)
    _send_ticket_email(recipients, subject, html, text)


def notify_ticket_status_changed(ticket_id: int) -> None:
    ticket = get_ticket_for_company(ticket_id, _load_company_id(ticket_id))
    if not ticket:
        return

    app_name = _app_name()
    link = _ticket_url(ticket.id)
    status_label = TICKET_STATUS_LABELS.get(ticket.status, ticket.status)
    summary = _ticket_summary_html(ticket)
    subject = f'{app_name} — Ticket {ticket.ticket_number} — {status_label}'
    html = f"""
    <p>Hello,</p>
    <p>Ticket <strong>{escape(ticket.ticket_number)}</strong> status is now <strong>{escape(status_label)}</strong>.</p>
    {summary}
    <p><a href="{link}" style="display:inline-block;padding:10px 18px;background:#ab0e1e;color:#fff;text-decoration:none;border-radius:6px;">View ticket</a></p>
    <p style="color:#64748b;font-size:12px;">{escape(app_name)}</p>
    """
    text = f'Ticket {ticket.ticket_number} status: {status_label}\nView: {link}\n'

    if ticket.requester_user_id:
        _create_in_app_notification(
            user_id=ticket.requester_user_id,
            title=f'{ticket.ticket_number}: {status_label}',
            message=ticket.subject,
            link=url_for('it_tickets.view', id=ticket.id),
            ticket_id=ticket.id,
        )

    recipients = []
    requester_email = _user_email(ticket.requester)
    if requester_email:
        recipients.append(requester_email)
    if ticket.assigned_to_user_id:
        assignee_email = _user_email(ticket.assigned_to)
        if assignee_email and assignee_email not in recipients:
            recipients.append(assignee_email)
    _send_ticket_email(recipients, subject, html, text)


def notify_ticket_comment(ticket_id: int, comment_id: int) -> None:
    ticket = get_ticket_for_company(ticket_id, _load_company_id(ticket_id))
    if not ticket:
        return
    comment = db.session.get(TicketComment, comment_id)
    if not comment:
        return

    app_name = _app_name()
    link = _ticket_url(ticket.id)
    author_name = comment.author.email if comment.author else 'User'
    if comment.author and comment.author.employee:
        author_name = comment.author.employee.full_name

    subject = f'{app_name} — New reply on {ticket.ticket_number}'
    html = f"""
    <p>Hello,</p>
    <p><strong>{escape(author_name)}</strong> replied on ticket <strong>{escape(ticket.ticket_number)}</strong>:</p>
    <p style="white-space:pre-wrap;background:#f8fafc;padding:12px;border-radius:6px;">{escape(comment.body)}</p>
    <p><a href="{link}" style="display:inline-block;padding:10px 18px;background:#ab0e1e;color:#fff;text-decoration:none;border-radius:6px;">View ticket</a></p>
    <p style="color:#64748b;font-size:12px;">{escape(app_name)}</p>
    """
    text = f'New reply on {ticket.ticket_number} from {author_name}.\nView: {link}\n'

    author_id = int(comment.author_user_id or 0)
    notify_user_ids: set[int] = set()
    if ticket.requester_user_id and ticket.requester_user_id != author_id:
        notify_user_ids.add(ticket.requester_user_id)
    if ticket.assigned_to_user_id and ticket.assigned_to_user_id != author_id:
        notify_user_ids.add(ticket.assigned_to_user_id)
    for user in _it_staff_users(ticket.company_id):
        if user.id != author_id:
            notify_user_ids.add(user.id)

    for uid in notify_user_ids:
        _create_in_app_notification(
            user_id=uid,
            title=f'Reply on {ticket.ticket_number}',
            message=comment.body[:200],
            link=url_for('it_tickets.view', id=ticket.id),
            ticket_id=ticket.id,
        )

    recipients: list[str] = []
    if ticket.requester_user_id != author_id:
        email = _user_email(ticket.requester)
        if email:
            recipients.append(email)
    if ticket.assigned_to_user_id and ticket.assigned_to_user_id != author_id:
        email = _user_email(ticket.assigned_to)
        if email and email not in recipients:
            recipients.append(email)
    if not ticket.assigned_to_user_id and author_id != ticket.requester_user_id:
        for addr in _it_staff_emails(ticket.company_id):
            if addr not in recipients:
                recipients.append(addr)
    _send_ticket_email(recipients, subject, html, text)


def _load_company_id(ticket_id: int) -> int:
    row = db.session.query(Ticket.company_id).filter(Ticket.id == ticket_id).first()
    return int(row[0]) if row else 0
