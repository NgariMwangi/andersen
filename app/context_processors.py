"""Template context processors: permissions, config."""
from flask_login import current_user
from sqlalchemy.orm import joinedload


def register_template_filters(app):
    """Jinja filters used across templates."""
    from app.utils.formatters import format_currency, mask_bank_account

    @app.template_filter('mask_bank_account')
    def mask_bank_account_filter(number, visible=4):
        return mask_bank_account(number or '', visible=visible)

    @app.template_filter('fmt_money')
    def fmt_money(value, curr='KES'):
        return format_currency(value, curr)

    @app.template_filter('fmt_days')
    def fmt_days(value):
        """Show day counts without unnecessary decimals (21 not 21.00; 0.5 stays 0.5)."""
        if value is None:
            return ''
        try:
            f = float(value)
        except (TypeError, ValueError):
            return value
        if f != f:  # NaN
            return value
        if abs(f - round(f)) < 1e-9:
            return str(int(round(f)))
        return '%g' % f


def inject_permissions():
    """Expose current_user and has_permission to templates."""
    from app.utils.navigation import is_employee_self_service_user, user_home_endpoint

    def has_permission(code):
        if not current_user.is_authenticated:
            return False
        return current_user.has_permission(code)

    if current_user.is_authenticated:
        ess = is_employee_self_service_user()
        home_ep = user_home_endpoint()
    else:
        ess = False
        home_ep = 'auth.login'

    return {
        'current_user': current_user,
        'has_permission': has_permission,
        'is_employee_self_service': ess,
        'home_endpoint': home_ep,
    }


def inject_config():
    """Expose app config values needed in templates."""
    from flask import current_app
    return {
        'app_name': current_app.config.get('APP_NAME', 'Andersen'),
        'currency': current_app.config.get('DEFAULT_CURRENCY', 'KES'),
        'payroll_enabled': bool(current_app.config.get('ENABLE_PAYROLL', False)),
        'attendance_enabled': bool(current_app.config.get('ENABLE_ATTENDANCE', False)),
        'overtime_enabled': bool(current_app.config.get('ENABLE_OVERTIME', False)),
        'branches_enabled': bool(current_app.config.get('ENABLE_BRANCHES', False)),
        'salary_is_annual': (current_app.config.get('SALARY_BASIS') or 'annual').strip().lower() != 'monthly',
        'salary_basic_label': (
            'Annual basic salary'
            if (current_app.config.get('SALARY_BASIS') or 'annual').strip().lower() != 'monthly'
            else 'Monthly basic salary'
        ),
        'salary_basic_column_label': (
            'Basic (per annum)'
            if (current_app.config.get('SALARY_BASIS') or 'annual').strip().lower() != 'monthly'
            else 'Basic (per month)'
        ),
    }


def inject_page_nav():
    """Auto page section + title for the top bar breadcrumb."""
    from flask import request
    from app.utils.page_nav import resolve_page_nav
    return {'page_nav': resolve_page_nav(request.endpoint)}


def inject_today():
    """Today's date for the top bar."""
    from datetime import date

    d = date.today()
    return {
        'today_display': d.strftime('%A, %d %b %Y'),
        'today_short': d.strftime('%d %b %Y'),
        'today_iso': d.isoformat(),
    }


def inject_tenant_nav():
    """
    Company + branch for top bar: tenant from user.company; branch from linked employee.branch
    when present. If the user is not linked to an employee, show the company's first branch
    (by name) as the organizational default so the bar is still accurate.
    """
    empty = {
        'tenant_nav': {
            'company': None,
            'branch': None,
            'currency': None,
            'branch_is_personal': None,
        },
        'signed_in_context': None,
    }
    if not current_user.is_authenticated:
        return empty
    uid = getattr(current_user, 'id', None)
    if not uid:
        return empty
    from flask import current_app
    from app.extensions import db
    from app.models.user import User
    from app.models.employee import Employee
    from app.models.company import Branch
    from app.utils.currency import currency_for_branch, currency_for_employee

    u = (
        db.session.query(User)
        .options(
            joinedload(User.company),
            joinedload(User.employee).options(
                joinedload(Employee.branch),
                joinedload(Employee.department),
                joinedload(Employee.job_title),
            ),
        )
        .filter(User.id == uid)
        .first()
    )
    if not u:
        return empty

    company_name = (u.company.name if u.company else None) or None
    branch_label = None
    branch_is_personal = None
    app_def = current_app.config.get('DEFAULT_CURRENCY', 'KES')
    payroll_currency = app_def
    show_branch_nav = current_app.config.get('ENABLE_BRANCHES', False)
    if show_branch_nav:
        if u.employee and u.employee.branch:
            br = u.employee.branch
            branch_label = f'{br.name} · {br.country_code}'
            branch_is_personal = True
            payroll_currency = currency_for_employee(
                u.employee,
                app_default=app_def,
            )
        elif u.company_id:
            br = (
                db.session.query(Branch)
                .filter(Branch.company_id == u.company_id)
                .order_by(Branch.name)
                .first()
            )
            if br:
                branch_label = f'{br.name} · {br.country_code}'
                branch_is_personal = False
                payroll_currency = currency_for_branch(br, app_default=app_def)
    elif u.employee:
        payroll_currency = currency_for_employee(u.employee, app_default=app_def)

    signed_in_context = None
    if u.employee:
        emp = u.employee
        meta_parts = []
        if emp.job_title:
            meta_parts.append(emp.job_title.name)
        if emp.department:
            meta_parts.append(emp.department.name)
        first_initial = (emp.first_name or '?')[0].upper()
        last_initial = (emp.last_name or '')[0].upper() if emp.last_name else ''
        signed_in_context = {
            'employee_id': emp.id,
            'name': emp.full_name,
            'initials': f'{first_initial}{last_initial}' if last_initial else first_initial,
            'meta': ' · '.join(meta_parts) if meta_parts else None,
            'employee_number': emp.employee_number,
            'has_photo': bool(emp.photo_url),
        }

    return {
        'tenant_nav': {
            'company': company_name,
            'branch': branch_label,
            'currency': payroll_currency,
            'branch_is_personal': branch_is_personal,
        },
        'signed_in_context': signed_in_context,
    }


def inject_leave_approval_helpers():
    """Leave workflow labels and per-request approval stage for templates."""
    from app.services.leave_approval_service import (
        approval_stage_for_user,
        leave_status_label,
        supervisor_step_summary,
        user_is_line_manager,
    )

    def leave_approval_stage(leave_request):
        if not current_user.is_authenticated or leave_request is None:
            return None
        return approval_stage_for_user(current_user, leave_request)

    def is_line_manager():
        if not current_user.is_authenticated or not getattr(current_user, 'company_id', None):
            return False
        return user_is_line_manager(current_user, current_user.company_id)

    return {
        'leave_status_label': leave_status_label,
        'leave_approval_stage': leave_approval_stage,
        'is_line_manager': is_line_manager,
        'supervisor_step_summary': supervisor_step_summary,
    }


def inject_pending_approvals():
    """Global pending approvals counters for top-bar notifications."""
    empty = {
        'pending_approvals': {
            'leave': 0,
            'overtime': 0,
            'total': 0,
        }
    }
    if not current_user.is_authenticated or not getattr(current_user, 'company_id', None):
        return empty

    from flask import current_app
    from app.extensions import db
    from app.models.employee import Employee
    from app.models.leave import LeaveRequest
    from app.models.overtime import OvertimeRequest

    cid = current_user.company_id
    leave_pending = 0
    overtime_pending = 0

    from app.services.leave_approval_service import count_pending_leave_for_user

    if current_user.has_permission('approve_leave') or getattr(current_user, 'employee_id', None):
        leave_pending = count_pending_leave_for_user(current_user, cid)

    if current_app.config.get('ENABLE_OVERTIME', False):
        if current_user.has_permission('approve_overtime'):
            overtime_pending = (
                db.session.query(OvertimeRequest)
                .filter(OvertimeRequest.company_id == cid, OvertimeRequest.status == 'pending')
                .count()
            )
        elif current_user.employee_id:
            from app.services.employee_relations_service import subordinate_employee_ids

            team_ids = subordinate_employee_ids(current_user.employee_id, cid)
            if team_ids:
                overtime_pending = (
                    db.session.query(OvertimeRequest)
                    .filter(
                        OvertimeRequest.company_id == cid,
                        OvertimeRequest.status == 'pending',
                        OvertimeRequest.employee_id.in_(team_ids),
                    )
                    .count()
                )

    return {
        'pending_approvals': {
            'leave': leave_pending,
            'overtime': overtime_pending,
            'total': leave_pending + overtime_pending,
        }
    }


def inject_unread_messages():
    """Unread message thread count for sidebar badge."""
    if not current_user.is_authenticated or not getattr(current_user, 'company_id', None):
        return {'unread_message_threads': 0}
    from app.services.message_service import unread_message_count
    return {
        'unread_message_threads': unread_message_count(current_user.company_id, current_user.id),
    }
