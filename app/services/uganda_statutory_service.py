"""
Uganda statutory payroll: PAYE (URA monthly bands), NSSF (5% / 10% on gross), LST (Jul–Oct).

References: URA PAYE monthly tables, NSSF Act (gross wages), Local Service Tax Act / Sage UG guide.
PAYE is on chargeable monthly income (gross cash emoluments). NSSF is not deductible for PAYE in Uganda.
LST (when due) reduces income subject to PAYE. LST applies only in July–October (financial year Q1).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from app.services.statutory_service import (
    TWO_DP,
    _cc,
    _get_rate,
    calculate_paye,
    calculate_paye_breakdown,
)

# Annual LST by monthly income (July reference income). (exclusive_min, inclusive_max, annual_lst)
# Income must exceed 100,000 UGX/month to attract LST (Sage / LST guide).
DEFAULT_LST_BANDS: tuple[tuple[Decimal, Decimal | None, Decimal], ...] = (
    (Decimal('0'), Decimal('100000'), Decimal('0')),
    (Decimal('100000'), Decimal('200000'), Decimal('5000')),
    (Decimal('200000'), Decimal('300000'), Decimal('10000')),
    (Decimal('300000'), Decimal('400000'), Decimal('20000')),
    (Decimal('400000'), Decimal('500000'), Decimal('30000')),
    (Decimal('500000'), Decimal('600000'), Decimal('40000')),
    (Decimal('600000'), Decimal('700000'), Decimal('60000')),
    (Decimal('700000'), Decimal('800000'), Decimal('70000')),
    (Decimal('800000'), Decimal('900000'), Decimal('80000')),
    (Decimal('900000'), Decimal('1000000'), Decimal('90000')),
    (Decimal('1000000'), None, Decimal('100000')),
)

LST_DEDUCTION_MONTHS = frozenset({7, 8, 9, 10})
DEFAULT_NSSF_EMPLOYEE_PERCENT = Decimal('5')
DEFAULT_NSSF_EMPLOYER_PERCENT = Decimal('10')
DEFAULT_LST_INSTALLMENTS = 4


def annual_lst_amount(monthly_income: Decimal) -> Decimal:
    """Annual local service tax from July-reference monthly income."""
    income = Decimal(str(monthly_income)).quantize(TWO_DP, rounding=ROUND_HALF_UP)
    if income <= Decimal('100000'):
        return Decimal('0')
    for low, high, annual in DEFAULT_LST_BANDS:
        if income <= low:
            continue
        if high is None or income <= high:
            return annual
    return Decimal('0')


def monthly_lst_installment(
    monthly_income_for_lst: Decimal,
    pay_month: int,
    *,
    lst_installments: int = DEFAULT_LST_INSTALLMENTS,
) -> Decimal:
    """
    LST withheld this month (0 outside Jul–Oct).
    Default: annual LST ÷ 4 for each of the four LST months.
    """
    if pay_month not in LST_DEDUCTION_MONTHS:
        return Decimal('0')
    annual = annual_lst_amount(monthly_income_for_lst)
    if annual <= 0 or lst_installments <= 0:
        return Decimal('0')
    return (annual / Decimal(lst_installments)).quantize(TWO_DP, rounding=ROUND_HALF_UP)


def calculate_uganda_nssf(
    gross_pay: Decimal,
    as_at: date,
    company_id: int,
    country_code: str = 'UG',
) -> tuple[Decimal, Decimal]:
    """NSSF: employee 5% and employer 10% of gross monthly wages (configurable rates)."""
    cc = _cc(country_code)
    emp_pct = _get_rate('NSSF_EMPLOYEE_PERCENT', as_at, company_id, cc)
    empr_pct = _get_rate('NSSF_EMPLOYER_PERCENT', as_at, company_id, cc)
    if emp_pct <= 0:
        emp_pct = DEFAULT_NSSF_EMPLOYEE_PERCENT
    if empr_pct <= 0:
        empr_pct = DEFAULT_NSSF_EMPLOYER_PERCENT
    gross = Decimal(str(gross_pay)).quantize(TWO_DP, rounding=ROUND_HALF_UP)
    emp = (gross * emp_pct / 100).quantize(TWO_DP, rounding=ROUND_HALF_UP)
    empr = (gross * empr_pct / 100).quantize(TWO_DP, rounding=ROUND_HALF_UP)
    return emp, empr


def calculate_uganda_paye(
    chargeable_income: Decimal,
    as_at: date,
    company_id: int,
    country_code: str = 'UG',
) -> Decimal:
    """PAYE on monthly chargeable income using company PAYE brackets for UG."""
    return calculate_paye(chargeable_income, as_at, company_id, country_code)


def calculate_uganda_paye_breakdown(
    chargeable_income: Decimal,
    as_at: date,
    company_id: int,
    country_code: str = 'UG',
) -> dict:
    return calculate_paye_breakdown(chargeable_income, as_at, company_id, country_code)
