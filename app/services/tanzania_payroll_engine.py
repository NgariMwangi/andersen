"""
Tanzania Mainland monthly payroll engine.

Order of operations:
1. Gross pay (cash emoluments, prorated if partial month).
2. NSSF employee 10% and employer 10% on gross (no cap).
3. Taxable pay = gross − NSSF employee.
4. PAYE and surtax on taxable pay.
5. SDL and WCF — employer-only (tracked for cost reporting, not net pay).
6. Voluntary pension / recurring / manual deductions.
7. Net = gross − PAYE − surtax − NSSF employee − other employee deductions.

No SHIF or Housing Levy (Kenya-only in this product).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.deduction_service import get_recurring_deduction_line_items
from app.services.payroll_common import build_gross_earnings, decimalize
from app.services.tanzania_statutory_service import (
    calculate_tanzania_nssf,
    calculate_tanzania_paye,
    calculate_tanzania_sdl,
    calculate_tanzania_surtax,
    calculate_tanzania_wcf,
)

ENGINE_COUNTRY_CODE = 'TZ'


def calculate_employee_payroll_tanzania(
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
    statutory_country_code: str = 'TZ',
    overtime_days: Decimal | None = None,
    pay_month: int | None = None,
    pay_year: int | None = None,
    july_gross_for_lst: Decimal | None = None,
) -> dict:
    del july_gross_for_lst  # Uganda-only; accepted for router signature compatibility

    pay_date = pay_date or date.today()
    pm = pay_month or pay_date.month
    py = pay_year or pay_date.year

    earnings = build_gross_earnings(
        basic_salary=basic_salary,
        house_allowance=house_allowance,
        transport_allowance=transport_allowance,
        meal_allowance=meal_allowance,
        other_allowances=other_allowances,
        pro_rata_factor=pro_rata_factor,
        pro_rata_calendar_days=pro_rata_calendar_days,
        other_earnings=other_earnings,
        allowance_breakdown=allowance_breakdown,
        overtime_days=overtime_days,
    )
    gross_pay = earnings.gross_pay
    taxable_gross = earnings.taxable_gross
    non_taxable_earnings = earnings.non_taxable_earnings
    pensionable = earnings.pensionable_pay
    earnings_breakdown = earnings.earnings_breakdown

    if statutory_company_id is None:
        raise ValueError('statutory_company_id is required for payroll calculation')

    cc = (statutory_country_code or ENGINE_COUNTRY_CODE).upper()[:2]
    nssf_emp, nssf_empr = calculate_tanzania_nssf(taxable_gross, pay_date, statutory_company_id, cc)
    taxable_pay = (taxable_gross - nssf_emp).quantize(Decimal('0.01'))
    if taxable_pay < 0:
        taxable_pay = Decimal('0')

    paye = calculate_tanzania_paye(taxable_pay, pay_date, statutory_company_id, cc)
    surtax = calculate_tanzania_surtax(taxable_pay, pay_date, statutory_company_id, cc)
    sdl_empr = calculate_tanzania_sdl(taxable_gross, pay_date, statutory_company_id, cc)
    wcf_empr = calculate_tanzania_wcf(taxable_gross, pay_date, statutory_company_id, cc)

    factor = decimalize(pro_rata_factor) if pro_rata_factor is not None else Decimal('1')
    pr_days = pro_rata_calendar_days
    denom = Decimal('30')
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

    recurring_lines = (
        get_recurring_deduction_line_items(employee_id, pay_date, gross_pay, decimalize(basic_salary))
        if employee_id
        else []
    )
    manual_lines = list(manual_deduction_lines or [])
    legacy_other = decimalize(other_deductions)
    extra_lines = recurring_lines + manual_lines
    other_ded = legacy_other + sum((x['amount'] for x in extra_lines), start=Decimal('0'))
    other_ded = other_ded.quantize(Decimal('0.01'))

    total_deductions = (
        paye + surtax + nssf_emp + pension_deduction + pension_fixed_deduction + other_ded
    ).quantize(Decimal('0.01'))
    net_pay = (taxable_gross - total_deductions + non_taxable_earnings).quantize(Decimal('0.01'))

    deductions_breakdown = [
        {'code': 'NSSF', 'name': 'NSSF (Employee)', 'amount': float(nssf_emp)},
        {'code': 'PAYE', 'name': 'PAYE', 'amount': float(paye)},
    ]
    if surtax > 0:
        deductions_breakdown.append({'code': 'SURTAX', 'name': 'Income Tax Surtax', 'amount': float(surtax)})
    for x in extra_lines:
        deductions_breakdown.append({'code': x['code'], 'name': x['name'], 'amount': float(x['amount'])})
    if legacy_other and legacy_other > 0:
        deductions_breakdown.append(
            {'code': 'OTHER', 'name': 'Other Deductions (legacy)', 'amount': float(legacy_other)}
        )
    if pension_deduction > 0:
        deductions_breakdown.append(
            {'code': 'PENSION_PERCENT', 'name': 'Pension (%)', 'amount': float(pension_deduction)}
        )
    if pension_fixed_deduction > 0:
        deductions_breakdown.append(
            {'code': 'PENSION_FIXED', 'name': 'Pension (Fixed)', 'amount': float(pension_fixed_deduction)}
        )

    employer_contributions = [
        {'code': 'NSSF_EMPLOYER', 'name': 'NSSF (Employer)', 'amount': float(nssf_empr)},
        {'code': 'SDL', 'name': 'Skills Development Levy', 'amount': float(sdl_empr)},
        {'code': 'WCF', 'name': 'Workers Compensation Fund', 'amount': float(wcf_empr)},
    ]

    return {
        'gross_pay': gross_pay,
        'taxable_gross': taxable_gross,
        'non_taxable_earnings': non_taxable_earnings,
        'pensionable_pay': pensionable,
        'nssf_employee': nssf_emp,
        'nssf_employer': nssf_empr,
        'sdl_employer': sdl_empr,
        'wcf_employer': wcf_empr,
        'shif': Decimal('0'),
        'housing_levy': Decimal('0'),
        'lst': Decimal('0'),
        'surtax': surtax,
        'pension_deduction': pension_deduction,
        'pension_fixed_deduction': pension_fixed_deduction,
        'pension_tax_deductible': Decimal('0'),
        'taxable_pay': taxable_pay,
        'paye': paye,
        'other_deductions': other_ded,
        'total_deductions': total_deductions,
        'net_pay': net_pay,
        'earnings_breakdown': earnings_breakdown,
        'deductions_breakdown': deductions_breakdown,
        'employer_contributions': employer_contributions,
        'payroll_engine': 'tanzania',
        'pay_month': pm,
        'pay_year': py,
    }
