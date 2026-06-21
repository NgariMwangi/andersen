"""Consultant payroll: monthly fee + optional allowances; withholding tax only."""
from decimal import Decimal, ROUND_HALF_UP

from app.services.payroll_engine import decimalize


def calculate_consultant_payroll(
    monthly_fee,
    other_allowances=0,
    withholding_rate: Decimal = None,
    pro_rata_factor: Decimal = None,
    pro_rata_calendar_days: int | None = None,
) -> dict:
    """
    Gross = prorated monthly fee + prorated other allowances.
    Withholding = gross × (withholding_rate / 100). No PAYE/NSSF/SHIF/pension.
    """
    fee = decimalize(monthly_fee)
    other = decimalize(other_allowances)
    rate_pct = decimalize(withholding_rate if withholding_rate is not None else Decimal('5'))

    def prorate_monthly(monthly_val: Decimal) -> Decimal:
        val = decimalize(monthly_val)
        if pro_rata_calendar_days is not None:
            return (val / Decimal('30') * Decimal(pro_rata_calendar_days)).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
        factor = decimalize(pro_rata_factor) if pro_rata_factor is not None else Decimal('1')
        return (val * factor).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    fee_pr = prorate_monthly(fee)
    other_pr = prorate_monthly(other)
    gross = (fee_pr + other_pr).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    wht = (gross * rate_pct / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    net = (gross - wht).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    earnings = []
    if fee_pr > 0:
        earnings.append({'code': 'CONSULTANT_FEE', 'name': 'Consultant fee', 'amount': float(fee_pr)})
    if other_pr > 0:
        earnings.append({'code': 'OTHER_ALLOW', 'name': 'Other allowances', 'amount': float(other_pr)})

    deductions = []
    if wht > 0:
        deductions.append({
            'code': 'WHT',
            'name': f'Withholding tax ({rate_pct}%)',
            'amount': float(wht),
        })

    factor = decimalize(pro_rata_factor) if pro_rata_factor is not None else Decimal('1')
    is_pro_rata = pro_rata_calendar_days is not None or factor < Decimal('1')

    return {
        'gross_pay': gross,
        'withholding_tax': wht,
        'net_pay': net,
        'earnings_breakdown': earnings,
        'deductions_breakdown': deductions,
        'is_pro_rata': is_pro_rata,
    }
