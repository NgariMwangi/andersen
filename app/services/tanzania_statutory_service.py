"""
Tanzania Mainland statutory payroll: PAYE (TRA monthly bands), NSSF (10% / 10% on gross),
SDL and WCF (employer-only), monthly surtax above TZS 10M.

References: TRA PAYE tables, NSSF Act, Vocational Education and Training Act (SDL),
Workers Compensation Act (WCF). Zanzibar uses different PAYE/SDL bands — configure separately if needed.
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

DEFAULT_NSSF_EMPLOYEE_PERCENT = Decimal('10')
DEFAULT_NSSF_EMPLOYER_PERCENT = Decimal('10')
DEFAULT_SDL_PERCENT = Decimal('3.5')
DEFAULT_WCF_PERCENT = Decimal('1')  # private sector; public sector often 0.5%
DEFAULT_SURTAX_PERCENT = Decimal('10')
DEFAULT_SURTAX_THRESHOLD = Decimal('10000000')


def calculate_tanzania_nssf(
    gross_pay: Decimal,
    as_at: date,
    company_id: int,
    country_code: str = 'TZ',
) -> tuple[Decimal, Decimal]:
    """NSSF: employee and employer shares on gross monthly wages (no statutory cap)."""
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


def calculate_tanzania_sdl(
    gross_pay: Decimal,
    as_at: date,
    company_id: int,
    country_code: str = 'TZ',
) -> Decimal:
    """Skills Development Levy — employer cost only (Mainland default 3.5% of gross emoluments)."""
    cc = _cc(country_code)
    pct = _get_rate('SDL_PERCENT', as_at, company_id, cc)
    if pct <= 0:
        pct = DEFAULT_SDL_PERCENT
    gross = Decimal(str(gross_pay)).quantize(TWO_DP, rounding=ROUND_HALF_UP)
    return (gross * pct / 100).quantize(TWO_DP, rounding=ROUND_HALF_UP)


def calculate_tanzania_wcf(
    gross_pay: Decimal,
    as_at: date,
    company_id: int,
    country_code: str = 'TZ',
) -> Decimal:
    """Workers Compensation Fund — employer cost only."""
    cc = _cc(country_code)
    pct = _get_rate('WCF_PERCENT', as_at, company_id, cc)
    if pct <= 0:
        pct = DEFAULT_WCF_PERCENT
    gross = Decimal(str(gross_pay)).quantize(TWO_DP, rounding=ROUND_HALF_UP)
    return (gross * pct / 100).quantize(TWO_DP, rounding=ROUND_HALF_UP)


def calculate_tanzania_surtax(
    taxable_income: Decimal,
    as_at: date,
    company_id: int,
    country_code: str = 'TZ',
) -> Decimal:
    """Additional 10% on monthly taxable income above TZS 10,000,000 (configurable)."""
    cc = _cc(country_code)
    threshold = _get_rate('SURTAX_THRESHOLD', as_at, company_id, cc)
    if threshold <= 0:
        threshold = DEFAULT_SURTAX_THRESHOLD
    pct = _get_rate('SURTAX_PERCENT', as_at, company_id, cc)
    if pct <= 0:
        pct = DEFAULT_SURTAX_PERCENT
    income = Decimal(str(taxable_income)).quantize(TWO_DP, rounding=ROUND_HALF_UP)
    if income <= threshold:
        return Decimal('0')
    excess = (income - threshold).quantize(TWO_DP, rounding=ROUND_HALF_UP)
    return (excess * pct / 100).quantize(TWO_DP, rounding=ROUND_HALF_UP)


def calculate_tanzania_paye(
    taxable_income: Decimal,
    as_at: date,
    company_id: int,
    country_code: str = 'TZ',
) -> Decimal:
    """PAYE from progressive monthly brackets (TRA Mainland resident)."""
    return calculate_paye(taxable_income, as_at, company_id, country_code)


def calculate_tanzania_paye_breakdown(
    taxable_income: Decimal,
    as_at: date,
    company_id: int,
    country_code: str = 'TZ',
) -> dict:
    return calculate_paye_breakdown(taxable_income, as_at, company_id, country_code)
