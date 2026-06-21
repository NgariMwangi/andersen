"""Calculation helpers for casual worker payouts."""
from decimal import Decimal, ROUND_HALF_UP


MONEY_PLACES = Decimal('0.01')


def _to_decimal(value) -> Decimal:
    if value is None:
        return Decimal('0')
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def calc_casual_payment(days_worked, rate_per_day, adjustments=0):
    """Return gross/net amounts for a casual payout line."""
    days = max(_to_decimal(days_worked), Decimal('0'))
    rate = max(_to_decimal(rate_per_day), Decimal('0'))
    adj = _to_decimal(adjustments)

    gross = (days * rate).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)
    net = (gross + adj).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)
    return {
        'gross_amount': gross,
        'net_amount': net,
    }
