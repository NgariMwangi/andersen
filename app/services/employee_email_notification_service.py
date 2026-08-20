"""Email notifications when employee contact details change."""
from __future__ import annotations

import logging
from html import escape

from flask import current_app

from app.models.employee import Employee
from app.services.brevo_service import brevo_configured, send_transactional_email
from app.services.employee_welcome_email_service import (
    _app_name,
    _company_display_name,
    _greeting_name,
    login_portal_url,
)

logger = logging.getLogger(__name__)

BRAND_PRIMARY = '#ab0e1e'
BRAND_SLATE = '#243444'


def _normalize_email(value: str | None) -> str | None:
    raw = (value or '').strip().lower()
    if not raw or '@' not in raw:
        return None
    return raw


def mask_email_for_display(email: str | None) -> str:
    """Mask local part for notifications, e.g. ******@ke.andersen.com."""
    normalized = _normalize_email(email)
    if not normalized:
        return '******'
    _local, domain = normalized.split('@', 1)
    return f'******@{domain}'


def primary_email_changed(old_email: str | None, new_email: str | None) -> bool:
    return _normalize_email(old_email) != _normalize_email(new_email)


def notify_primary_email_changed(
    employee: Employee,
    old_email: str | None,
    new_email: str | None,
) -> bool:
    """
    Notify the employee at their new primary email when it changes.
    Returns True if an email was sent successfully.
    """
    old_norm = _normalize_email(old_email)
    new_norm = _normalize_email(new_email)
    if not new_norm or old_norm == new_norm:
        return False

    if not brevo_configured():
        logger.warning(
            'Primary email change notification skipped — Brevo not configured (employee_id=%s)',
            employee.id,
        )
        return False

    app_name = _app_name()
    greeting = escape(_greeting_name(employee))
    company_name = escape(_company_display_name(employee))
    masked_old = escape(mask_email_for_display(old_email))
    masked_new = escape(mask_email_for_display(new_email))
    portal_url = escape(login_portal_url())
    portal_host = escape(login_portal_url().replace('https://', '').replace('http://', '').split('/')[0])

    subject = f'{app_name} — Your work email was updated'
    body_html = (
        f'<p style="margin:0 0 16px;font-size:17px;line-height:1.5;color:{BRAND_SLATE};">'
        f'Hello <strong>{greeting}</strong>,</p>'
        f'<p style="margin:0 0 16px;font-size:15px;line-height:1.65;color:#475569;">'
        f'Your primary work email on <strong>{company_name}</strong> {app_name} HRMS has been updated.</p>'
        f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
        f'style="margin:0 0 20px;background-color:#f8fafc;border:1px solid #e2e8f0;border-left:4px solid {BRAND_PRIMARY};">'
        f'<tr><td style="padding:18px 20px;font-family:Helvetica,Arial,sans-serif;">'
        f'<p style="margin:0;font-size:15px;line-height:1.6;color:{BRAND_SLATE};">'
        f'Changed from <strong>{masked_old}</strong> to <strong>{masked_new}</strong>.</p>'
        f'</td></tr></table>'
        f'<p style="margin:0 0 16px;font-size:14px;line-height:1.6;color:#64748b;">'
        f'If you did not request this change, contact your HR department immediately.</p>'
        f'<p style="margin:0;font-size:14px;line-height:1.6;color:#64748b;">'
        f'Sign in at <a href="{portal_url}" style="color:{BRAND_PRIMARY};font-weight:600;">{portal_host}</a> '
        f'using your updated email if you have a login account.</p>'
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"/><title>{escape(subject)}</title></head>
<body style="margin:0;padding:24px;background:#eef2f7;font-family:Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:600px;margin:0 auto;background:#fff;border:1px solid #e2e8f0;">
    <tr><td bgcolor="{BRAND_PRIMARY}" style="background:{BRAND_PRIMARY};padding:24px;color:#fff;">
      <p style="margin:0;font-size:22px;font-weight:700;">{escape(app_name)} HRMS</p>
      <p style="margin:8px 0 0;font-size:14px;opacity:0.95;">Work email updated</p>
    </td></tr>
    <tr><td style="padding:28px;">{body_html}</td></tr>
  </table>
</body>
</html>"""
    text = (
        f'Hello {_greeting_name(employee)},\n\n'
        f'Your primary work email on {company_name} {app_name} HRMS has been updated.\n'
        f'Changed from {mask_email_for_display(old_email)} to {mask_email_for_display(new_email)}.\n\n'
        f'If you did not request this change, contact HR immediately.\n'
        f'Sign in: {login_portal_url()}\n'
    )

    ok = send_transactional_email(
        new_norm,
        subject,
        html,
        text_content=text,
        sender_name=f'{app_name} HRMS',
    )
    if ok:
        logger.info(
            'Primary email change notification sent to employee_id=%s new_email=%s',
            employee.id,
            mask_email_for_display(new_norm),
        )
    else:
        logger.warning(
            'Primary email change notification failed for employee_id=%s new_email=%s',
            employee.id,
            mask_email_for_display(new_norm),
        )
    return ok
