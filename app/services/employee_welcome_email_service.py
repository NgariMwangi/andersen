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

FEATURES: tuple[tuple[str, str, str], ...] = (
    ('View your employee data', 'Personal details, employment information, and uploaded documents.'),
    ('Leave management', 'Check leave balances, apply for leave, and follow request status.'),
    ('IT support', 'Log tickets when you need help with software, systems, or equipment.'),
    ('Internal communications', 'Send and receive messages with colleagues across the organisation.'),
    ('More to explore', 'Payslips, career history, and other tools enabled by your HR team.'),
)


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


def _portal_host() -> str:
    url = login_portal_url()
    return url.replace('https://', '').replace('http://', '').split('/')[0]


def _greeting_name(employee: Employee) -> str:
    if (employee.first_name or '').strip():
        return employee.first_name.strip()
    return employee.full_name or 'there'


def _feature_rows_html() -> str:
    rows = []
    for index, (title, detail) in enumerate(FEATURES, start=1):
        rows.append(
            f'<tr>'
            f'<td style="padding:0 0 10px 0;">'
            f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
            f'style="border:1px solid #e2e8f0;border-left:4px solid {BRAND_PRIMARY};background-color:#f8fafc;">'
            f'<tr>'
            f'<td width="36" valign="top" style="padding:14px 0 14px 14px;font-size:15px;font-weight:700;'
            f'color:{BRAND_PRIMARY};font-family:Helvetica,Arial,sans-serif;">{index}</td>'
            f'<td valign="top" style="padding:14px 14px 14px 0;font-family:Helvetica,Arial,sans-serif;">'
            f'<p style="margin:0 0 4px;font-size:14px;font-weight:700;color:{BRAND_SLATE};">{escape(title)}</p>'
            f'<p style="margin:0;font-size:13px;line-height:1.55;color:#64748b;">{escape(detail)}</p>'
            f'</td></tr></table></td></tr>'
        )
    return ''.join(rows)


def _credential_row(label: str, value: str, *, monospace: bool = False) -> str:
    value_style = (
        'font-family:Consolas,Monaco,"Courier New",monospace;font-size:14px;font-weight:700;'
        if monospace
        else 'font-size:14px;font-weight:600;'
    )
    return (
        f'<tr>'
        f'<td width="120" valign="top" style="padding:8px 0;font-size:13px;color:#64748b;'
        f'font-family:Helvetica,Arial,sans-serif;">{escape(label)}</td>'
        f'<td valign="top" style="padding:8px 0;color:{BRAND_SLATE};{value_style}'
        f'font-family:Helvetica,Arial,sans-serif;">{escape(value)}</td>'
        f'</tr>'
    )


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
    portal_url = login_portal_url()
    portal_url_safe = escape(portal_url)
    portal_host = escape(_portal_host())

    pwd_change_note = ''
    if must_change_password:
        pwd_change_note = (
            f'<tr><td colspan="2" style="padding:12px 0 0;font-size:13px;line-height:1.5;'
            f'color:#64748b;font-family:Helvetica,Arial,sans-serif;">'
            f'<strong style="color:{BRAND_PRIMARY};">Important:</strong> '
            f'You will be asked to choose a new password the first time you sign in.</td></tr>'
        )

    preheader = escape(
        f'Your { _app_name() } HRMS account is ready. Sign in at { _portal_host() } with the credentials inside.'
    )

    return f"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" lang="en">
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Welcome to {app_name} HRMS</title>
</head>
<body style="margin:0;padding:0;background-color:#eef2f7;width:100%;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">
  <div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">{preheader}&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;</div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color:#eef2f7;">
    <tr>
      <td align="center" style="padding:32px 16px;">
        <table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0" style="width:100%;max-width:600px;background-color:#ffffff;border:1px solid #e2e8f0;">

          <!-- Header -->
          <tr>
            <td align="center" bgcolor="{BRAND_PRIMARY}" style="background-color:{BRAND_PRIMARY};padding:32px 28px;">
              <p style="margin:0 0 6px;font-size:11px;letter-spacing:0.14em;text-transform:uppercase;color:#ffffff;font-family:Helvetica,Arial,sans-serif;opacity:0.9;">Human Resource Management</p>
              <p style="margin:0 0 8px;font-size:28px;font-weight:700;color:#ffffff;letter-spacing:0.04em;font-family:Helvetica,Arial,sans-serif;">{app_name}</p>
              <p style="margin:0;font-size:16px;color:#ffffff;font-family:Helvetica,Arial,sans-serif;">Welcome to your HR portal</p>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:32px 28px 8px;font-family:Helvetica,Arial,sans-serif;">
              <p style="margin:0 0 16px;font-size:17px;line-height:1.5;color:{BRAND_SLATE};">
                Hello <strong>{greeting}</strong>,
              </p>
              <p style="margin:0 0 24px;font-size:15px;line-height:1.65;color:#475569;">
                Your login account for <strong>{company_name}</strong> on <strong>{app_name} HRMS</strong> has been created.
                Use the portal to manage your work information securely, anytime.
              </p>

              <p style="margin:0 0 14px;font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:{BRAND_SLATE};">
                What you can do
              </p>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin:0 0 28px;">
                {_feature_rows_html()}
              </table>

              <p style="margin:0 0 14px;font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:{BRAND_SLATE};">
                How to sign in
              </p>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin:0 0 28px;background-color:#f8fafc;border:1px solid #e2e8f0;">
                <tr>
                  <td style="padding:18px 20px;font-family:Helvetica,Arial,sans-serif;">
                    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                      <tr>
                        <td width="28" valign="top" style="padding:0 10px 12px 0;font-size:14px;font-weight:700;color:{BRAND_PRIMARY};">1</td>
                        <td style="padding:0 0 12px;font-size:14px;line-height:1.55;color:#475569;">Open Chrome, Edge, Safari, or Firefox on your computer or phone.</td>
                      </tr>
                      <tr>
                        <td width="28" valign="top" style="padding:0 10px 12px 0;font-size:14px;font-weight:700;color:{BRAND_PRIMARY};">2</td>
                        <td style="padding:0 0 12px;font-size:14px;line-height:1.55;color:#475569;">Go to <a href="{portal_url_safe}" style="color:{BRAND_PRIMARY};font-weight:700;text-decoration:none;">{portal_host}</a></td>
                      </tr>
                      <tr>
                        <td width="28" valign="top" style="padding:0 10px 12px 0;font-size:14px;font-weight:700;color:{BRAND_PRIMARY};">3</td>
                        <td style="padding:0 0 12px;font-size:14px;line-height:1.55;color:#475569;">Enter your email and password below, then click <strong>Sign In</strong>.</td>
                      </tr>
                      <tr>
                        <td width="28" valign="top" style="padding:0;font-size:14px;font-weight:700;color:{BRAND_PRIMARY};">4</td>
                        <td style="padding:0;font-size:14px;line-height:1.55;color:#475569;">Use the menu on the left to navigate after you log in.</td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <p style="margin:0 0 14px;font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:{BRAND_PRIMARY};">
                Your login credentials
              </p>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin:0 0 28px;background-color:#fff5f5;border:1px solid #fecaca;">
                <tr>
                  <td style="padding:20px 22px;">
                    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                      {_credential_row('Portal URL', portal_url)}
                      {_credential_row('Email', login_email)}
                      {_credential_row('Password', password, monospace=True)}
                      {pwd_change_note}
                    </table>
                  </td>
                </tr>
              </table>

              <!-- Bulletproof button -->
              <table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center" style="margin:0 auto 28px;">
                <tr>
                  <td align="center" bgcolor="{BRAND_PRIMARY}" style="background-color:{BRAND_PRIMARY};border-radius:6px;">
                    <a href="{portal_url_safe}" target="_blank" style="display:inline-block;padding:15px 36px;font-family:Helvetica,Arial,sans-serif;font-size:15px;font-weight:700;color:#ffffff;text-decoration:none;border-radius:6px;">
                      Sign in to {app_name}
                    </a>
                  </td>
                </tr>
              </table>

              <p style="margin:0;font-size:13px;line-height:1.65;color:#64748b;text-align:center;">
                Keep your password private. If you did not expect this email, contact your HR department.
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td align="center" bgcolor="#f8fafc" style="background-color:#f8fafc;padding:22px 28px;border-top:1px solid #e2e8f0;">
              <p style="margin:0 0 4px;font-size:13px;font-weight:600;color:{BRAND_SLATE};font-family:Helvetica,Arial,sans-serif;">{company_name}</p>
              <p style="margin:0;font-size:12px;line-height:1.5;color:#94a3b8;font-family:Helvetica,Arial,sans-serif;">
                {app_name} HRMS &middot; Automated message — please do not reply
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
        '=' * 40,
        '',
        f'Hello {greeting},',
        '',
        f'Your login account for {company_name} has been created.',
        '',
        'WHAT YOU CAN DO',
        '-' * 20,
    ]
    for index, (title, detail) in enumerate(FEATURES, start=1):
        lines.append(f'{index}. {title} — {detail}')
    lines.extend([
        '',
        'HOW TO SIGN IN',
        '-' * 20,
        f'1. Open your browser and go to: {portal_url}',
        f'2. Email: {login_email}',
        f'3. Password: {password}',
        '4. Click Sign In',
        '5. Use the menu on the left after logging in',
    ])
    if must_change_password:
        lines.append('6. You will be prompted to change your password on first login.')
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
    ok = send_transactional_email(
        user.email.strip(),
        subject,
        html,
        text_content=text,
        sender_name=f'{app_name} HRMS',
    )
    if ok:
        logger.info('Welcome email sent to %s (employee_id=%s)', user.email, employee.id)
    else:
        logger.warning('Welcome email failed for %s (employee_id=%s)', user.email, employee.id)
    return ok
