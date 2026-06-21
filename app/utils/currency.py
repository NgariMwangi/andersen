"""ISO 4217 currency helpers for multi-country tenants (aligned with branch country)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.company import Branch
    from app.models.employee import Employee


# Default payroll/display currency when branch has no explicit currency_code.
DEFAULT_CURRENCY_BY_COUNTRY: dict[str, str] = {
    'KE': 'KES',
    'UG': 'UGX',
    'TZ': 'TZS',
    'RW': 'RWF',
    'ET': 'ETB',
    'ZA': 'ZAR',
    'NG': 'NGN',
    'GH': 'GHS',
}


def currency_for_country(country_code: str | None, *, app_default: str = 'KES') -> str:
    cc = (country_code or 'KE').strip().upper()[:2]
    return DEFAULT_CURRENCY_BY_COUNTRY.get(cc, app_default)


def currency_for_branch(branch: 'Branch | None', *, app_default: str = 'KES') -> str:
    if branch is None:
        return app_default
    raw = getattr(branch, 'currency_code', None)
    if raw and str(raw).strip():
        return str(raw).strip().upper()[:3]
    return currency_for_country(getattr(branch, 'country_code', None), app_default=app_default)


def currency_for_employee(emp: 'Employee | None', *, app_default: str = 'KES') -> str:
    if emp is None:
        return app_default
    return currency_for_branch(getattr(emp, 'branch', None), app_default=app_default)
