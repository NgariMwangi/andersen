"""
P9 / annual payroll summary for iTax: calendar-year totals from approved payroll runs (option A).
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date
from typing import Optional
from decimal import Decimal

from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.payroll import PayrollItem, PayrollRun
from app.models.employee import Employee
from app.services.statutory_service import calculate_paye_breakdown, get_personal_relief


MONTH_NAMES = (
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
)


def _quantize(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(Decimal('0.01'))


def _basic_from_item(item: PayrollItem) -> Decimal:
    """Basic salary component from payslip earnings_breakdown."""
    for row in item.earnings_breakdown or []:
        if str(row.get('code', '')).upper() == 'BASIC':
            return _quantize(row.get('amount', 0))
    return Decimal('0')


def _benefits_from_item(item: PayrollItem) -> Decimal:
    """
    Non-basic taxable cash components of gross (allowances + other earnings in payslip breakdown).
    Non-taxable reimbursements are excluded from P9 benefits.
    """
    gross = _quantize(item.gross_pay)
    basic = Decimal('0')
    non_taxable = Decimal('0')
    for row in item.earnings_breakdown or []:
        code = str(row.get('code', '')).upper()
        amt = Decimal(str(row.get('amount', 0)))
        if code == 'BASIC':
            basic = amt
        if row.get('is_taxable') is False:
            non_taxable += amt
    diff = gross - basic - non_taxable
    if diff < 0:
        diff = Decimal('0')
    return diff.quantize(Decimal('0.01'))


def _pay_period_date(run: PayrollRun) -> date:
    return date(int(run.pay_year), int(run.pay_month), 1)


def _statutory_company_and_country(item: PayrollItem) -> tuple[int, str]:
    """Company from payroll run; country from employee branch (defaults KE)."""
    run = item.payroll_run
    cid = int(run.company_id) if run and run.company_id is not None else 0
    cc = 'KE'
    emp = item.employee
    if emp and getattr(emp, 'branch', None) is not None and emp.branch.country_code:
        cc = str(emp.branch.country_code).upper()[:2]
    return cid, cc


def aggregate_p9_for_year(calendar_year: int, company_id: int) -> dict:
    """
    Per employee, full-year P9-style totals from PayrollItem snapshots + PAYE breakdown.

    Returns dict[employee_id] = {
        months_paye: {1..12: Decimal},
        gross_pay, benefits, chargeable_income (sum taxable_pay),
        tax_before_relief, personal_relief_applied,
        paye (stored sums), nssf_employee, nssf_employer, shif, housing_levy
    }
    """
    items = (
        db.session.query(PayrollItem)
        .join(PayrollRun, PayrollItem.payroll_run_id == PayrollRun.id)
        .filter(
            PayrollRun.status == 'approved',
            PayrollRun.pay_year == calendar_year,
            PayrollRun.company_id == company_id,
        )
        .options(
            joinedload(PayrollItem.payroll_run),
            joinedload(PayrollItem.employee).joinedload(Employee.branch),
        )
        .all()
    )
    by_emp: dict = defaultdict(
        lambda: {
            'months_paye': {m: Decimal('0') for m in range(1, 13)},
            'gross_pay': Decimal('0'),
            'benefits': Decimal('0'),
            'chargeable_income': Decimal('0'),
            'tax_before_relief': Decimal('0'),
            'personal_relief_applied': Decimal('0'),
            'paye': Decimal('0'),
            'nssf_employee': Decimal('0'),
            'nssf_employer': Decimal('0'),
            'shif': Decimal('0'),
            'housing_levy': Decimal('0'),
        }
    )
    for item in items:
        run = item.payroll_run
        if not run:
            continue
        m = int(run.pay_month)
        if not (1 <= m <= 12):
            continue
        eid = item.employee_id
        bucket = by_emp[eid]
        bucket['months_paye'][m] += _quantize(item.paye)
        bucket['gross_pay'] += _quantize(item.gross_pay)
        bucket['benefits'] += _benefits_from_item(item)
        bucket['chargeable_income'] += _quantize(item.taxable_pay)
        bucket['paye'] += _quantize(item.paye)
        bucket['nssf_employee'] += _quantize(item.nssf_employee)
        bucket['nssf_employer'] += _quantize(item.nssf_employer)
        bucket['shif'] += _quantize(item.shif)
        bucket['housing_levy'] += _quantize(item.housing_levy)
        pd = _pay_period_date(run)
        sc, scc = _statutory_company_and_country(item)
        br = calculate_paye_breakdown(item.taxable_pay, pd, sc, scc)
        bucket['tax_before_relief'] += br['tax_before_relief']
        bucket['personal_relief_applied'] += br['personal_relief_applied']

    for eid, bucket in by_emp.items():
        for k in (
            'gross_pay',
            'benefits',
            'chargeable_income',
            'tax_before_relief',
            'personal_relief_applied',
            'paye',
            'nssf_employee',
            'nssf_employer',
            'shif',
            'housing_levy',
        ):
            bucket[k] = bucket[k].quantize(Decimal('0.01'))
        bucket['months_paye'] = {mm: bucket['months_paye'][mm].quantize(Decimal('0.01')) for mm in range(1, 13)}
    return dict(by_emp)


def fetch_annual_paye_matrix(calendar_year: int, company_id: int) -> dict:
    """
    Aggregate PAYE by employee and calendar month from approved payroll runs.
    Returns dict[employee_id] = {'months': {1..12: Decimal}, 'total': Decimal}
    """
    full = aggregate_p9_for_year(calendar_year, company_id)
    out = {}
    for emp_id, data in full.items():
        months = data['months_paye']
        total = sum(months.values(), start=Decimal('0')).quantize(Decimal('0.01'))
        out[emp_id] = {'months': months, 'total': total}
    return out


def load_employees_for_p9(employee_ids: list) -> dict:
    """Map employee_id -> Employee."""
    if not employee_ids:
        return {}
    emps = db.session.query(Employee).filter(Employee.id.in_(employee_ids)).all()
    return {e.id: e for e in emps}


def rows_for_csv(calendar_year: int, company_id: int) -> list:
    """
    One row per employee: identity + monthly PAYE + yearly P9 totals (iTax-oriented).
    """
    full = aggregate_p9_for_year(calendar_year, company_id)
    emps = load_employees_for_p9(list(full.keys()))
    rows = []
    for emp_id, data in full.items():
        emp = emps.get(emp_id)
        row = {
            'employee_id': emp_id,
            'employee_number': emp.employee_number if emp else '',
            'pin': (emp.kra_pin or '').strip() if emp else '',
            'name': emp.full_name if emp else f'Employee #{emp_id}',
        }
        for m in range(1, 13):
            row[f'm{m}'] = data['months_paye'][m]
        row['total_paye'] = data['paye']
        row['gross_pay_yearly'] = data['gross_pay']
        row['benefits_yearly'] = data['benefits']
        row['chargeable_income_yearly'] = data['chargeable_income']
        row['tax_before_relief_yearly'] = data['tax_before_relief']
        row['personal_relief_yearly'] = data['personal_relief_applied']
        row['nssf_employee_yearly'] = data['nssf_employee']
        row['nssf_employer_yearly'] = data['nssf_employer']
        row['shif_yearly'] = data['shif']
        row['housing_levy_yearly'] = data['housing_levy']
        rows.append(row)
    rows.sort(key=lambda r: (r['name'] or '').lower())
    return rows


def monthly_p9_rows(calendar_year: int, employee_id: int, company_id: int) -> list:
    """
    One row per month that has approved payroll for this employee (months without payroll are omitted).
    Pension = NSSF employee contribution; PAYE auto = stored PAYE; MPR from statutory rates.
    Arrears / PAYE manual are not tracked in HRMS — shown as 0.
    """
    items = (
        db.session.query(PayrollItem)
        .join(PayrollRun, PayrollItem.payroll_run_id == PayrollRun.id)
        .filter(
            PayrollRun.status == 'approved',
            PayrollRun.pay_year == calendar_year,
            PayrollRun.company_id == company_id,
            PayrollItem.employee_id == employee_id,
        )
        .options(
            joinedload(PayrollItem.payroll_run),
            joinedload(PayrollItem.employee).joinedload(Employee.branch),
        )
        .all()
    )
    by_month: dict[int, list] = defaultdict(list)
    for item in items:
        run = item.payroll_run
        if not run:
            continue
        m = int(run.pay_month)
        if 1 <= m <= 12:
            by_month[m].append(item)

    rows = []
    for m in range(1, 13):
        batch = by_month.get(m, [])
        if not batch:
            continue
        pd = date(calendar_year, m, 1)
        last_day = date(calendar_year, m, calendar.monthrange(calendar_year, m)[1])
        pay_date_str = last_day.strftime('%d/%m/%Y')
        sc, scc = _statutory_company_and_country(batch[0])
        mpr = get_personal_relief(pd, sc, scc)
        taxable = sum(_quantize(i.taxable_pay) for i in batch)
        paye = sum(_quantize(i.paye) for i in batch)
        pension = sum(_quantize(i.nssf_employee) for i in batch)
        br = calculate_paye_breakdown(taxable, pd, sc, scc)
        unused = (mpr - br['personal_relief_applied']).quantize(Decimal('0.01'))
        if unused < 0:
            unused = Decimal('0')
        rows.append(
            {
                'month': m,
                'pay_date': pay_date_str,
                'taxable_pay': taxable,
                'pension': pension,
                'paye_auto': paye,
                'unused_mpr': unused,
                'mpr_value': mpr,
                'arrears': Decimal('0'),
                'paye_manual': Decimal('0'),
            }
        )
    return rows


def monthly_p9a_rows(calendar_year: int, employee_id: int, company_id: int) -> list:
    """
    KRA P9A monthly grid from approved payroll (one row per month with payroll data).
    Column keys match the official form: a..o.
    """
    items = (
        db.session.query(PayrollItem)
        .join(PayrollRun, PayrollItem.payroll_run_id == PayrollRun.id)
        .filter(
            PayrollRun.status == 'approved',
            PayrollRun.pay_year == calendar_year,
            PayrollRun.company_id == company_id,
            PayrollItem.employee_id == employee_id,
        )
        .options(
            joinedload(PayrollItem.payroll_run),
            joinedload(PayrollItem.employee).joinedload(Employee.branch),
        )
        .all()
    )
    by_month: dict[int, list] = defaultdict(list)
    for item in items:
        run = item.payroll_run
        if not run:
            continue
        m = int(run.pay_month)
        if 1 <= m <= 12:
            by_month[m].append(item)

    rows = []
    for m in range(1, 13):
        batch = by_month.get(m, [])
        if not batch:
            continue
        pd = date(calendar_year, m, 1)
        sc, scc = _statutory_company_and_country(batch[0])
        basic = sum(_basic_from_item(i) for i in batch)
        benefits = sum(_benefits_from_item(i) for i in batch)
        gross = sum(_quantize(i.gross_pay) for i in batch)
        nssf = sum(_quantize(i.nssf_employee) for i in batch)
        housing = sum(_quantize(i.housing_levy) for i in batch)
        shif = sum(_quantize(i.shif) for i in batch)
        taxable = sum(_quantize(i.taxable_pay) for i in batch)
        paye = sum(_quantize(i.paye) for i in batch)
        br = calculate_paye_breakdown(taxable, pd, sc, scc)
        rows.append(
            {
                'month': m,
                'a_basic': basic,
                'b_benefits': benefits,
                'c_quarters': Decimal('0'),
                'd_gross': gross,
                'e_pension': nssf,
                'f_ahl': housing,
                'g_shif': shif,
                'h_prmf': Decimal('0'),
                'i_owner_interest': Decimal('0'),
                'j_other': Decimal('0'),
                'k_chargeable': taxable,
                'l_tax_charged': br['tax_before_relief'],
                'm_personal_relief': br['personal_relief_applied'],
                'n_insurance_relief': Decimal('0'),
                'o_paye': paye,
            }
        )
    return rows


def p9a_column_totals(monthly_rows: list) -> dict:
    """Sum each P9A column across months (for TOTAL row and footer)."""
    keys = (
        'a_basic', 'b_benefits', 'c_quarters', 'd_gross', 'e_pension', 'f_ahl', 'g_shif',
        'h_prmf', 'i_owner_interest', 'j_other', 'k_chargeable', 'l_tax_charged',
        'm_personal_relief', 'n_insurance_relief', 'o_paye',
    )
    out = {}
    for k in keys:
        out[k] = sum((r[k] for r in monthly_rows), start=Decimal('0')).quantize(Decimal('0.01'))
    return out


def monthly_p9_totals(monthly_rows: list) -> dict:
    keys = ['taxable_pay', 'pension', 'paye_auto', 'unused_mpr', 'mpr_value', 'arrears', 'paye_manual']
    out = {}
    for k in keys:
        out[k] = sum((r[k] for r in monthly_rows), start=Decimal('0')).quantize(Decimal('0.01'))
    return out


def row_for_employee(calendar_year: int, employee_id: int, company_id: int) -> Optional[dict]:
    emp = db.session.get(Employee, employee_id)
    if not emp or emp.company_id != company_id:
        return None
    full = aggregate_p9_for_year(calendar_year, company_id)
    if employee_id not in full:
        return None
    data = full[employee_id]
    months = data['months_paye']
    total_paye = data['paye']
    monthly_rows = monthly_p9_rows(calendar_year, employee_id, company_id)
    monthly_totals = monthly_p9_totals(monthly_rows)
    p9a_rows = monthly_p9a_rows(calendar_year, employee_id, company_id)
    p9a_totals = p9a_column_totals(p9a_rows)
    return {
        'employee': emp,
        'employee_id': employee_id,
        'months': months,
        'total': total_paye,
        'gross_pay': data['gross_pay'],
        'benefits': data['benefits'],
        'chargeable_income': data['chargeable_income'],
        'tax_before_relief': data['tax_before_relief'],
        'personal_relief_applied': data['personal_relief_applied'],
        'paye': data['paye'],
        'nssf_employee': data['nssf_employee'],
        'nssf_employer': data['nssf_employer'],
        'shif': data['shif'],
        'housing_levy': data['housing_levy'],
        'monthly_rows': monthly_rows,
        'monthly_totals': monthly_totals,
        'p9a_rows': p9a_rows,
        'p9a_totals': p9a_totals,
    }
