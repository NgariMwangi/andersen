"""Email employee payslips with PDF attachment via Brevo."""
from __future__ import annotations

import logging
from html import escape

from flask import current_app
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.employee import Employee
from app.models.payroll import PayrollItem, PayrollRun
from app.services.brevo_service import brevo_configured, send_transactional_email
from app.services.leave_notification_service import _employee_inbox
from app.services.payslip_pdf_service import build_payslip_context, build_payslip_pdf, payslip_pdf_filename

logger = logging.getLogger(__name__)

_PAYSLIP_SEND_RUN_STATUSES = ('approved', 'finance_reviewed', 'paid')


def _app_name() -> str:
    return (current_app.config.get('APP_NAME') or 'HRMS').strip() or 'HRMS'


def send_payslip_email(item: PayrollItem) -> tuple[bool, str]:
    """
    Email one payslip PDF to the employee.
    Returns (success, user-facing message).
    """
    emp = item.employee
    if not emp:
        return False, 'Employee record not found for this payslip.'

    to_email = _employee_inbox(emp)
    if not to_email:
        return False, f'No email address on file for {emp.full_name}.'

    if not brevo_configured():
        return False, 'Email is not configured. Set BREVO_API_KEY in your environment.'

    run = item.payroll_run
    if not run or run.status not in _PAYSLIP_SEND_RUN_STATUSES:
        return False, 'Payslips can only be emailed after payroll is approved.'

    ctx = build_payslip_context(item)
    period_label = ctx['period_date'].strftime('%B %Y')
    pdf_bytes = build_payslip_pdf(ctx)
    filename = payslip_pdf_filename(item)
    app_name = _app_name()
    company_name = escape(ctx.get('company_name') or company_name_from_run(run))
    emp_name = escape(emp.full_name)
    currency = escape(ctx['payslip_currency'])
    net_pay = escape(str(item.net_pay))

    subject = f'{app_name} — Payslip for {period_label}'
    html = f"""
    <p>Hello {emp_name},</p>
    <p>Please find your payslip for <strong>{escape(period_label)}</strong> attached.</p>
    <p>Net pay: <strong>{net_pay} {currency}</strong></p>
    <p style="color:#64748b;font-size:12px;">{company_name} · {escape(app_name)}</p>
    """
    text = (
        f'Hello {emp.full_name},\n\n'
        f'Your payslip for {period_label} is attached.\n'
        f'Net pay: {item.net_pay} {ctx["payslip_currency"]}\n\n'
        f'{ctx.get("company_name") or company_name_from_run(run)} · {app_name}'
    )

    ok = send_transactional_email(
        to_email,
        subject,
        html,
        text_content=text,
        attachments=[(filename, pdf_bytes)],
    )
    if ok:
        return True, f'Payslip emailed to {to_email}.'
    return False, f'Failed to send payslip to {to_email}. Please try again or contact support.'


def send_payslips_for_run(run_id: int, company_id: int) -> dict[str, int]:
    """Email payslips to all staff in a payroll run. Returns sent/skipped/failed counts."""
    items = (
        db.session.query(PayrollItem)
        .join(PayrollRun, PayrollItem.payroll_run_id == PayrollRun.id)
        .filter(
            PayrollItem.payroll_run_id == run_id,
            PayrollRun.company_id == company_id,
        )
        .options(
            joinedload(PayrollItem.payroll_run).joinedload(PayrollRun.company),
            joinedload(PayrollItem.employee).joinedload(Employee.branch),
            joinedload(PayrollItem.employee).joinedload(Employee.department),
            joinedload(PayrollItem.employee).joinedload(Employee.job_title),
            joinedload(PayrollItem.employee).joinedload(Employee.user),
        )
        .order_by(PayrollItem.employee_id)
        .all()
    )

    sent = 0
    skipped_no_email = 0
    failed = 0

    if not brevo_configured():
        logger.warning('Bulk payslip email skipped: Brevo not configured')
        return {'sent': 0, 'skipped_no_email': 0, 'failed': len(items)}

    for item in items:
        emp = item.employee
        if not emp or not _employee_inbox(emp):
            skipped_no_email += 1
            continue
        ok, _ = send_payslip_email(item)
        if ok:
            sent += 1
        else:
            failed += 1

    return {
        'sent': sent,
        'skipped_no_email': skipped_no_email,
        'failed': failed,
    }


def company_name_from_run(run: PayrollRun | None) -> str:
    if run and run.company and run.company.name:
        return run.company.name
    return 'Organization'
