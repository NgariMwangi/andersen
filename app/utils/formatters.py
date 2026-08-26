"""Currency, date, and display formatting for Kenya."""
from decimal import Decimal
from datetime import date, datetime, timedelta, timezone

# Server stores naive UTC; Kenya (Africa/Nairobi) is UTC+3 with no DST.
DISPLAY_UTC_OFFSET = timedelta(hours=3)
DEFAULT_DATETIME_FORMAT = '%d %b %Y %H:%M'


def to_local_datetime(value):
    """
    Convert a DB datetime (naive UTC) to local display time (+3 hours).
    Pure date values are returned unchanged.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        try:
            from zoneinfo import ZoneInfo
            from flask import has_app_context, current_app

            tz_name = 'Africa/Nairobi'
            if has_app_context():
                tz_name = current_app.config.get('TIMEZONE') or tz_name
            utc_dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
            return utc_dt.astimezone(ZoneInfo(tz_name)).replace(tzinfo=None)
        except Exception:
            naive = value.replace(tzinfo=None) if value.tzinfo is not None else value
            return naive + DISPLAY_UTC_OFFSET
    if isinstance(value, date):
        return value
    return value


def format_local_datetime(value, fmt=DEFAULT_DATETIME_FORMAT) -> str:
    """Format a DB datetime for UI display in local time (+3h)."""
    if value is None:
        return ''
    local = to_local_datetime(value)
    if local is None:
        return ''
    if isinstance(local, datetime):
        return local.strftime(fmt or DEFAULT_DATETIME_FORMAT)
    if isinstance(local, date):
        return local.strftime(fmt or '%d %b %Y')
    return str(local)


def format_currency(value, currency='KES') -> str:
    """Format as Kenyan Shillings."""
    if value is None:
        return f'{currency} 0.00'
    if isinstance(value, (int, float)):
        value = Decimal(str(value))
    return f'{currency} {value:,.2f}'


def format_date(d) -> str:
    """Format date for display. Datetimes are shown in local time (+3h)."""
    if d is None:
        return ''
    if isinstance(d, datetime):
        return format_local_datetime(d, '%d %b %Y')
    if isinstance(d, date):
        return d.strftime('%d %b %Y')
    return str(d)


def mask_bank_account(number: str, visible=4) -> str:
    """Mask bank account: show last 4 digits."""
    if not number or len(number) <= visible:
        return number or ''
    return '*' * (len(number) - visible) + number[-visible:]
