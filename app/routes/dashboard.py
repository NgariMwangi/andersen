"""Dashboard and homepage."""
from datetime import date, timedelta

from flask import Blueprint, render_template, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from sqlalchemy import func
from app.extensions import db
from app.models.employee import Employee
from app.models.leave import LeaveRequest
from app.models.overtime import OvertimeRequest
from app.models.payroll import PayrollRun, PayrollItem
from app.models.consultant import ConsultantPayrollItem
from app.utils.tenant import require_company_id
from app.utils.navigation import is_employee_self_service_user, redirect_to_user_home

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
@login_required
def index():
    """Main dashboard - show widgets based on role."""
    if is_employee_self_service_user():
        return redirect_to_user_home()
    today = date.today()
    if current_user.company_id is None:
        if current_user.is_superuser:
            flash(
                'Your account is not linked to a company yet. Create or select a company first.',
                'warning',
            )
            return redirect(url_for('settings.companies_new'))
        flash('Your account is not linked to a company. Contact your administrator.', 'danger')
        return redirect(url_for('auth.logout'))
    cid = require_company_id()
    # Headcount
    total_employees = (
        db.session.query(Employee)
        .filter(Employee.status == 'active', Employee.company_id == cid)
        .count()
    )
    # Pending leave (supervisor queue + HR queue)
    pending_leave = 0
    if current_user.has_permission('approve_leave') or getattr(current_user, 'employee_id', None):
        from app.services.leave_approval_service import count_pending_leave_for_user

        pending_leave = count_pending_leave_for_user(current_user, cid)
    pending_overtime = 0
    if current_app.config.get('ENABLE_OVERTIME', False):
        if current_user.has_permission('approve_overtime'):
            pending_overtime = (
                db.session.query(OvertimeRequest)
                .filter(
                    OvertimeRequest.company_id == cid,
                    OvertimeRequest.status == 'pending',
                )
                .count()
            )
        elif current_user.employee_id:
            from app.services.employee_relations_service import subordinate_employee_ids

            team_ids = subordinate_employee_ids(current_user.employee_id, cid)
            if team_ids:
                pending_overtime = (
                    db.session.query(OvertimeRequest)
                    .filter(
                        OvertimeRequest.company_id == cid,
                        OvertimeRequest.status == 'pending',
                        OvertimeRequest.employee_id.in_(team_ids),
                    )
                    .count()
                )

    probation_alert_window_days = 14
    probation_nearing = []
    probation_arrived = []
    contract_alert_window_days = 60
    contract_nearing = []
    contract_arrived = []
    if current_user.has_permission('edit_employees'):
        probation_rows = (
            db.session.query(Employee)
            .filter(
                Employee.company_id == cid,
                Employee.status == 'active',
                Employee.probation_end_date.isnot(None),
            )
            .all()
        )
        for emp in probation_rows:
            end_date = emp.probation_end_date
            days_to_end = (end_date - today).days
            if 1 <= days_to_end <= probation_alert_window_days:
                probation_nearing.append(
                    {
                        'employee': emp,
                        'probation_end_date': end_date,
                        'days_to_end': days_to_end,
                    }
                )
            elif days_to_end <= 0:
                probation_arrived.append(
                    {
                        'employee': emp,
                        'probation_end_date': end_date,
                        'days_to_end': days_to_end,
                    }
                )
        probation_nearing.sort(key=lambda item: (item['days_to_end'], item['employee'].full_name.lower()))
        probation_arrived.sort(key=lambda item: (item['days_to_end'], item['employee'].full_name.lower()))

        contract_rows = (
            db.session.query(Employee)
            .filter(
                Employee.company_id == cid,
                Employee.status == 'active',
                Employee.employment_type == 'contract',
                Employee.contract_end_date.isnot(None),
            )
            .all()
        )
        for emp in contract_rows:
            end_date = emp.contract_end_date
            days_to_end = (end_date - today).days
            if 1 <= days_to_end <= contract_alert_window_days:
                contract_nearing.append(
                    {
                        'employee': emp,
                        'contract_end_date': end_date,
                        'days_to_end': days_to_end,
                    }
                )
            elif days_to_end <= 0:
                contract_arrived.append(
                    {
                        'employee': emp,
                        'contract_end_date': end_date,
                        'days_to_end': days_to_end,
                    }
                )
        contract_nearing.sort(key=lambda item: (item['days_to_end'], item['employee'].full_name.lower()))
        contract_arrived.sort(key=lambda item: (item['days_to_end'], item['employee'].full_name.lower()))

    # Upcoming birthdays (admins / HR users with employee visibility)
    birthday_window_days = 14
    upcoming_birthdays = []
    if current_user.has_permission('view_employees'):
        employees_with_birthdays = (
            db.session.query(Employee)
            .filter(
                Employee.status == 'active',
                Employee.company_id == cid,
                Employee.date_of_birth.isnot(None),
            )
            .all()
        )
        birthday_rows = []
        for emp in employees_with_birthdays:
            dob = emp.date_of_birth
            try:
                next_birthday = date(today.year, dob.month, dob.day)
            except ValueError:
                # Handle Feb 29 birthdays on non-leap years.
                next_birthday = date(today.year, 3, 1)
            if next_birthday < today:
                try:
                    next_birthday = date(today.year + 1, dob.month, dob.day)
                except ValueError:
                    next_birthday = date(today.year + 1, 3, 1)
            birthday_rows.append(
                {
                    'employee': emp,
                    'birthday': next_birthday,
                    'weekday': next_birthday.strftime('%A'),
                    'days_away': (next_birthday - today).days,
                    'coming_weekday_label': (
                        f"This coming {next_birthday.strftime('%A')}"
                        if 2 <= (next_birthday - today).days <= 6
                        else None
                    ),
                    'turning_age': next_birthday.year - dob.year,
                }
            )
        birthday_rows = [item for item in birthday_rows if item['days_away'] <= birthday_window_days]
        birthday_rows.sort(key=lambda item: (item['days_away'], item['employee'].full_name.lower()))
        upcoming_birthdays = birthday_rows
    # Recent payroll (optional module)
    latest_payroll = None
    payroll_charts = []
    executive_summary = None
    payroll_enabled = bool(current_app.config.get('ENABLE_PAYROLL', False))

    if payroll_enabled:
        latest_payroll = (
            db.session.query(PayrollRun)
            .filter(PayrollRun.company_id == cid)
            .order_by(PayrollRun.pay_year.desc(), PayrollRun.pay_month.desc())
            .first()
        )

    if current_user.has_permission('view_reports') or (
        payroll_enabled and current_user.has_permission('approve_payroll')
    ):
        from app.utils.currency import currency_for_country

        start_of_month = date(today.year, today.month, 1)
        latest_run = (
            db.session.query(PayrollRun)
            .filter(PayrollRun.company_id == cid)
            .order_by(PayrollRun.pay_year.desc(), PayrollRun.pay_month.desc(), PayrollRun.id.desc())
            .first()
        )
        payroll_by_branch = []
        payroll_period = None
        if payroll_enabled and latest_run:
            payroll_period = f"{latest_run.pay_month}/{latest_run.pay_year}"
            runs_for_period = (
                db.session.query(PayrollRun)
                .filter(
                    PayrollRun.company_id == cid,
                    PayrollRun.pay_year == latest_run.pay_year,
                    PayrollRun.pay_month == latest_run.pay_month,
                )
                .all()
            )
            for run in runs_for_period:
                staff_net, staff_count = (
                    db.session.query(
                        func.coalesce(func.sum(PayrollItem.net_pay), 0),
                        func.count(PayrollItem.id),
                    )
                    .filter(PayrollItem.payroll_run_id == run.id)
                    .one()
                )
                consultant_net, consultant_count = (
                    db.session.query(
                        func.coalesce(func.sum(ConsultantPayrollItem.net_pay), 0),
                        func.count(ConsultantPayrollItem.id),
                    )
                    .filter(ConsultantPayrollItem.payroll_run_id == run.id)
                    .one()
                )
                payroll_by_branch.append({
                    'country_code': run.country_code or 'KE',
                    'currency': currency_for_country(run.country_code),
                    'net': staff_net + consultant_net,
                    'staff': staff_count,
                    'consultants': consultant_count,
                    'status': run.status,
                })
        executive_summary = {
            'active_employees': total_employees,
            'pending_leave': pending_leave,
            'pending_overtime': pending_overtime,
            'new_hires_this_month': db.session.query(Employee).filter(
                Employee.company_id == cid,
                Employee.hire_date >= start_of_month,
            ).count(),
            'exits_this_month': db.session.query(Employee).filter(
                Employee.company_id == cid,
                Employee.termination_date.isnot(None),
                Employee.termination_date >= start_of_month,
            ).count(),
            'payroll_period': payroll_period,
            'payroll_by_branch': payroll_by_branch,
        }
    if payroll_enabled and executive_summary:
        from app.utils.currency import currency_for_country
        import json as _json
        from collections import OrderedDict

        trend_runs = (
            db.session.query(
                PayrollRun.pay_year,
                PayrollRun.pay_month,
                PayrollRun.country_code,
                func.coalesce(func.sum(PayrollItem.net_pay), 0).label('staff_net'),
            )
            .outerjoin(PayrollItem, PayrollItem.payroll_run_id == PayrollRun.id)
            .filter(PayrollRun.company_id == cid)
            .group_by(PayrollRun.pay_year, PayrollRun.pay_month, PayrollRun.country_code)
            .order_by(PayrollRun.pay_year, PayrollRun.pay_month)
            .all()
        )
        trend_consultant = (
            db.session.query(
                PayrollRun.pay_year,
                PayrollRun.pay_month,
                PayrollRun.country_code,
                func.coalesce(func.sum(ConsultantPayrollItem.net_pay), 0).label('con_net'),
            )
            .outerjoin(ConsultantPayrollItem, ConsultantPayrollItem.payroll_run_id == PayrollRun.id)
            .filter(PayrollRun.company_id == cid)
            .group_by(PayrollRun.pay_year, PayrollRun.pay_month, PayrollRun.country_code)
            .order_by(PayrollRun.pay_year, PayrollRun.pay_month)
            .all()
        )
        con_lookup = {}
        for r in trend_consultant:
            con_lookup[(r.pay_year, r.pay_month, r.country_code)] = float(r.con_net or 0)

        all_countries = sorted({r.country_code or 'KE' for r in trend_runs})
        colors = ['#0d6efd', '#198754', '#dc3545', '#ffc107', '#6f42c1', '#20c997']

        for i, cc in enumerate(all_countries):
            months_data = OrderedDict()
            for r in trend_runs:
                if (r.country_code or 'KE') != cc:
                    continue
                label = f"{r.pay_month:02d}/{r.pay_year}"
                con_net = con_lookup.get((r.pay_year, r.pay_month, r.country_code), 0)
                months_data[label] = float(r.staff_net or 0) + con_net

            chart_labels = list(months_data.keys())[-12:]
            chart_data = [months_data.get(lbl, 0) for lbl in chart_labels]
            currency = currency_for_country(cc)
            payroll_charts.append({
                'id': f'payrollChart_{cc}',
                'title': f'{cc} — {currency}',
                'data_json': _json.dumps({
                    'labels': chart_labels,
                    'datasets': [{
                        'label': f'Net Pay ({currency})',
                        'data': chart_data,
                        'borderColor': colors[i % len(colors)],
                        'backgroundColor': colors[i % len(colors)] + '33',
                        'tension': 0.3,
                        'fill': True,
                    }]
                }),
            })

    return render_template(
        'dashboard/index.html',
        total_employees=total_employees,
        pending_leave=pending_leave,
        pending_overtime=pending_overtime,
        latest_payroll=latest_payroll,
        executive_summary=executive_summary,
        payroll_charts=payroll_charts,
        probation_alert_window_days=probation_alert_window_days,
        probation_nearing=probation_nearing,
        probation_arrived=probation_arrived,
        contract_alert_window_days=contract_alert_window_days,
        contract_nearing=contract_nearing,
        contract_arrived=contract_arrived,
        upcoming_birthdays=upcoming_birthdays,
        birthday_window_days=birthday_window_days,
    )
