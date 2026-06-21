"""Payroll processing and history."""
from decimal import Decimal
from io import BytesIO

from flask import Blueprint, abort, render_template, redirect, url_for, flash, request, current_app, send_file
from flask_login import login_required, current_user
from app.extensions import db
from app.models.payroll import (
    PayrollRun,
    PayrollItem,
    EmployeeSalary,
    EmployeeAllowance,
    PayrollStatutoryRemittance,
    PayrollRunManualDeduction,
    PayrollRunExclusion,
)
from app.models.employee import Employee as EmpModel
from app.models.company import Branch
from app.models.overtime import OvertimeRequest
from app.models.benefit import EmployeeBenefit
from app.forms.payroll_forms import PayrollRunForm, PayrollApproveForm
from app.services.payroll_engine import (
    calculate_employee_payroll,
    pro_rata_calendar_days_or_none,
    pro_rata_factor,
)
from app.services.deduction_service import get_manual_deduction_line_items_for_run
from app.models.consultant import Consultant, ConsultantPayrollItem
from app.services.consultant_payroll_run import (
    consultant_eligibility_for_run,
    calculate_all_consultants_for_run,
    recalculate_single_consultant,
    save_consultant_exclusions,
)
from app.services.statutory_remittance_service import (
    delete_statutory_remitances_for_run,
    replace_statutory_remitances_for_run,
    institution_totals_for_run,
)
from app.services.payslip_pdf_service import build_payslip_context, build_payslip_pdf, payslip_pdf_filename
from app.services.payslip_email_service import send_payslip_email, send_payslips_for_run
from app.services.audit_service import log_update, log_create, model_to_audit_dict
from app.decorators.permissions import permission_required
from app.utils.tenant import require_company_id
from app.utils.currency import currency_for_country
from datetime import date
from sqlalchemy import update
from sqlalchemy import extract
from sqlalchemy.orm import joinedload

payroll_bp = Blueprint('payroll', __name__)


def _july_gross_for_uganda_lst(
    employee_id: int,
    company_id: int,
    pay_year: int,
    pay_month: int,
) -> Decimal | None:
    """July gross used for LST annual band (Aug–Oct instalments). None if not found."""
    if pay_month == 7:
        return None
    row = (
        db.session.query(PayrollItem.gross_pay)
        .join(PayrollRun, PayrollItem.payroll_run_id == PayrollRun.id)
        .filter(
            PayrollItem.employee_id == employee_id,
            PayrollRun.company_id == company_id,
            PayrollRun.pay_year == pay_year,
            PayrollRun.pay_month == 7,
            PayrollRun.country_code == 'UG',
        )
        .order_by(PayrollItem.id.desc())
        .first()
    )
    if row and row[0] is not None:
        return Decimal(str(row[0]))
    return None


def _payroll_calc_kwargs(run_obj, run_cc: str, employee_id: int) -> dict:
    if run_cc != 'UG':
        return {}
    return {
        'pay_month': run_obj.pay_month,
        'pay_year': run_obj.pay_year,
        'july_gross_for_lst': _july_gross_for_uganda_lst(
            employee_id,
            run_obj.company_id,
            run_obj.pay_year,
            run_obj.pay_month,
        ),
    }

_EMPLOYEE_PAYSLIP_RUN_STATUSES = ('approved', 'finance_reviewed', 'paid')


def _cc(raw) -> str:
    return (raw or 'KE').strip().upper()[:2]


def _approved_overtime_for_employee(
    company_id: int,
    employee_id: int,
    pay_month: int,
    pay_year: int,
    payroll_run_id: int,
):
    """Approved OT for this pay month, not applied elsewhere or already on this draft run."""
    return (
        db.session.query(OvertimeRequest)
        .filter(
            OvertimeRequest.company_id == company_id,
            OvertimeRequest.employee_id == employee_id,
            OvertimeRequest.for_pay_month == pay_month,
            OvertimeRequest.for_pay_year == pay_year,
            OvertimeRequest.status == 'approved',
            db.or_(
                OvertimeRequest.applied_to_payroll_run_id.is_(None),
                OvertimeRequest.applied_to_payroll_run_id == payroll_run_id,
            ),
        )
        .all()
    )


@payroll_bp.route('/')
@login_required
@permission_required('view_payroll')
def index():
    cid = require_company_id()
    country_rows = (
        db.session.query(Branch.country_code)
        .filter(Branch.company_id == cid, Branch.country_code.isnot(None))
        .distinct()
        .order_by(Branch.country_code)
        .all()
    )
    countries_nav = [_cc(cc) for (cc,) in country_rows if cc] or ['KE']
    selected_country = _cc(request.args.get('country_code') or countries_nav[0])
    if selected_country not in countries_nav:
        countries_nav.append(selected_country)
        countries_nav = sorted(set(countries_nav))
    runs = (
        db.session.query(PayrollRun)
        .filter(PayrollRun.company_id == cid, PayrollRun.country_code == selected_country)
        .order_by(PayrollRun.pay_year.desc(), PayrollRun.pay_month.desc())
        .all()
    )
    return render_template(
        'payroll/history.html',
        runs=runs,
        countries_nav=countries_nav,
        selected_country=selected_country,
    )


@payroll_bp.route('/run', methods=['GET', 'POST'])
@login_required
@permission_required('process_payroll')
def run():
    form = PayrollRunForm()
    cid = require_company_id()
    country_rows = (
        db.session.query(Branch.country_code)
        .filter(Branch.company_id == cid, Branch.country_code.isnot(None))
        .distinct()
        .order_by(Branch.country_code)
        .all()
    )
    countries = [(_cc(cc), _cc(cc)) for (cc,) in country_rows if cc]
    if not countries:
        countries = [('KE', 'KE')]
    preferred = _cc(request.args.get('country_code') or countries[0][0])
    if request.method == 'GET':
        form.country_code.data = preferred
        form.pay_year.data = date.today().year
    if form.validate_on_submit():
        cc = _cc(form.country_code.data)
        existing = db.session.query(PayrollRun).filter(
            PayrollRun.company_id == cid,
            PayrollRun.country_code == cc,
            PayrollRun.pay_month == form.pay_month.data,
            PayrollRun.pay_year == form.pay_year.data,
        ).first()
        if existing:
            flash(f'Payroll for {cc} in this month already exists.', 'warning')
            return render_template('payroll/run_payroll.html', form=form, countries=countries)
        run_obj = PayrollRun(
            company_id=cid,
            country_code=cc,
            pay_month=form.pay_month.data,
            pay_year=form.pay_year.data,
            status='draft',
            notes=form.notes.data,
        )
        db.session.add(run_obj)
        db.session.commit()
        flash(f'Payroll run ({cc}) created. Add employees and calculate.', 'success')
        return redirect(url_for('payroll.run_calculate', id=run_obj.id))
    return render_template('payroll/run_payroll.html', form=form, countries=countries)


@payroll_bp.route('/run/<int:id>/calculate', methods=['GET', 'POST'])
@login_required
@permission_required('process_payroll')
def run_calculate(id):
    run_obj = db.session.get(PayrollRun, id)
    if not run_obj or run_obj.status != 'draft' or run_obj.company_id != require_company_id():
        from flask import abort
        abort(404)
    pay_date = date(run_obj.pay_year, run_obj.pay_month, 1)
    from calendar import monthrange
    _, month_last_day = monthrange(run_obj.pay_year, run_obj.pay_month)
    period_start = date(run_obj.pay_year, run_obj.pay_month, 1)
    period_end = date(run_obj.pay_year, run_obj.pay_month, month_last_day)
    run_cc = _cc(run_obj.country_code)
    run_currency = currency_for_country(run_cc)
    # Employees who worked any day in this month (incl. terminated mid-month), with salary/benefits.
    employees = (
        db.session.query(EmpModel)
        .options(joinedload(EmpModel.branch))
        .join(Branch, EmpModel.branch_id == Branch.id)
        .filter(
            EmpModel.company_id == run_obj.company_id,
            Branch.country_code == run_cc,
            EmpModel.hire_date <= period_end,
            db.or_(
                EmpModel.termination_date.is_(None),
                EmpModel.termination_date >= period_start,
            ),
        )
        .all()
    )
    eligible_employee_ids = set()
    missing_salary = []
    for emp in employees:
        salary = db.session.query(EmployeeSalary).filter(
            EmployeeSalary.employee_id == emp.id,
            EmployeeSalary.effective_from <= period_end,
            (EmployeeSalary.effective_to.is_(None)) | (EmployeeSalary.effective_to >= period_start),
        ).order_by(EmployeeSalary.effective_from.desc(), EmployeeSalary.id.desc()).first()
        if salary:
            eligible_employee_ids.add(emp.id)
        else:
            has_benefits = db.session.query(EmployeeBenefit).filter(
                EmployeeBenefit.employee_id == emp.id,
                EmployeeBenefit.is_active.is_(True),
                db.or_(
                    db.and_(
                        EmployeeBenefit.frequency == 'one_off',
                        EmployeeBenefit.payroll_year == run_obj.pay_year,
                        EmployeeBenefit.payroll_month == run_obj.pay_month,
                    ),
                    db.and_(
                        EmployeeBenefit.frequency == 'monthly',
                        EmployeeBenefit.payroll_year.isnot(None),
                        EmployeeBenefit.payroll_month.isnot(None),
                        db.or_(
                            EmployeeBenefit.payroll_year < run_obj.pay_year,
                            db.and_(
                                EmployeeBenefit.payroll_year == run_obj.pay_year,
                                EmployeeBenefit.payroll_month <= run_obj.pay_month,
                            ),
                        ),
                    ),
                ),
            ).first()
            if has_benefits:
                eligible_employee_ids.add(emp.id)
            else:
                missing_salary.append(emp)
    eligible_count = len(eligible_employee_ids)
    missing_salary_ids = {e.id for e in missing_salary}
    excluded_rows = (
        db.session.query(PayrollRunExclusion)
        .filter(PayrollRunExclusion.payroll_run_id == run_obj.id)
        .all()
    )
    excluded_employee_ids = {row.employee_id for row in excluded_rows}
    excluded_count = len(excluded_employee_ids & eligible_employee_ids)
    included_count = max(eligible_count - excluded_count, 0)

    consultants, consultant_eligible_ids, missing_compensation, excluded_consultant_ids_set = (
        consultant_eligibility_for_run(run_obj, period_start, period_end)
    )
    consultant_eligible_count = len(consultant_eligible_ids)
    missing_compensation_ids = {c.id for c in missing_compensation}
    consultant_excluded_count = len(excluded_consultant_ids_set & consultant_eligible_ids)
    consultant_included_count = max(consultant_eligible_count - consultant_excluded_count, 0)

    def _recalculate_single_employee(emp_id: int):
        """Recalculate payroll lines for one employee in this run. Returns (ok, error, calc_dict)."""
        emp = (
            db.session.query(EmpModel)
            .options(joinedload(EmpModel.branch))
            .filter(EmpModel.id == emp_id, EmpModel.company_id == run_obj.company_id)
            .first()
        )
        if not emp:
            return False, 'Employee not found in this payroll country scope.', None

        salary = db.session.query(EmployeeSalary).filter(
            EmployeeSalary.employee_id == emp.id,
            EmployeeSalary.effective_from <= period_end,
            (EmployeeSalary.effective_to.is_(None)) | (EmployeeSalary.effective_to >= period_start),
        ).order_by(EmployeeSalary.effective_from.desc(), EmployeeSalary.id.desc()).first()

        ot_rows = _approved_overtime_for_employee(
            run_obj.company_id,
            emp.id,
            run_obj.pay_month,
            run_obj.pay_year,
            run_obj.id,
        )

        # Release this employee's overtime rows tied to this run and remove existing payroll line.
        db.session.execute(
            update(OvertimeRequest)
            .where(
                OvertimeRequest.applied_to_payroll_run_id == run_obj.id,
                OvertimeRequest.employee_id == emp.id,
            )
            .values(applied_to_payroll_run_id=None)
        )
        db.session.query(PayrollItem).filter(
            PayrollItem.payroll_run_id == run_obj.id,
            PayrollItem.employee_id == emp.id,
        ).delete()
        db.session.flush()

        hire_or_start = emp.hire_date
        if salary and salary.effective_from and (not hire_or_start or salary.effective_from > hire_or_start):
            hire_or_start = salary.effective_from
        end_or_termination = emp.termination_date
        if salary and salary.effective_to and (not end_or_termination or salary.effective_to < end_or_termination):
            end_or_termination = salary.effective_to
        factor = pro_rata_factor(hire_or_start, end_or_termination, run_obj.pay_month, run_obj.pay_year)
        cal_days = pro_rata_calendar_days_or_none(
            hire_or_start, end_or_termination, run_obj.pay_month, run_obj.pay_year
        )

        emp_allowances = db.session.query(EmployeeAllowance).filter(
            EmployeeAllowance.employee_id == emp.id,
            EmployeeAllowance.effective_from <= pay_date,
            (EmployeeAllowance.effective_to.is_(None)) | (EmployeeAllowance.effective_to >= pay_date),
        ).all()
        emp_benefits = db.session.query(EmployeeBenefit).filter(
            EmployeeBenefit.employee_id == emp.id,
            EmployeeBenefit.is_active.is_(True),
            db.or_(
                db.and_(
                    EmployeeBenefit.frequency == 'one_off',
                    EmployeeBenefit.payroll_year == run_obj.pay_year,
                    EmployeeBenefit.payroll_month == run_obj.pay_month,
                ),
                db.and_(
                    EmployeeBenefit.frequency == 'monthly',
                    EmployeeBenefit.payroll_year.isnot(None),
                    EmployeeBenefit.payroll_month.isnot(None),
                    db.or_(
                        EmployeeBenefit.payroll_year < run_obj.pay_year,
                        db.and_(
                            EmployeeBenefit.payroll_year == run_obj.pay_year,
                            EmployeeBenefit.payroll_month <= run_obj.pay_month,
                        ),
                    ),
                ),
                db.and_(
                    db.or_(EmployeeBenefit.frequency.is_(None), EmployeeBenefit.frequency == ''),
                    EmployeeBenefit.payroll_year.is_(None),
                    EmployeeBenefit.payroll_month.is_(None),
                    EmployeeBenefit.effective_date.isnot(None),
                    extract('year', EmployeeBenefit.effective_date) == run_obj.pay_year,
                    extract('month', EmployeeBenefit.effective_date) == run_obj.pay_month,
                ),
            ),
        ).all()
        manual_lines = get_manual_deduction_line_items_for_run(run_obj.id, emp.id)
        overtime_days = sum((Decimal(str(r.days)) for r in ot_rows), start=Decimal('0'))

        basic = salary.basic_salary if salary else 0
        pension_pct = salary.pension_employee_percent if salary else 0
        pension_fixed = salary.pension_employee_fixed_amount if salary else 0

        if not salary and not emp_benefits:
            return False, 'Employee has no salary or benefits for this period.', None

        if emp_allowances or emp_benefits:
            allowance_breakdown = []
            if emp_allowances:
                allowance_breakdown.extend([
                    {
                        'amount': ea.amount,
                        'is_taxable': ea.allowance.is_taxable,
                        'is_pensionable': ea.allowance.is_pensionable,
                        'prorate': True,
                        'code': ea.allowance.code,
                        'name': ea.allowance.name,
                    }
                    for ea in emp_allowances
                ])
            elif salary:
                allowance_breakdown.extend([
                    {'amount': salary.house_allowance, 'is_taxable': True, 'is_pensionable': True, 'prorate': True, 'code': 'HOUSE', 'name': 'House Allowance'},
                    {'amount': salary.transport_allowance, 'is_taxable': True, 'is_pensionable': False, 'prorate': True, 'code': 'TRANSPORT', 'name': 'Transport Allowance'},
                    {'amount': salary.meal_allowance, 'is_taxable': True, 'is_pensionable': False, 'prorate': True, 'code': 'MEAL', 'name': 'Meal Allowance'},
                    {'amount': salary.other_allowances, 'is_taxable': True, 'is_pensionable': False, 'prorate': True, 'code': 'OTHER_ALLOW', 'name': 'Other Allowances'},
                ])
            allowance_breakdown.extend(
                {
                    'amount': b.amount,
                    'is_taxable': bool(getattr(b, 'is_taxable', True)),
                    'is_pensionable': bool(getattr(b, 'is_pensionable', True)),
                    'prorate': False,
                    'code': f'BEN-{b.id}',
                    'name': b.title or 'Benefit',
                }
                for b in emp_benefits
            )
            calc = calculate_employee_payroll(
                basic_salary=basic,
                pension_employee_percent=pension_pct,
                pension_employee_fixed_amount=pension_fixed,
                pay_date=pay_date,
                pro_rata_factor=factor,
                pro_rata_calendar_days=cal_days,
                allowance_breakdown=allowance_breakdown,
                employee_id=emp.id,
                manual_deduction_lines=manual_lines,
                statutory_company_id=emp.company_id,
                statutory_country_code=run_cc,
                overtime_days=overtime_days,
                **_payroll_calc_kwargs(run_obj, run_cc, emp.id),
            )
        else:
            calc = calculate_employee_payroll(
                basic_salary=basic,
                house_allowance=salary.house_allowance if salary else 0,
                transport_allowance=salary.transport_allowance if salary else 0,
                meal_allowance=salary.meal_allowance if salary else 0,
                other_allowances=salary.other_allowances if salary else 0,
                pension_employee_percent=pension_pct,
                pension_employee_fixed_amount=pension_fixed,
                pay_date=pay_date,
                pro_rata_factor=factor,
                pro_rata_calendar_days=cal_days,
                employee_id=emp.id,
                manual_deduction_lines=manual_lines,
                statutory_company_id=emp.company_id,
                statutory_country_code=run_cc,
                overtime_days=overtime_days,
                **_payroll_calc_kwargs(run_obj, run_cc, emp.id),
            )
        for ot_r in ot_rows:
            ot_r.applied_to_payroll_run_id = run_obj.id
        db.session.add(
            PayrollItem(
                payroll_run_id=run_obj.id,
                employee_id=emp.id,
                gross_pay=calc['gross_pay'],
                taxable_pay=calc['taxable_pay'],
                paye=calc['paye'],
                nssf_employee=calc['nssf_employee'],
                nssf_employer=calc['nssf_employer'],
                shif=calc['shif'],
                housing_levy=calc['housing_levy'],
                other_deductions=calc['other_deductions'],
                net_pay=calc['net_pay'],
                earnings_breakdown=calc['earnings_breakdown'],
                deductions_breakdown=calc['deductions_breakdown'],
                is_pro_rata=(cal_days is not None or factor < Decimal('1')),
            )
        )
        return True, None, calc

    if request.method == 'POST' and request.form.get('action') == 'save_exclusions':
        selected = set(request.form.getlist('excluded_employee_ids', type=int))
        selected = {eid for eid in selected if eid in eligible_employee_ids}
        employee_id_scope = {e.id for e in employees}
        table_scope = set(request.form.getlist('exclusion_table_employee_ids', type=int)) & employee_id_scope
        if table_scope:
            new_excluded = set()
            for eid in eligible_employee_ids:
                if eid in table_scope:
                    if eid in selected:
                        new_excluded.add(eid)
                elif eid in excluded_employee_ids:
                    new_excluded.add(eid)
        else:
            new_excluded = selected
        db.session.query(PayrollRunExclusion).filter(
            PayrollRunExclusion.payroll_run_id == run_obj.id
        ).delete()
        for eid in sorted(new_excluded):
            db.session.add(PayrollRunExclusion(payroll_run_id=run_obj.id, employee_id=eid))
        db.session.commit()
        flash(f'Payroll exclusions updated ({len(new_excluded)} employee(s) excluded).', 'success')
        q_save = (request.form.get('q') or '').strip()
        if q_save:
            return redirect(url_for('payroll.run_calculate', id=run_obj.id, q=q_save))
        return redirect(url_for('payroll.run_calculate', id=run_obj.id))

    if request.method == 'POST' and request.form.get('action') == 'save_consultant_exclusions':
        selected = set(request.form.getlist('excluded_consultant_ids', type=int))
        selected = {cid for cid in selected if cid in consultant_eligible_ids}
        consultant_id_scope = {c.id for c in consultants}
        table_scope = set(request.form.getlist('exclusion_table_consultant_ids', type=int)) & consultant_id_scope
        if table_scope:
            new_excluded = save_consultant_exclusions(
                run_obj.id,
                consultant_eligible_ids,
                selected,
                table_scope=table_scope,
                previous_excluded=excluded_consultant_ids_set,
            )
        else:
            new_excluded = save_consultant_exclusions(run_obj.id, consultant_eligible_ids, selected)
        db.session.commit()
        flash(f'Consultant exclusions updated ({new_excluded} consultant(s) excluded).', 'success')
        q_save = (request.form.get('q') or '').strip()
        if q_save:
            return redirect(url_for('payroll.run_calculate', id=run_obj.id, q=q_save))
        return redirect(url_for('payroll.run_calculate', id=run_obj.id))

    if request.method == 'POST' and request.form.get('action') == 'calculate':
        excluded_employee_ids = {
            row.employee_id
            for row in db.session.query(PayrollRunExclusion)
            .filter(PayrollRunExclusion.payroll_run_id == run_obj.id)
            .all()
        }
        # Release overtime rows tied to this draft run, then replace line items
        db.session.execute(
            update(OvertimeRequest)
            .where(OvertimeRequest.applied_to_payroll_run_id == run_obj.id)
            .values(applied_to_payroll_run_id=None)
        )
        db.session.query(PayrollItem).filter(PayrollItem.payroll_run_id == run_obj.id).delete()
        db.session.commit()
        for emp in employees:
            if emp.id in excluded_employee_ids:
                continue
            if emp.id not in eligible_employee_ids:
                continue
            salary = db.session.query(EmployeeSalary).filter(
                EmployeeSalary.employee_id == emp.id,
                EmployeeSalary.effective_from <= period_end,
                (EmployeeSalary.effective_to.is_(None)) | (EmployeeSalary.effective_to >= period_start),
            ).order_by(EmployeeSalary.effective_from.desc(), EmployeeSalary.id.desc()).first()
            # Pro-rate using employee lifecycle and salary window overlap.
            hire_or_start = emp.hire_date
            if salary and salary.effective_from and (not hire_or_start or salary.effective_from > hire_or_start):
                hire_or_start = salary.effective_from
            end_or_termination = emp.termination_date
            if salary and salary.effective_to and (not end_or_termination or salary.effective_to < end_or_termination):
                end_or_termination = salary.effective_to
            factor = pro_rata_factor(hire_or_start, end_or_termination, run_obj.pay_month, run_obj.pay_year)
            cal_days = pro_rata_calendar_days_or_none(
                hire_or_start, end_or_termination, run_obj.pay_month, run_obj.pay_year
            )
            # Use EmployeeAllowance table if any assignments exist for this pay date
            emp_allowances = db.session.query(EmployeeAllowance).filter(
                EmployeeAllowance.employee_id == emp.id,
                EmployeeAllowance.effective_from <= pay_date,
                (EmployeeAllowance.effective_to.is_(None)) | (EmployeeAllowance.effective_to >= pay_date),
            ).all()
            emp_benefits = db.session.query(EmployeeBenefit).filter(
                EmployeeBenefit.employee_id == emp.id,
                EmployeeBenefit.is_active.is_(True),
                db.or_(
                    db.and_(
                        EmployeeBenefit.frequency == 'one_off',
                        EmployeeBenefit.payroll_year == run_obj.pay_year,
                        EmployeeBenefit.payroll_month == run_obj.pay_month,
                    ),
                    db.and_(
                        EmployeeBenefit.frequency == 'monthly',
                        EmployeeBenefit.payroll_year.isnot(None),
                        EmployeeBenefit.payroll_month.isnot(None),
                        db.or_(
                            EmployeeBenefit.payroll_year < run_obj.pay_year,
                            db.and_(
                                EmployeeBenefit.payroll_year == run_obj.pay_year,
                                EmployeeBenefit.payroll_month <= run_obj.pay_month,
                            ),
                        ),
                    ),
                    db.and_(
                        db.or_(EmployeeBenefit.frequency.is_(None), EmployeeBenefit.frequency == ''),
                        EmployeeBenefit.payroll_year.is_(None),
                        EmployeeBenefit.payroll_month.is_(None),
                        EmployeeBenefit.effective_date.isnot(None),
                        extract('year', EmployeeBenefit.effective_date) == run_obj.pay_year,
                        extract('month', EmployeeBenefit.effective_date) == run_obj.pay_month,
                    ),
                ),
            ).all()
            manual_lines = get_manual_deduction_line_items_for_run(run_obj.id, emp.id)
            ot_rows = _approved_overtime_for_employee(
                run_obj.company_id,
                emp.id,
                run_obj.pay_month,
                run_obj.pay_year,
                run_obj.id,
            )
            overtime_days = sum((Decimal(str(r.days)) for r in ot_rows), start=Decimal('0'))
            basic = salary.basic_salary if salary else 0
            pension_pct = salary.pension_employee_percent if salary else 0
            pension_fixed = salary.pension_employee_fixed_amount if salary else 0

            if not salary and not emp_benefits:
                continue

            if emp_allowances or emp_benefits:
                allowance_breakdown = []
                if emp_allowances:
                    allowance_breakdown.extend([
                    {
                        'amount': ea.amount,
                        'is_taxable': ea.allowance.is_taxable,
                        'is_pensionable': ea.allowance.is_pensionable,
                        'prorate': True,
                        'code': ea.allowance.code,
                        'name': ea.allowance.name,
                    }
                    for ea in emp_allowances
                    ])
                elif salary:
                    allowance_breakdown.extend([
                        {'amount': salary.house_allowance, 'is_taxable': True, 'is_pensionable': True, 'prorate': True, 'code': 'HOUSE', 'name': 'House Allowance'},
                        {'amount': salary.transport_allowance, 'is_taxable': True, 'is_pensionable': False, 'prorate': True, 'code': 'TRANSPORT', 'name': 'Transport Allowance'},
                        {'amount': salary.meal_allowance, 'is_taxable': True, 'is_pensionable': False, 'prorate': True, 'code': 'MEAL', 'name': 'Meal Allowance'},
                        {'amount': salary.other_allowances, 'is_taxable': True, 'is_pensionable': False, 'prorate': True, 'code': 'OTHER_ALLOW', 'name': 'Other Allowances'},
                    ])
                allowance_breakdown.extend(
                    {
                        'amount': b.amount,
                        'is_taxable': bool(getattr(b, 'is_taxable', True)),
                        'is_pensionable': bool(getattr(b, 'is_pensionable', True)),
                        'prorate': False,
                        'code': f'BEN-{b.id}',
                        'name': b.title or 'Benefit',
                    }
                    for b in emp_benefits
                )
                calc = calculate_employee_payroll(
                    basic_salary=basic,
                    pension_employee_percent=pension_pct,
                    pension_employee_fixed_amount=pension_fixed,
                    pay_date=pay_date,
                    pro_rata_factor=factor,
                    pro_rata_calendar_days=cal_days,
                    allowance_breakdown=allowance_breakdown,
                    employee_id=emp.id,
                    manual_deduction_lines=manual_lines,
                    statutory_company_id=emp.company_id,
                    statutory_country_code=run_cc,
                    overtime_days=overtime_days,
                    **_payroll_calc_kwargs(run_obj, run_cc, emp.id),
                )
            else:
                calc = calculate_employee_payroll(
                    basic_salary=basic,
                    house_allowance=salary.house_allowance if salary else 0,
                    transport_allowance=salary.transport_allowance if salary else 0,
                    meal_allowance=salary.meal_allowance if salary else 0,
                    other_allowances=salary.other_allowances if salary else 0,
                    pension_employee_percent=pension_pct,
                    pension_employee_fixed_amount=pension_fixed,
                    pay_date=pay_date,
                    pro_rata_factor=factor,
                    pro_rata_calendar_days=cal_days,
                    employee_id=emp.id,
                    manual_deduction_lines=manual_lines,
                    statutory_company_id=emp.company_id,
                    statutory_country_code=run_cc,
                    overtime_days=overtime_days,
                    **_payroll_calc_kwargs(run_obj, run_cc, emp.id),
                )
            for ot_r in ot_rows:
                ot_r.applied_to_payroll_run_id = run_obj.id
            item = PayrollItem(
                payroll_run_id=run_obj.id,
                employee_id=emp.id,
                gross_pay=calc['gross_pay'],
                taxable_pay=calc['taxable_pay'],
                paye=calc['paye'],
                nssf_employee=calc['nssf_employee'],
                nssf_employer=calc['nssf_employer'],
                shif=calc['shif'],
                housing_levy=calc['housing_levy'],
                other_deductions=calc['other_deductions'],
                net_pay=calc['net_pay'],
                earnings_breakdown=calc['earnings_breakdown'],
                deductions_breakdown=calc['deductions_breakdown'],
                is_pro_rata=(cal_days is not None or factor < Decimal('1')),
            )
            db.session.add(item)
        consultant_processed = calculate_all_consultants_for_run(run_obj, period_start, period_end)
        db.session.commit()
        processed = max(eligible_count - len(excluded_employee_ids & eligible_employee_ids), 0)
        flash(
            f'Payroll calculated for {processed} employee(s) and {consultant_processed} consultant(s).',
            'success',
        )
        return redirect(url_for('payroll.view_run', id=run_obj.id))

    if request.method == 'POST' and request.form.get('action') == 'recalculate_consultant':
        q_rec = (request.form.get('q') or '').strip()
        consultant_id = request.form.get('consultant_id', type=int)
        if not consultant_id:
            flash('Select a consultant to recalculate.', 'danger')
            if q_rec:
                return redirect(url_for('payroll.run_calculate', id=run_obj.id, q=q_rec))
            return redirect(url_for('payroll.run_calculate', id=run_obj.id))
        if consultant_id not in {c.id for c in consultants}:
            flash('Consultant not found in this payroll country scope.', 'danger')
            if q_rec:
                return redirect(url_for('payroll.run_calculate', id=run_obj.id, q=q_rec))
            return redirect(url_for('payroll.run_calculate', id=run_obj.id))
        if consultant_id in excluded_consultant_ids_set:
            flash('Consultant is excluded from this run. Remove exclusion first.', 'warning')
            if q_rec:
                return redirect(url_for('payroll.run_calculate', id=run_obj.id, q=q_rec))
            return redirect(url_for('payroll.run_calculate', id=run_obj.id))
        ok, err, calc = recalculate_single_consultant(
            run_obj, consultant_id, period_start, period_end
        )
        if not ok:
            flash(err or 'Could not recalculate consultant.', 'danger')
            if q_rec:
                return redirect(url_for('payroll.run_calculate', id=run_obj.id, q=q_rec))
            return redirect(url_for('payroll.run_calculate', id=run_obj.id))
        db.session.commit()
        gross_msg = ''
        if calc and calc.get('gross_pay') is not None:
            gross_msg = f" Gross pay: {Decimal(str(calc['gross_pay'])):,.2f}."
        from app.models.consultant import Consultant as ConsultantModel
        con = db.session.get(ConsultantModel, consultant_id)
        flash(f"Payroll recalculated for {con.full_name if con else 'consultant'}.{gross_msg}", 'success')
        if q_rec:
            return redirect(url_for('payroll.run_calculate', id=run_obj.id, q=q_rec))
        return redirect(url_for('payroll.view_run', id=run_obj.id))

    if request.method == 'POST' and request.form.get('action') == 'recalculate_employee':
        q_rec = (request.form.get('q') or '').strip()
        emp_id = request.form.get('employee_id', type=int)
        if not emp_id:
            flash('Select an employee to recalculate.', 'danger')
            if q_rec:
                return redirect(url_for('payroll.run_calculate', id=run_obj.id, q=q_rec))
            return redirect(url_for('payroll.run_calculate', id=run_obj.id))
        if emp_id not in {e.id for e in employees}:
            flash('Employee not found in this payroll country scope.', 'danger')
            if q_rec:
                return redirect(url_for('payroll.run_calculate', id=run_obj.id, q=q_rec))
            return redirect(url_for('payroll.run_calculate', id=run_obj.id))
        if emp_id in excluded_employee_ids:
            flash('Employee is excluded from this run. Remove exclusion first.', 'warning')
            if q_rec:
                return redirect(url_for('payroll.run_calculate', id=run_obj.id, q=q_rec))
            return redirect(url_for('payroll.run_calculate', id=run_obj.id))
        ok, err, calc = _recalculate_single_employee(emp_id)
        if not ok:
            flash(err or 'Could not recalculate employee.', 'danger')
            if q_rec:
                return redirect(url_for('payroll.run_calculate', id=run_obj.id, q=q_rec))
            return redirect(url_for('payroll.run_calculate', id=run_obj.id))
        db.session.commit()
        gross_msg = ''
        if calc and calc.get('gross_pay') is not None:
            gross_msg = f" Gross pay: {Decimal(str(calc['gross_pay'])):,.2f} KES."
        emp = db.session.get(EmpModel, emp_id)
        flash(f"Payroll recalculated for {emp.full_name if emp else 'employee'}.{gross_msg}", 'success')
        if q_rec:
            return redirect(url_for('payroll.run_calculate', id=run_obj.id, q=q_rec))
        return redirect(url_for('payroll.view_run', id=run_obj.id))
    q = (request.args.get('q') or '').strip()
    employees_table = employees
    missing_salary_display = missing_salary
    if q:
        needle = q.lower()
        employees_table = [
            e
            for e in employees
            if needle in (e.full_name or '').lower() or needle in str(e.employee_number or '').lower()
        ]
        missing_salary_display = [
            e
            for e in missing_salary
            if needle in (e.full_name or '').lower() or needle in str(e.employee_number or '').lower()
        ]
    payroll_gross_by_employee = {
        row.employee_id: row.gross_pay
        for row in db.session.query(PayrollItem.employee_id, PayrollItem.gross_pay).filter(
            PayrollItem.payroll_run_id == run_obj.id
        ).all()
    }
    consultants_table = consultants
    missing_compensation_display = missing_compensation
    if q:
        needle = q.lower()
        consultants_table = [
            c
            for c in consultants
            if needle in (c.full_name or '').lower()
            or needle in str(c.consultant_number or '').lower()
        ]
        missing_compensation_display = [
            c
            for c in missing_compensation
            if needle in (c.full_name or '').lower()
            or needle in str(c.consultant_number or '').lower()
        ]
    payroll_gross_by_consultant = {
        row.consultant_id: row.gross_pay
        for row in db.session.query(ConsultantPayrollItem.consultant_id, ConsultantPayrollItem.gross_pay).filter(
            ConsultantPayrollItem.payroll_run_id == run_obj.id
        ).all()
    }
    return render_template(
        'payroll/run_calculate.html',
        run=run_obj,
        run_country_code=run_cc,
        run_currency=run_currency,
        employees=employees_table,
        active_employee_count=len(employees),
        eligible_count=eligible_count,
        excluded_employee_ids=excluded_employee_ids,
        excluded_count=excluded_count,
        included_count=included_count,
        missing_salary_ids=missing_salary_ids,
        missing_salary=missing_salary_display,
        payroll_gross_by_employee=payroll_gross_by_employee,
        consultants=consultants_table,
        active_consultant_count=len(consultants),
        consultant_eligible_count=consultant_eligible_count,
        excluded_consultant_ids=excluded_consultant_ids_set,
        consultant_excluded_count=consultant_excluded_count,
        consultant_included_count=consultant_included_count,
        missing_compensation_ids=missing_compensation_ids,
        missing_compensation=missing_compensation_display,
        payroll_gross_by_consultant=payroll_gross_by_consultant,
        q=q,
    )


@payroll_bp.route('/run/<int:id>/manual-deductions', methods=['GET', 'POST'])
@login_required
@permission_required('process_payroll')
def run_manual_deductions(id):
    """One-off deductions for this draft payroll run (applied on next calculate)."""
    run_obj = db.session.get(PayrollRun, id)
    if not run_obj or run_obj.status != 'draft' or run_obj.company_id != require_company_id():
        from flask import abort
        abort(404)
    from calendar import monthrange

    pay_date = date(run_obj.pay_year, run_obj.pay_month, 1)
    _, month_last_day = monthrange(run_obj.pay_year, run_obj.pay_month)
    period_start = date(run_obj.pay_year, run_obj.pay_month, 1)
    period_end = date(run_obj.pay_year, run_obj.pay_month, month_last_day)
    run_cc = _cc(run_obj.country_code)
    run_currency = currency_for_country(run_cc)
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            emp_id = request.form.get('employee_id', type=int)
            label = (request.form.get('label') or '').strip()
            amount = request.form.get('amount', type=float)
            notes = (request.form.get('notes') or '').strip() or None
            if emp_id and label and amount is not None and amount > 0:
                db.session.add(
                    PayrollRunManualDeduction(
                        payroll_run_id=run_obj.id,
                        employee_id=emp_id,
                        label=label,
                        amount=Decimal(str(amount)),
                        notes=notes,
                    )
                )
                db.session.commit()
                flash('Manual deduction added. Recalculate payroll to apply.', 'success')
            else:
                flash('Select employee, label, and a positive amount.', 'danger')
        elif action == 'delete':
            mid = request.form.get('id', type=int)
            if mid:
                row = db.session.get(PayrollRunManualDeduction, mid)
                if row and row.payroll_run_id == run_obj.id:
                    db.session.delete(row)
                    db.session.commit()
                    flash('Manual deduction removed.', 'success')
        return redirect(url_for('payroll.run_manual_deductions', id=id))
    rows = (
        db.session.query(PayrollRunManualDeduction)
        .filter(PayrollRunManualDeduction.payroll_run_id == run_obj.id)
        .order_by(PayrollRunManualDeduction.id)
        .all()
    )
    employees_with_salary = []
    for emp in (
        db.session.query(EmpModel)
        .join(Branch, EmpModel.branch_id == Branch.id)
        .filter(
            EmpModel.company_id == run_obj.company_id,
            Branch.country_code == run_cc,
            EmpModel.hire_date <= period_end,
            db.or_(
                EmpModel.termination_date.is_(None),
                EmpModel.termination_date >= period_start,
            ),
        )
        .order_by(EmpModel.first_name)
        .all()
    ):
        sal = db.session.query(EmployeeSalary).filter(
            EmployeeSalary.employee_id == emp.id,
            EmployeeSalary.effective_from <= period_end,
            (EmployeeSalary.effective_to.is_(None)) | (EmployeeSalary.effective_to >= period_start),
        ).order_by(EmployeeSalary.effective_from.desc()).first()
        if sal:
            employees_with_salary.append(emp)
    return render_template(
        'payroll/run_manual_deductions.html',
        run=run_obj,
        run_country_code=run_cc,
        run_currency=run_currency,
        rows=rows,
        employees=employees_with_salary,
    )


@payroll_bp.route('/run/<int:id>')
@login_required
@permission_required('view_payroll')
def view_run(id):
    run_obj = db.session.get(PayrollRun, id)
    if not run_obj or run_obj.company_id != require_company_id():
        from flask import abort
        abort(404)
    q = (request.args.get('q') or '').strip()
    tab = (request.args.get('tab') or 'staff').strip().lower()
    if tab not in ('staff', 'consultants'):
        tab = 'staff'
    items = (
        db.session.query(PayrollItem)
        .filter(PayrollItem.payroll_run_id == run_obj.id)
        .options(joinedload(PayrollItem.employee))
        .order_by(PayrollItem.employee_id)
        .all()
    )
    consultant_items = (
        db.session.query(ConsultantPayrollItem)
        .filter(ConsultantPayrollItem.payroll_run_id == run_obj.id)
        .options(joinedload(ConsultantPayrollItem.consultant))
        .order_by(ConsultantPayrollItem.consultant_id)
        .all()
    )
    if q:
        needle = q.lower()
        items = [
            it for it in items
            if it.employee and (
                needle in (it.employee.full_name or '').lower()
                or needle in str(it.employee.employee_number or '').lower()
            )
        ]
        consultant_items = [
            it for it in consultant_items
            if it.consultant and (
                needle in (it.consultant.full_name or '').lower()
                or needle in str(it.consultant.consultant_number or '').lower()
            )
        ]
    staff_totals = {
        'gross': sum(Decimal(str(it.gross_pay or 0)) for it in items),
        'net': sum(Decimal(str(it.net_pay or 0)) for it in items),
    }
    consultant_totals = {
        'gross': sum(Decimal(str(it.gross_pay or 0)) for it in consultant_items),
        'wht': sum(Decimal(str(it.withholding_tax or 0)) for it in consultant_items),
        'net': sum(Decimal(str(it.net_pay or 0)) for it in consultant_items),
    }
    combined_totals = {
        'gross': staff_totals['gross'] + consultant_totals['gross'],
        'net': staff_totals['net'] + consultant_totals['net'],
    }
    run_currency = currency_for_country(_cc(run_obj.country_code))
    return render_template(
        'payroll/view_run.html',
        run=run_obj,
        items=items,
        consultant_items=consultant_items,
        staff_totals=staff_totals,
        consultant_totals=consultant_totals,
        combined_totals=combined_totals,
        run_currency=run_currency,
        tab=tab,
        q=q,
    )


@payroll_bp.route('/run/<int:id>/export-kenya.xlsx')
@login_required
@permission_required('view_payroll')
def export_kenya_payroll_xlsx(id):
    """Export Kenya staff payroll run to Excel."""
    run_obj = db.session.get(PayrollRun, id)
    cid = require_company_id()
    if not run_obj or run_obj.company_id != cid:
        abort(404)
    if _cc(run_obj.country_code) != 'KE':
        flash('Kenya payroll export is only available for KE payroll runs.', 'warning')
        return redirect(url_for('payroll.view_run', id=id))

    from app.services.kenya_payroll_export_service import (
        build_kenya_payroll_workbook,
        fetch_kenya_consultant_items,
        fetch_kenya_payroll_items,
    )

    items = fetch_kenya_payroll_items(run_obj.id, cid)
    consultant_items = fetch_kenya_consultant_items(run_obj.id, cid)
    if not items and not consultant_items:
        flash('No payroll items to export. Calculate payroll first.', 'warning')
        return redirect(url_for('payroll.view_run', id=id))

    buffer = build_kenya_payroll_workbook(run_obj, items, consultant_items)
    filename = f'payroll-ke-{run_obj.pay_year}-{run_obj.pay_month:02d}.xlsx'
    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


@payroll_bp.route('/run/<int:id>/export-uganda.xlsx')
@login_required
@permission_required('view_payroll')
def export_uganda_payroll_xlsx(id):
    """Export Uganda staff payroll run to Excel."""
    run_obj = db.session.get(PayrollRun, id)
    cid = require_company_id()
    if not run_obj or run_obj.company_id != cid:
        abort(404)
    if _cc(run_obj.country_code) != 'UG':
        flash('Uganda payroll export is only available for UG payroll runs.', 'warning')
        return redirect(url_for('payroll.view_run', id=id))

    from app.services.uganda_payroll_export_service import (
        build_uganda_payroll_workbook,
        fetch_uganda_payroll_items,
    )

    items = fetch_uganda_payroll_items(run_obj.id, cid)
    if not items:
        flash('No staff payroll items to export. Calculate payroll first.', 'warning')
        return redirect(url_for('payroll.view_run', id=id))

    buffer = build_uganda_payroll_workbook(run_obj, items)
    filename = f'payroll-ug-{run_obj.pay_year}-{run_obj.pay_month:02d}.xlsx'
    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


@payroll_bp.route('/run/<int:id>/approve', methods=['POST'])
@login_required
@permission_required('approve_payroll')
def approve_run(id):
    from datetime import datetime
    run_obj = db.session.get(PayrollRun, id)
    if not run_obj or run_obj.status != 'draft' or run_obj.company_id != require_company_id():
        from flask import abort
        abort(404)
    run_obj.status = 'approved'
    run_obj.approved_by_id = current_user.id
    run_obj.approved_at = datetime.utcnow()
    n_lines = replace_statutory_remitances_for_run(run_obj.id)
    db.session.commit()
    log_update('PayrollRun', run_obj.id, {'status': 'draft'}, {'status': 'approved'}, user_id=current_user.id, description='Payroll approved')
    flash(
        f'Payroll approved. Statutory remittances recorded ({n_lines} line(s)) for institutions (PAYE, NSSF, SHIF, Housing).',
        'success',
    )
    return redirect(url_for('payroll.view_run', id=run_obj.id))


@payroll_bp.route('/run/<int:id>/unapprove', methods=['POST'])
@login_required
@permission_required('approve_payroll')
def unapprove_run(id):
    """Revert an approved (or finance-reviewed) payroll to draft for recalculation."""
    run_obj = db.session.get(PayrollRun, id)
    if not run_obj or run_obj.company_id != require_company_id():
        abort(404)
    if run_obj.status == 'paid':
        flash(
            'This payroll is marked as paid and cannot be un-approved. '
            'Contact an administrator if a correction is required.',
            'warning',
        )
        return redirect(url_for('payroll.view_run', id=id))
    if run_obj.status not in ('approved', 'finance_reviewed'):
        flash('Only approved or finance-reviewed payrolls can be reverted to draft.', 'warning')
        return redirect(url_for('payroll.view_run', id=id))
    previous_status = run_obj.status
    n_removed = delete_statutory_remitances_for_run(run_obj.id)
    run_obj.status = 'draft'
    run_obj.approved_by_id = None
    run_obj.approved_at = None
    run_obj.finance_reviewed_by_id = None
    run_obj.finance_reviewed_at = None
    db.session.commit()
    log_update(
        'PayrollRun',
        run_obj.id,
        {'status': previous_status},
        {'status': 'draft'},
        user_id=current_user.id,
        description='Payroll un-approved (reverted to draft)',
    )
    flash(
        f'Payroll reverted to draft. Removed {n_removed} statutory remittance line(s). '
        'You can recalculate and approve again when ready.',
        'success',
    )
    return redirect(url_for('payroll.view_run', id=run_obj.id))


@payroll_bp.route('/run/<int:id>/finance-review', methods=['POST'])
@login_required
@permission_required('review_payroll_finance')
def finance_review_run(id):
    from datetime import datetime

    run_obj = db.session.get(PayrollRun, id)
    if not run_obj or run_obj.company_id != require_company_id():
        abort(404)
    if run_obj.status != 'approved':
        flash('Only approved payroll runs can be marked as finance reviewed.', 'warning')
        return redirect(url_for('payroll.view_run', id=id))
    run_obj.status = 'finance_reviewed'
    run_obj.finance_reviewed_by_id = current_user.id
    run_obj.finance_reviewed_at = datetime.utcnow()
    db.session.commit()
    log_update(
        'PayrollRun',
        run_obj.id,
        {'status': 'approved'},
        {'status': 'finance_reviewed'},
        user_id=current_user.id,
        description='Payroll finance review completed',
    )
    flash('Payroll marked as finance reviewed.', 'success')
    return redirect(url_for('payroll.view_run', id=run_obj.id))


@payroll_bp.route('/run/<int:id>/mark-paid', methods=['POST'])
@login_required
@permission_required('mark_payroll_paid')
def mark_paid_run(id):
    from datetime import datetime

    run_obj = db.session.get(PayrollRun, id)
    if not run_obj or run_obj.company_id != require_company_id():
        abort(404)
    if run_obj.status not in ('approved', 'finance_reviewed'):
        flash('Only approved/finance-reviewed payroll runs can be marked paid.', 'warning')
        return redirect(url_for('payroll.view_run', id=id))
    previous = run_obj.status
    run_obj.status = 'paid'
    run_obj.paid_by_id = current_user.id
    run_obj.paid_at = datetime.utcnow()
    payment_ref = (request.form.get('payment_reference') or '').strip()
    run_obj.payment_reference = payment_ref or None
    db.session.commit()
    log_update(
        'PayrollRun',
        run_obj.id,
        {'status': previous},
        {'status': 'paid', 'payment_reference': run_obj.payment_reference},
        user_id=current_user.id,
        description='Payroll marked as paid by finance',
    )
    flash('Payroll marked as paid.', 'success')
    return redirect(url_for('payroll.view_run', id=run_obj.id))


@payroll_bp.route('/run/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('process_payroll')
def delete_run(id):
    run_obj = db.session.get(PayrollRun, id)
    if not run_obj or run_obj.company_id != require_company_id():
        flash('Payroll run not found.', 'danger')
        return redirect(url_for('payroll.index'))
    if run_obj.status != 'draft':
        flash('Only draft payrolls can be deleted. This run is already {}.'.format(run_obj.status), 'danger')
        return redirect(url_for('payroll.view_run', id=id))
    db.session.delete(run_obj)
    db.session.commit()
    flash('Payroll deleted.', 'success')
    return redirect(url_for('payroll.index'))


@payroll_bp.route('/run/<int:id>/statutory-remittances')
@login_required
@permission_required('view_payroll')
def view_statutory_remitances(id):
    """Per-employee statutory amounts owed to institutions (recorded on payroll approval)."""
    run_obj = db.session.get(PayrollRun, id)
    if not run_obj or run_obj.company_id != require_company_id():
        from flask import abort
        abort(404)
    if run_obj.status not in ('approved', 'finance_reviewed', 'paid'):
        flash('Statutory remittances are only available after payroll is approved.', 'warning')
        return redirect(url_for('payroll.view_run', id=id))
    remittances = (
        db.session.query(PayrollStatutoryRemittance)
        .filter(PayrollStatutoryRemittance.payroll_run_id == run_obj.id)
        .order_by(
            PayrollStatutoryRemittance.statutory_code,
            PayrollStatutoryRemittance.employee_id,
        )
        .all()
    )
    totals = institution_totals_for_run(run_obj.id)
    grand_total = Decimal('0')
    for t in totals:
        grand_total += Decimal(str(t['total'] or 0))
    return render_template(
        'payroll/statutory_remitances.html',
        run=run_obj,
        remittances=remittances,
        totals=totals,
        grand_total=grand_total,
    )


@payroll_bp.route('/my-payslips')
@login_required
def my_payslips():
    """List finalized payslips for the logged-in user's linked employee."""
    if not current_user.employee_id:
        flash('Your account is not linked to an employee record. Contact HR.', 'warning')
        return redirect(url_for('dashboard.index'))
    emp_id = current_user.employee_id
    today_year = date.today().year
    selected_year = request.args.get('year', type=int)
    if selected_year is None:
        selected_year = today_year

    year_rows = (
        db.session.query(PayrollRun.pay_year)
        .join(PayrollItem, PayrollItem.payroll_run_id == PayrollRun.id)
        .filter(
            PayrollItem.employee_id == emp_id,
            PayrollRun.company_id == current_user.company_id,
            PayrollRun.status.in_(_EMPLOYEE_PAYSLIP_RUN_STATUSES),
        )
        .distinct()
        .order_by(PayrollRun.pay_year.desc())
        .all()
    )
    years_from_db = [r[0] for r in year_rows]
    year_options = sorted(set(years_from_db) | {today_year}, reverse=True)

    items = (
        db.session.query(PayrollItem)
        .options(joinedload(PayrollItem.payroll_run))
        .join(PayrollRun, PayrollItem.payroll_run_id == PayrollRun.id)
        .filter(
            PayrollItem.employee_id == emp_id,
            PayrollRun.company_id == current_user.company_id,
            PayrollRun.status.in_(_EMPLOYEE_PAYSLIP_RUN_STATUSES),
            PayrollRun.pay_year == selected_year,
        )
        .order_by(PayrollRun.pay_month.desc())
        .all()
    )
    return render_template(
        'payroll/my_payslips.html',
        items=items,
        selected_year=selected_year,
        year_options=year_options,
    )


def _payslip_item_query(run_id: int, employee_id: int):
    return (
        db.session.query(PayrollItem)
        .options(
            joinedload(PayrollItem.payroll_run).joinedload(PayrollRun.company),
            joinedload(PayrollItem.employee).joinedload(EmpModel.branch),
            joinedload(PayrollItem.employee).joinedload(EmpModel.department),
            joinedload(PayrollItem.employee).joinedload(EmpModel.job_title),
            joinedload(PayrollItem.employee).joinedload(EmpModel.user),
        )
        .filter(
            PayrollItem.payroll_run_id == run_id,
            PayrollItem.employee_id == employee_id,
        )
    )


def _fetch_payslip_item(run_id: int, employee_id: int) -> PayrollItem:
    item = _payslip_item_query(run_id, employee_id).first()
    if not item:
        abort(404)
    run = item.payroll_run
    if not run or run.company_id != require_company_id():
        abort(404)
    is_own = current_user.employee_id is not None and current_user.employee_id == employee_id
    has_payroll_view = current_user.has_permission('view_payroll')
    if not is_own and not has_payroll_view:
        abort(403)
    if is_own and not has_payroll_view and run.status not in _EMPLOYEE_PAYSLIP_RUN_STATUSES:
        abort(403)
    return item


@payroll_bp.route('/payslip/<int:run_id>/<int:employee_id>')
@login_required
def view_payslip(run_id, employee_id):
    item = _fetch_payslip_item(run_id, employee_id)
    return render_template('payroll/view_payslip.html', **build_payslip_context(item))


@payroll_bp.route('/payslip/<int:run_id>/<int:employee_id>/pdf')
@login_required
def export_payslip_pdf(run_id, employee_id):
    item = _fetch_payslip_item(run_id, employee_id)
    ctx = build_payslip_context(item)
    pdf_bytes = build_payslip_pdf(ctx)
    return send_file(
        BytesIO(pdf_bytes),
        as_attachment=True,
        download_name=payslip_pdf_filename(item),
        mimetype='application/pdf',
    )


@payroll_bp.route('/payslip/<int:run_id>/<int:employee_id>/email', methods=['POST'])
@login_required
@permission_required('process_payroll')
def email_payslip(run_id, employee_id):
    item = _payslip_item_query(run_id, employee_id).first()
    if not item or not item.payroll_run or item.payroll_run.company_id != require_company_id():
        abort(404)
    run = item.payroll_run
    if run.status not in _EMPLOYEE_PAYSLIP_RUN_STATUSES:
        flash('Payslips can only be emailed after payroll is approved.', 'warning')
        return redirect(url_for('payroll.view_run', id=run_id))
    ok, message = send_payslip_email(item)
    flash(message, 'success' if ok else 'danger')
    next_url = request.form.get('next') or url_for('payroll.view_payslip', run_id=run_id, employee_id=employee_id)
    return redirect(next_url)


@payroll_bp.route('/run/<int:id>/email-payslips', methods=['POST'])
@login_required
@permission_required('process_payroll')
def email_payslips_for_run(id):
    run_obj = db.session.get(PayrollRun, id)
    if not run_obj or run_obj.company_id != require_company_id():
        abort(404)
    if run_obj.status not in _EMPLOYEE_PAYSLIP_RUN_STATUSES:
        flash('Payslips can only be emailed after payroll is approved.', 'warning')
        return redirect(url_for('payroll.view_run', id=id))
    if not request.form.get('confirm'):
        flash('Please confirm before emailing all payslips.', 'warning')
        return redirect(url_for('payroll.view_run', id=id))
    result = send_payslips_for_run(run_obj.id, run_obj.company_id)
    parts = [f'{result["sent"]} payslip(s) emailed']
    if result['skipped_no_email']:
        parts.append(f'{result["skipped_no_email"]} skipped (no email on file)')
    if result['failed']:
        parts.append(f'{result["failed"]} failed to send')
    flash('. '.join(parts) + '.', 'success' if result['sent'] else 'warning')
    return redirect(url_for('payroll.view_run', id=id))


def _fetch_consultant_payslip_item(run_id: int, consultant_id: int) -> ConsultantPayrollItem:
    item = (
        db.session.query(ConsultantPayrollItem)
        .options(
            joinedload(ConsultantPayrollItem.consultant).joinedload(Consultant.branch),
            joinedload(ConsultantPayrollItem.payroll_run),
        )
        .filter(
            ConsultantPayrollItem.payroll_run_id == run_id,
            ConsultantPayrollItem.consultant_id == consultant_id,
        )
        .first()
    )
    if not item or not item.payroll_run or item.payroll_run.company_id != require_company_id():
        abort(404)
    if not current_user.has_permission('view_payroll'):
        abort(403)
    return item


def _build_consultant_payslip_context(item: ConsultantPayrollItem) -> dict:
    from app.utils.currency import currency_for_branch

    run = item.payroll_run
    period_date = date(run.pay_year, run.pay_month, 1)
    con = item.consultant
    payslip_currency = currency_for_branch(
        con.branch if con else None,
        app_default=current_app.config.get('DEFAULT_CURRENCY', 'KES'),
    )
    earnings_lines = []
    for e in item.earnings_breakdown or []:
        try:
            amt = float(e.get('amount') or 0)
        except (TypeError, ValueError):
            amt = 0.0
        if amt:
            earnings_lines.append(e)
    deduction_lines = []
    for d in item.deductions_breakdown or []:
        try:
            amt = float(d.get('amount') or 0)
        except (TypeError, ValueError):
            amt = 0.0
        if amt:
            deduction_lines.append(d)
    return {
        'item': item,
        'consultant': con,
        'period_date': period_date,
        'payslip_currency': payslip_currency,
        'earnings_lines': earnings_lines,
        'deduction_lines': deduction_lines,
        'company_name': run.company.name if run and run.company else None,
    }


@payroll_bp.route('/consultant-payslip/<int:run_id>/<int:consultant_id>')
@login_required
@permission_required('view_payroll')
def view_consultant_payslip(run_id, consultant_id):
    item = _fetch_consultant_payslip_item(run_id, consultant_id)
    return render_template('payroll/view_consultant_payslip.html', **_build_consultant_payslip_context(item))
