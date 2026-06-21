"""
Uganda monthly payroll engine.

Order of operations (standard Uganda practice):
1. Gross pay (cash emoluments, prorated if partial month).
2. LST instalment (Jul–Oct only), based on July-reference monthly income.
3. PAYE on chargeable income = gross − LST (LST is tax-deductible). NSSF is not deducted before PAYE.
4. NSSF employee 5% and employer 10% on gross.
5. Voluntary pension / recurring / manual deductions.
6. Net = gross − PAYE − NSSF − LST − other deductions.

No SHIF or Housing Levy (Kenya-only in this product).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.deduction_service import get_recurring_deduction_line_items
from app.services.payroll_common import build_gross_earnings, decimalize
from app.services.uganda_statutory_service import (
    calculate_uganda_nssf,
    calculate_uganda_paye,
    monthly_lst_installment,
)

ENGINE_COUNTRY_CODE = 'UG'


def calculate_employee_payroll_uganda(
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
    statutory_country_code: str = 'UG',
    overtime_days: Decimal | None = None,
    pay_month: int | None = None,
    pay_year: int | None = None,
    july_gross_for_lst: Decimal | None = None,
) -> dict:
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

    lst_reference_income = decimalize(july_gross_for_lst) if july_gross_for_lst is not None else taxable_gross
    lst = monthly_lst_installment(lst_reference_income, pm)
    chargeable_income = (taxable_gross - lst).quantize(Decimal('0.01'))
    if chargeable_income < 0:
        chargeable_income = Decimal('0')

    paye = calculate_uganda_paye(chargeable_income, pay_date, statutory_company_id, ENGINE_COUNTRY_CODE)
    nssf_emp, nssf_empr = calculate_uganda_nssf(
        taxable_gross, pay_date, statutory_company_id, ENGINE_COUNTRY_CODE
    )

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
        paye + nssf_emp + lst + pension_deduction + pension_fixed_deduction + other_ded
    ).quantize(Decimal('0.01'))
    net_pay = (taxable_gross - total_deductions + non_taxable_earnings).quantize(Decimal('0.01'))

    deductions_breakdown = [
        {'code': 'NSSF', 'name': 'NSSF (Employee 5%)', 'amount': float(nssf_emp)},
        {'code': 'PAYE', 'name': 'PAYE', 'amount': float(paye)},
    ]
    if lst > 0:
        deductions_breakdown.append({'code': 'LST', 'name': 'Local Service Tax', 'amount': float(lst)})
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

    return {
        'gross_pay': gross_pay,
        'taxable_gross': taxable_gross,
        'non_taxable_earnings': non_taxable_earnings,
        'pensionable_pay': pensionable,
        'nssf_employee': nssf_emp,
        'nssf_employer': nssf_empr,
        'shif': Decimal('0'),
        'housing_levy': Decimal('0'),
        'lst': lst,
        'pension_deduction': pension_deduction,
        'pension_fixed_deduction': pension_fixed_deduction,
        'pension_tax_deductible': Decimal('0'),
        'taxable_pay': chargeable_income,
        'paye': paye,
        'other_deductions': other_ded,
        'total_deductions': total_deductions,
        'net_pay': net_pay,
        'earnings_breakdown': earnings_breakdown,
        'deductions_breakdown': deductions_breakdown,
        'payroll_engine': 'uganda',
        'pay_month': pm,
        'pay_year': py,
    }
