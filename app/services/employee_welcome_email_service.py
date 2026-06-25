"""Welcome email when an employee is linked to a login account."""
from __future__ import annotations

import logging
from html import escape

from flask import current_app

from app.extensions import db
from app.models.company import Company
from app.models.employee import Employee
from app.models.user import User
from app.services.brevo_service import brevo_configured, send_transactional_email
from app.services.password_reset_service import external_base_url

logger = logging.getLogger(__name__)

BRAND_PRIMARY = '#ab0e1e'
BRAND_PRIMARY_DARK = '#8d0c18'
BRAND_SLATE = '#243444'
DEFAULT_PORTAL_URL = 'https://hrms.nexusafrica.co.ke'


def _app_name() -> str:
    return (current_app.config.get('APP_NAME') or 'Andersen').strip() or 'Andersen'


def _company_display_name(employee: Employee) -> str:
    company = db.session.get(Company, employee.company_id) if employee.company_id else None
    if company and company.employer_profile and (company.employer_profile.name or '').strip():
        return company.employer_profile.name.strip()
    if company and (company.name or '').strip():
        return company.name.strip()
    return _app_name()


def login_portal_url() -> str:
    base = (external_base_url() or '').strip().rstrip('/')
    if not base:
        base = (current_app.config.get('APP_BASE_URL') or DEFAULT_PORTAL_URL).strip().rstrip('/')
    return f'{base}/auth/login'


def _logo_url() -> str | None:
    base = (external_base_url() or '').strip().rstrip('/')
    if not base:
        base = (current_app.config.get('APP_BASE_URL') or DEFAULT_PORTAL_URL).strip().rstrip('/')
    if not base:
        return None
    return f'{base}/static/brand/andersen-logo.jpg'


def _greeting_name(employee: Employee) -> str:
    if (employee.first_name or '').strip():
        return employee.first_name.strip()
    return employee.full_name or 'there'


def build_welcome_email_html(
    *,
    employee: Employee,
    login_email: str,
    password: str,
    must_change_password: bool,
) -> str:
    app_name = escape(_app_name())
    company_name = escape(_company_display_name(employee))
    greeting = escape(_greeting_name(employee))
    portal_url = escape(login_portal_url())
    email_safe = escape(login_email)
    password_safe = escape(password)
    logo = _logo_url()

    logo_block = ''
    if logo:
        logo_block = (
            f'<img src="{escape(logo)}" alt="{app_name}" width="160" '
            f'style="display:block;margin:0 auto 12px;max-width:160px;height:auto;">'
        )

    pwd_change_note = ''
    if must_change_password:
        pwd_change_note = (
            '<p style="margin:16px 0 0;font-size:13px;color:#64748b;line-height:1.5;">'
            'For security, you will be asked to <strong>change your password</strong> '
            'the first time you sign in.</p>'
        )

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Welcome to {app_name}</title>
</head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f1f5f9;padding:32px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:600px;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(36,52,68,0.12);">
          <tr>
            <td style="background:linear-gradient(135deg,{BRAND_PRIMARY} 0%,{BRAND_PRIMARY_DARK} 100%);padding:28px 32px;text-align:center;">
              {logo_block}
              <p style="margin:0;font-size:13px;letter-spacing:0.08em;text-transform:uppercase;color:rgba(255,255,255,0.85);">Human Resource Management</p>
              <h1 style="margin:8px 0 0;font-size:24px;font-weight:600;color:#ffffff;line-height:1.3;">Welcome to {app_name}</h1>
            </td>
          </tr>
          <tr>
            <td style="padding:32px 32px 8px;">
              <p style="margin:0 0 16px;font-size:16px;line-height:1.6;color:{BRAND_SLATE};">
                Hello <strong>{greeting}</strong>,
              </p>
              <p style="margin:0 0 16px;font-size:15px;line-height:1.65;color:#475569;">
                Your login account for <strong>{company_name}</strong> on <strong>{app_name} HRMS</strong> has been created.
                You can now access the portal to manage your work-related information in one place.
              </p>
              <p style="margin:0 0 12px;font-size:14px;font-weight:600;color:{BRAND_SLATE};">What you can do on the system</p>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 24px;">
                <tr>
                  <td style="padding:10px 14px;background:#f8fafc;border-radius:8px;border-left:4px solid {BRAND_PRIMARY};">
                    <p style="margin:0 0 8px;font-size:14px;line-height:1.55;color:#334155;"><strong>1.</strong> View your employee profile — personal details, employment information, and documents.</p>
                    <p style="margin:0 0 8px;font-size:14px;line-height:1.55;color:#334155;"><strong>2.</strong> View leave balances, apply for leave, and track the status of your leave requests.</p>
                    <p style="margin:0 0 8px;font-size:14px;line-height:1.55;color:#334155;"><strong>3.</strong> Request IT support when you need help with systems or equipment.</p>
                    <p style="margin:0 0 8px;font-size:14px;line-height:1.55;color:#334155;"><strong>4.</strong> Send messages to colleagues and receive communications from others within the organisation.</p>
                    <p style="margin:0;font-size:14px;line-height:1.55;color:#334155;"><strong>5.</strong> Explore other features available to you — payslips, career history, and more as enabled by HR.</p>
                  </td>
                </tr>
              </table>
              <p style="margin:0 0 12px;font-size:14px;font-weight:600;color:{BRAND_SLATE};">How to sign in</p>
              <ol style="margin:0 0 24px;padding-left:20px;font-size:14px;line-height:1.75;color:#475569;">
                <li>Open your web browser (Chrome, Edge, Safari, or Firefox).</li>
                <li>Go to the portal: <a href="{portal_url}" style="color:{BRAND_PRIMARY};font-weight:600;">{portal_url}</a></li>
                <li>Enter your login email and password (see below).</li>
                <li>Click <strong>Sign In</strong>.</li>
                <li>After signing in, use the menu on the left to navigate the system.</li>
              </ol>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 24px;background:#fef2f2;border:1px solid #fecaca;border-radius:10px;">
                <tr>
                  <td style="padding:18px 20px;">
                    <p style="margin:0 0 10px;font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:0.04em;color:{BRAND_PRIMARY};">Your login credentials</p>
                    <p style="margin:0 0 6px;font-size:14px;color:#334155;"><strong>Portal URL:</strong> <a href="{portal_url}" style="color:{BRAND_PRIMARY};">{portal_url}</a></p>
                    <p style="margin:0 0 6px;font-size:14px;color:#334155;"><strong>Email:</strong> {email_safe}</p>
                    <p style="margin:0;font-size:14px;color:#334155;"><strong>Password:</strong> {password_safe}</p>
                    {pwd_change_note}
                  </td>
                </tr>
              </table>
              <p style="margin:0 0 24px;text-align:center;">
                <a href="{portal_url}" style="display:inline-block;padding:14px 28px;background:{BRAND_PRIMARY};color:#ffffff;text-decoration:none;font-size:15px;font-weight:600;border-radius:8px;">Sign in to {app_name}</a>
              </p>
              <p style="margin:0;font-size:13px;line-height:1.6;color:#64748b;">
                Keep your password confidential. If you did not expect this account or need assistance, please contact your HR department.
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 32px 28px;background:#f8fafc;border-top:1px solid #e2e8f0;text-align:center;">
              <p style="margin:0;font-size:12px;color:#94a3b8;line-height:1.5;">
                {company_name} · {app_name} HRMS<br>
                This is an automated message — please do not reply to this email.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def build_welcome_email_text(
    *,
    employee: Employee,
    login_email: str,
    password: str,
    must_change_password: bool,
) -> str:
    app_name = _app_name()
    company_name = _company_display_name(employee)
    greeting = _greeting_name(employee)
    portal_url = login_portal_url()
    lines = [
        f'Welcome to {app_name} HRMS',
        '',
        f'Hello {greeting},',
        '',
        f'Your login account for {company_name} has been created.',
        '',
        'What you can do:',
        '1. View your employee data',
        '2. View leave days, apply for leave, and monitor leave requests',
        '3. Request IT support',
        '4. Send and receive communications with colleagues',
        '5. Explore other features (payslips, career history, and more)',
        '',
        'How to sign in:',
        f'1. Open your browser and go to: {portal_url}',
        f'2. Email: {login_email}',
        f'3. Password: {password}',
        '4. Click Sign In',
    ]
    if must_change_password:
        lines.append('5. You will be prompted to change your password on first login.')
    lines.extend([
        '',
        'Keep your password confidential. Contact HR if you need help.',
        '',
        f'{company_name} · {app_name} HRMS',
    ])
    return '\n'.join(lines)


def send_employee_welcome_email(
    user: User,
    employee: Employee,
    password: str,
    *,
    must_change_password: bool | None = None,
) -> bool:
    """Send welcome email with login details. Returns True if sent successfully."""
    if not (user.email or '').strip():
        logger.warning('Welcome email skipped — no login email for employee_id=%s', employee.id)
        return False
    if not brevo_configured():
        logger.warning(
            'Welcome email skipped — Brevo not configured (employee_id=%s email=%s)',
            employee.id,
            user.email,
        )
        return False

    must_change = user.must_change_password if must_change_password is None else must_change_password
    app_name = _app_name()
    subject = f'Welcome to {app_name} HRMS — your login details'
    html = build_welcome_email_html(
        employee=employee,
        login_email=user.email.strip(),
        password=password,
        must_change_password=must_change,
    )
    text = build_welcome_email_text(
        employee=employee,
        login_email=user.email.strip(),
        password=password,
        must_change_password=must_change,
    )
    ok = send_transactional_email(user.email.strip(), subject, html, text_content=text)
    if ok:
        logger.info('Welcome email sent to %s (employee_id=%s)', user.email, employee.id)
    else:
        logger.warning('Welcome email failed for %s (employee_id=%s)', user.email, employee.id)
    return ok
