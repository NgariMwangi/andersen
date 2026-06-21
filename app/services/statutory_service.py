"""
Statutory deduction calculations (Kenya by default).
Uses rates from database with effective dates — scoped per company and country (branch).
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func

from app.extensions import db
from app.models.statutory import StatutoryRate, PayeBracket, NssfTier

# Currency amounts: always round to 2 decimal places (KES cents).
TWO_DP = Decimal('0.01')
NSSF_OPEN_BAND_MAX = Decimal('999999999')


def _cc(country_code: str | None) -> str:
    return (country_code or 'KE').upper()[:2]


def _get_rate(code: str, as_at: date, company_id: int, country_code: str) -> Decimal:
    """Get single rate value for code valid on as_at."""
    cc = _cc(country_code)
    r = (
        db.session.query(StatutoryRate)
        .filter(
            StatutoryRate.company_id == company_id,
            StatutoryRate.country_code == cc,
            StatutoryRate.code == code,
            StatutoryRate.effective_from <= as_at,
            (StatutoryRate.effective_to.is_(None)) | (StatutoryRate.effective_to >= as_at),
        )
        .order_by(StatutoryRate.effective_from.desc())
        .first()
    )
    if not r:
        return Decimal('0')
    return Decimal(str(r.value)).quantize(TWO_DP, rounding=ROUND_HALF_UP)


def get_personal_relief(as_at: date, company_id: int, country_code: str = 'KE') -> Decimal:
    """Personal relief amount (monthly) for PAYE."""
    return _get_rate('PERSONAL_RELIEF', as_at, company_id, country_code)


def get_shif_percent(as_at: date, company_id: int, country_code: str = 'KE') -> Decimal:
    return _get_rate('SHIF_PERCENT', as_at, company_id, country_code)


def get_shif_min_amount(as_at: date, company_id: int, country_code: str = 'KE') -> Decimal:
    return _get_rate('SHIF_MIN_AMOUNT', as_at, company_id, country_code)


def get_housing_levy_percent(as_at: date, company_id: int, country_code: str = 'KE') -> Decimal:
    return _get_rate('HOUSING_LEVY_PERCENT', as_at, company_id, country_code)


def _fetch_nssf_tiers(as_at: date, company_id: int, country_code: str) -> list:
    """
    Use the latest NSSF tier set active on as_at (by effective_from), so overlapping
    seeded rows do not duplicate tiers. If no row is active on as_at (e.g. pay date
    before the first effective_from), fall back to the latest configured set so NSSF
    is not silently zero.
    """
    cc = _cc(country_code)
    active_latest = (
        db.session.query(func.max(NssfTier.effective_from))
        .filter(
            NssfTier.company_id == company_id,
            NssfTier.country_code == cc,
            NssfTier.effective_from <= as_at,
            (NssfTier.effective_to.is_(None)) | (NssfTier.effective_to >= as_at),
        )
        .scalar()
    )
    if active_latest is not None:
        return (
            db.session.query(NssfTier)
            .filter(
                NssfTier.company_id == company_id,
                NssfTier.country_code == cc,
                NssfTier.effective_from == active_latest,
                (NssfTier.effective_to.is_(None)) | (NssfTier.effective_to >= as_at),
            )
            .order_by(NssfTier.tier_number)
            .all()
        )
    latest_any = (
        db.session.query(func.max(NssfTier.effective_from))
        .filter(NssfTier.company_id == company_id, NssfTier.country_code == cc)
        .scalar()
    )
    if latest_any is None:
        return []
    return (
        db.session.query(NssfTier)
        .filter(
            NssfTier.company_id == company_id,
            NssfTier.country_code == cc,
            NssfTier.effective_from == latest_any,
        )
        .order_by(NssfTier.tier_number)
        .all()
    )


def calculate_nssf(
    pensionable_pay: Decimal, as_at: date, company_id: int, country_code: str = 'KE'
) -> tuple:
    """
    NSSF Feb 2026: Tier I first 9,000 (6%+6%), Tier II 9,001-108,000 (6%+6% capped).
    Returns (employee_contribution, employer_contribution).
    """
    tiers = _fetch_nssf_tiers(as_at, company_id, country_code)
    if not tiers:
        return Decimal('0'), Decimal('0')

    emp_total = Decimal('0')
    empr_total = Decimal('0')
    prev_high = Decimal('0')
    for tier in tiers:
        tier_min = Decimal(str(tier.pensionable_min or 0))
        lower = max(prev_high, tier_min)
        high = Decimal(str(tier.pensionable_max)) if tier.pensionable_max is not None else NSSF_OPEN_BAND_MAX
        if pensionable_pay <= lower:
            continue
        taxable_in_tier = min(pensionable_pay, high) - lower
        emp_pct = Decimal(str(tier.employee_percent)) / 100
        empr_pct = Decimal(str(tier.employer_percent)) / 100
        emp_contrib = taxable_in_tier * emp_pct
        empr_contrib = taxable_in_tier * empr_pct
        if tier.employee_max_amount is not None:
            emp_contrib = min(emp_contrib, Decimal(str(tier.employee_max_amount)))
        if tier.employer_max_amount is not None:
            empr_contrib = min(empr_contrib, Decimal(str(tier.employer_max_amount)))
        emp_total += emp_contrib
        empr_total += empr_contrib
        prev_high = high
        if high == NSSF_OPEN_BAND_MAX:
            break
    return emp_total, empr_total


def calculate_nssf_with_breakdown(
    pensionable_pay: Decimal, as_at: date, company_id: int, country_code: str = 'KE'
) -> tuple:
    tiers = _fetch_nssf_tiers(as_at, company_id, country_code)
    if not tiers:
        return Decimal('0'), Decimal('0'), []

    emp_total = Decimal('0')
    empr_total = Decimal('0')
    breakdown = []
    prev_high = Decimal('0')
    for tier in tiers:
        tier_min = Decimal(str(tier.pensionable_min or 0))
        lower = max(prev_high, tier_min)
        high = Decimal(str(tier.pensionable_max)) if tier.pensionable_max is not None else NSSF_OPEN_BAND_MAX
        if pensionable_pay <= lower:
            continue
        taxable_in_tier = min(pensionable_pay, high) - lower
        emp_pct = Decimal(str(tier.employee_percent)) / 100
        empr_pct = Decimal(str(tier.employer_percent)) / 100
        emp_contrib = taxable_in_tier * emp_pct
        empr_contrib = taxable_in_tier * empr_pct
        if tier.employee_max_amount is not None:
            emp_contrib = min(emp_contrib, Decimal(str(tier.employee_max_amount)))
        if tier.employer_max_amount is not None:
            empr_contrib = min(empr_contrib, Decimal(str(tier.employer_max_amount)))
        emp_contrib = emp_contrib.quantize(Decimal('0.01'))
        empr_contrib = empr_contrib.quantize(Decimal('0.01'))
        emp_total += emp_contrib
        empr_total += empr_contrib
        breakdown.append(
            {
                'tier_number': int(tier.tier_number),
                'employee': emp_contrib,
                'employer': empr_contrib,
            }
        )
        prev_high = high
        if high == NSSF_OPEN_BAND_MAX:
            break
    return emp_total, empr_total, breakdown


def calculate_paye_breakdown(
    taxable_pay: Decimal, as_at: date, company_id: int, country_code: str = 'KE'
) -> dict:
    cc = _cc(country_code)
    brackets = (
        db.session.query(PayeBracket)
        .filter(
            PayeBracket.company_id == company_id,
            PayeBracket.country_code == cc,
            PayeBracket.effective_from <= as_at,
            (PayeBracket.effective_to.is_(None)) | (PayeBracket.effective_to >= as_at),
        )
        .order_by(PayeBracket.bracket_order)
        .all()
    )
    z = Decimal('0').quantize(TWO_DP, rounding=ROUND_HALF_UP)
    if not brackets:
        return {'tax_before_relief': z, 'personal_relief_applied': z, 'paye': z}

    taxable_pay = Decimal(str(taxable_pay)).quantize(TWO_DP, rounding=ROUND_HALF_UP)
    tax = Decimal('0')
    prev_ceiling = Decimal('0')
    for br in brackets:
        high = Decimal(str(br.max_amount)) if br.max_amount is not None else Decimal('999999999')
        rate = Decimal(str(br.rate_percent)) / 100
        if taxable_pay <= prev_ceiling:
            break
        band_income = min(taxable_pay, high) - prev_ceiling
        if band_income > 0:
            tier_tax = (band_income * rate).quantize(TWO_DP, rounding=ROUND_HALF_UP)
            tax += tier_tax
        prev_ceiling = high

    relief = get_personal_relief(as_at, company_id, cc)
    tax = tax.quantize(TWO_DP, rounding=ROUND_HALF_UP)
    paye = (tax - relief).quantize(TWO_DP, rounding=ROUND_HALF_UP)
    if paye < 0:
        paye = Decimal('0').quantize(TWO_DP, rounding=ROUND_HALF_UP)
    relief_applied = (tax - paye).quantize(TWO_DP, rounding=ROUND_HALF_UP)
    return {
        'tax_before_relief': tax,
        'personal_relief_applied': relief_applied,
        'paye': paye,
    }


def calculate_paye(
    taxable_pay: Decimal, as_at: date, company_id: int, country_code: str = 'KE'
) -> Decimal:
    return calculate_paye_breakdown(taxable_pay, as_at, company_id, country_code)['paye']


def calculate_shif(
    gross_pay: Decimal, as_at: date, company_id: int, country_code: str = 'KE'
) -> Decimal:
    pct = get_shif_percent(as_at, company_id, country_code)
    min_amount = get_shif_min_amount(as_at, company_id, country_code)
    percent_amount = (gross_pay * pct / 100).quantize(Decimal('0.01'))
    return max(percent_amount, min_amount.quantize(Decimal('0.01')))


def calculate_housing_levy(
    gross_pay: Decimal, as_at: date, company_id: int, country_code: str = 'KE'
) -> Decimal:
    pct = get_housing_levy_percent(as_at, company_id, country_code)
    return (gross_pay * pct / 100).quantize(Decimal('0.01'))


def get_pensionable_pay(
    basic_salary: Decimal, house_allowance: Decimal, other_pensionable: Decimal = None
) -> Decimal:
    """Pensionable pay for NSSF = basic + house allowance (typically)."""
    other = other_pensionable or Decimal('0')
    return (basic_salary + house_allowance + other).quantize(Decimal('0.01'))
