"""
Payroll calculation router and Kenya engine.

Kenya: PAYE after NSSF, SHIF, Housing Levy on gross; pension cap for PAYE.
Uganda: see uganda_payroll_engine.py (PAYE on gross − LST, NSSF on gross, LST Jul–Oct).
Tanzania: see tanzania_payroll_engine.py (taxable = gross − NSSF employee, PAYE on taxable, NSSF 10%/10%, SDL/WCF employer-only).
"""
from datetime import date
from decimal import Decimal

from app.services.deduction_service import get_recurring_deduction_line_items
from app.services.payroll_common import (
    PRORATA_STANDARD_MONTH_DAYS,
    build_gross_earnings,
    decimalize,
    employment_partial_month_days,
    pro_rata_calendar_days_or_none,
    pro_rata_factor,
)
from app.services.statutory_service import (
    calculate_housing_levy,
    calculate_nssf_with_breakdown,
    calculate_paye,
    calculate_shif,
)

KENYA_PENSION_TAX_DEDUCTIBLE_CAP = Decimal('30000')


def get_working_days_in_month(year: int, month: int) -> int:
    from calendar import monthrange

    wd = 0
    _, last = monthrange(year, month)
    for d in range(1, last + 1):
        dte = date(year, month, d)
        if dte.weekday() < 5:
            wd += 1
    return wd


def calculate_employee_payroll(
    basic_salary: Decimal,
    house_allowance: Decimal = None,
    transport_allowance: Decimal = None,
    meal_allowance: Decimal = None,
    other_allowances: Decimal = None,
    pension_employee_percent: Decimal = None,
    pension_employee_fixed_amount: Decimal = None,
    pay_date: date = None,
    pro_rata_factor: Decimal = None,
    pro_rata_calendar_days: int | None = None,
    other_earnings: Decimal = None,
    other_deductions: Decimal = None,
    allowance_breakdown: list = None,
    employee_id: int = None,
    manual_deduction_lines: list = None,
    statutory_company_id: int | None = None,
    statutory_country_code: str = 'KE',
    overtime_days: Decimal | None = None,
    pay_month: int | None = None,
    pay_year: int | None = None,
    july_gross_for_lst: Decimal | None = None,
) -> dict:
    """
    Calculate single employee pay for the month. Routes by statutory country (UG, TZ, else Kenya).
    """
    scc = (statutory_country_code or 'KE').upper()[:2]
    if scc == 'TZ':
        from app.services.tanzania_payroll_engine import calculate_employee_payroll_tanzania

        return calculate_employee_payroll_tanzania(
            basic_salary=basic_salary,
            house_allowance=house_allowance,
            transport_allowance=transport_allowance,
            meal_allowance=meal_allowance,
            other_allowances=other_allowances,
            pension_employee_percent=pension_employee_percent,
            pension_employee_fixed_amount=pension_employee_fixed_amount,
            pay_date=pay_date,
            pro_rata_factor=pro_rata_factor,
            pro_rata_calendar_days=pro_rata_calendar_days,
            other_earnings=other_earnings,
            other_deductions=other_deductions,
            allowance_breakdown=allowance_breakdown,
            employee_id=employee_id,
            manual_deduction_lines=manual_deduction_lines,
            statutory_company_id=statutory_company_id,
            statutory_country_code=scc,
            overtime_days=overtime_days,
            pay_month=pay_month,
            pay_year=pay_year,
            july_gross_for_lst=july_gross_for_lst,
        )

    if scc == 'UG':
        from app.services.uganda_payroll_engine import calculate_employee_payroll_uganda

        return calculate_employee_payroll_uganda(
            basic_salary=basic_salary,
            house_allowance=house_allowance,
            transport_allowance=transport_allowance,
            meal_allowance=meal_allowance,
            other_allowances=other_allowances,
            pension_employee_percent=pension_employee_percent,
            pension_employee_fixed_amount=pension_employee_fixed_amount,
            pay_date=pay_date,
            pro_rata_factor=pro_rata_factor,
            pro_rata_calendar_days=pro_rata_calendar_days,
            other_earnings=other_earnings,
            other_deductions=other_deductions,
            allowance_breakdown=allowance_breakdown,
            employee_id=employee_id,
            manual_deduction_lines=manual_deduction_lines,
            statutory_company_id=statutory_company_id,
            statutory_country_code=scc,
            overtime_days=overtime_days,
            pay_month=pay_month,
            pay_year=pay_year,
            july_gross_for_lst=july_gross_for_lst,
        )

    return _calculate_employee_payroll_kenya(
        basic_salary=basic_salary,
        house_allowance=house_allowance,
        transport_allowance=transport_allowance,
        meal_allowance=meal_allowance,
        other_allowances=other_allowances,
        pension_employee_percent=pension_employee_percent,
        pension_employee_fixed_amount=pension_employee_fixed_amount,
        pay_date=pay_date,
        pro_rata_factor=pro_rata_factor,
        pro_rata_calendar_days=pro_rata_calendar_days,
        other_earnings=other_earnings,
        other_deductions=other_deductions,
        allowance_breakdown=allowance_breakdown,
        employee_id=employee_id,
        manual_deduction_lines=manual_deduction_lines,
        statutory_company_id=statutory_company_id,
        statutory_country_code=scc,
        overtime_days=overtime_days,
    )


def _calculate_employee_payroll_kenya(
    basic_salary: Decimal,
    house_allowance: Decimal = None,
    transport_allowance: Decimal = None,
    meal_allowance: Decimal = None,
    other_allowances: Decimal = None,
    pension_employee_percent: Decimal = None,
    pension_employee_fixed_amount: Decimal = None,
    pay_date: date = None,
    pro_rata_factor: Decimal = None,
    pro_rata_calendar_days: int | None = None,
    other_earnings: Decimal = None,
    other_deductions: Decimal = None,
    allowance_breakdown: list = None,
    employee_id: int = None,
    manual_deduction_lines: list = None,
    statutory_company_id: int | None = None,
    statutory_country_code: str = 'KE',
    overtime_days: Decimal | None = None,
) -> dict:
    pay_date = pay_date or date.today()
    scid = statutory_company_id
    scc = (statutory_country_code or 'KE').upper()[:2]
    factor = decimalize(pro_rata_factor) if pro_rata_factor is not None else Decimal('1')
    pr_days = pro_rata_calendar_days
    denom = Decimal(PRORATA_STANDARD_MONTH_DAYS)

    earnings = build_gross_earnings(
        basic_salary=basic_salary,
        house_allowance=house_allowance,
        transport_allowance=transport_allowance,
        meal_allowance=meal_allowance,
        other_allowances=other_allowances,
        pro_rata_factor=factor,
        pro_rata_calendar_days=pr_days,
        other_earnings=other_earnings,
        allowance_breakdown=allowance_breakdown,
        overtime_days=overtime_days,
    )
    gross_pay = earnings.gross_pay
    taxable_gross = earnings.taxable_gross
    non_taxable_earnings = earnings.non_taxable_earnings
    pensionable = earnings.pensionable_pay
    earnings_breakdown = earnings.earnings_breakdown

    if scid is None:
        raise ValueError('statutory_company_id is required for payroll calculation')
    nssf_emp, nssf_empr, nssf_breakdown = calculate_nssf_with_breakdown(
        pensionable, pay_date, scid, scc
    )
    nssf_emp = nssf_emp.quantize(Decimal('0.01'))
    nssf_empr = nssf_empr.quantize(Decimal('0.01'))

    shif = calculate_shif(taxable_gross, pay_date, scid, scc)
    housing_levy = calculate_housing_levy(taxable_gross, pay_date, scid, scc)
    pension_pct = decimalize(pension_employee_percent)
    pension_fixed = decimalize(pension_employee_fixed_amount)
    pension_deduction = (taxable_gross * pension_pct / 100).quantize(Decimal('0.01')) if pension_pct else Decimal('0')
    if pension_fixed:
        if pr_days is not None:
            pension_fixed_deduction = ((pension_fixed / denom) * Decimal(pr_days)).quantize(Decimal('0.01'))
        else:
            pension_fixed_deduction = (pension_fixed * factor).quantize(Decimal('0.01'))
    else:
        pension_fixed_deduction = Decimal('0')
    if pension_fixed_deduction < 0:
        pension_fixed_deduction = Decimal('0')
    pension_total_for_month = (pension_deduction + pension_fixed_deduction).quantize(Decimal('0.01'))
    pension_tax_deductible = pension_total_for_month
    if scc == 'KE':
        pension_tax_deductible = min(pension_total_for_month, KENYA_PENSION_TAX_DEDUCTIBLE_CAP)
    taxable_pay = (taxable_gross - nssf_emp - shif - housing_levy - pension_tax_deductible).quantize(
        Decimal('0.01')
    )
    if taxable_pay < 0:
        taxable_pay = Decimal('0')
    paye = calculate_paye(taxable_pay, pay_date, scid, scc)
    recurring_lines = (
        get_recurring_deduction_line_items(employee_id, pay_date, gross_pay, decimalize(basic_salary))
        if employee_id
        else []
    )
    manual_lines = list(manual_deduction_lines or [])
    extra_lines = recurring_lines + manual_lines
    legacy_other = decimalize(other_deductions)
    other_ded = legacy_other + sum((x['amount'] for x in extra_lines), start=Decimal('0'))
    other_ded = other_ded.quantize(Decimal('0.01'))
    total_deductions = (
        nssf_emp + shif + housing_levy + paye + pension_deduction + pension_fixed_deduction + other_ded
    )
    net_pay = (taxable_gross - total_deductions + non_taxable_earnings).quantize(Decimal('0.01'))
    deductions_breakdown = []
    for row in nssf_breakdown:
        deductions_breakdown.append(
            {
                'code': f"NSSF_TIER{row['tier_number']}",
                'name': f"NSSF (Tier {row['tier_number']})",
                'amount': float(row['employee']),
            }
        )
    if not nssf_breakdown:
        deductions_breakdown.append({'code': 'NSSF', 'name': 'NSSF', 'amount': float(nssf_emp)})
    ext = [
        {'code': 'SHIF', 'name': 'SHIF', 'amount': float(shif)},
        {'code': 'HOUSING_LEVY', 'name': 'Housing Levy', 'amount': float(housing_levy)},
        {'code': 'PAYE', 'name': 'PAYE', 'amount': float(paye)},
    ]
    for x in extra_lines:
        ext.append({'code': x['code'], 'name': x['name'], 'amount': float(x['amount'])})
    if legacy_other and legacy_other > 0:
        ext.append({'code': 'OTHER', 'name': 'Other Deductions (legacy)', 'amount': float(legacy_other)})
    if pension_deduction and pension_deduction > 0:
        ext.insert(-1, {'code': 'PENSION_PERCENT', 'name': 'Pension (%)', 'amount': float(pension_deduction)})
    if pension_fixed_deduction and pension_fixed_deduction > 0:
        ext.insert(-1, {'code': 'PENSION_FIXED', 'name': 'Pension (Fixed)', 'amount': float(pension_fixed_deduction)})
    deductions_breakdown.extend(ext)

    return {
        'gross_pay': gross_pay,
        'taxable_gross': taxable_gross,
        'non_taxable_earnings': non_taxable_earnings,
        'pensionable_pay': pensionable,
        'nssf_employee': nssf_emp,
        'nssf_employer': nssf_empr,
        'shif': shif,
        'housing_levy': housing_levy,
        'pension_deduction': pension_deduction,
        'pension_fixed_deduction': pension_fixed_deduction,
        'pension_tax_deductible': pension_tax_deductible,
        'taxable_pay': taxable_pay,
        'paye': paye,
        'other_deductions': other_ded,
        'total_deductions': total_deductions,
        'net_pay': net_pay,
        'earnings_breakdown': earnings_breakdown,
        'deductions_breakdown': deductions_breakdown,
        'payroll_engine': 'kenya',
    }
