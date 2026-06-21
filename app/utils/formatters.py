"""Currency, date, and display formatting for Kenya."""
from decimal import Decimal
from datetime import date, datetime


def format_currency(value, currency='KES') -> str:
    """Format as Kenyan Shillings."""
    if value is None:
        return f'{currency} 0.00'
    if isinstance(value, (int, float)):
        value = Decimal(str(value))
    return f'{currency} {value:,.2f}'


def format_date(d) -> str:
    """Format date for display."""
    if d is None:
        return ''
    if isinstance(d, datetime):
        return d.strftime('%d %b %Y')
    if isinstance(d, date):
        return d.strftime('%d %b %Y')
    return str(d)


def mask_bank_account(number: str, visible=4) -> str:
    """Mask bank account: show last 4 digits."""
    if not number or len(number) <= visible:
        return number or ''
    return '*' * (len(number) - visible) + number[-visible:]
