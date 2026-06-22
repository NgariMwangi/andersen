"""How employee basic salary is stored (annual vs monthly)."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from flask import current_app


def salary_basis() -> str:
    raw = (current_app.config.get('SALARY_BASIS') or 'annual').strip().lower()
    return 'monthly' if raw == 'monthly' else 'annual'


def salary_is_annual() -> bool:
    return salary_basis() == 'annual'


def basic_salary_field_label() -> str:
    return 'Annual basic salary' if salary_is_annual() else 'Monthly basic salary'


def basic_salary_column_label() -> str:
    return 'Basic (per annum)' if salary_is_annual() else 'Basic (per month)'


def monthly_basic_for_payroll(stored_amount) -> Decimal:
    """Convert stored salary to monthly amount for payroll calculation."""
    amt = Decimal(str(stored_amount or 0))
    if salary_is_annual():
        return (amt / Decimal('12')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return amt
