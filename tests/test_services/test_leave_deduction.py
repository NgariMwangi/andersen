"""HR manual leave deduction helpers."""
from decimal import Decimal
from types import SimpleNamespace

from app.services.leave_balance_service import (
    deduction_days_from_adjusted,
    effective_entitlement_for_year,
    year_book_limit_from_snapshot,
)


class _LeaveType:
    def __init__(self, days_per_year=None):
        self.days_per_year = days_per_year


def test_deduction_days_from_negative_adjusted():
    assert deduction_days_from_adjusted(Decimal('-6')) == Decimal('6.00')
    assert deduction_days_from_adjusted(Decimal('0')) == Decimal('0.00')
    assert deduction_days_from_adjusted(Decimal('3')) == Decimal('0.00')


def test_effective_entitlement_subtracts_deduction():
    lt = _LeaveType(days_per_year=Decimal('21'))
    assert effective_entitlement_for_year(lt, Decimal('6')) == Decimal('15.00')
    assert effective_entitlement_for_year(lt, Decimal('0')) == Decimal('21.00')
    assert effective_entitlement_for_year(lt, Decimal('25')) == Decimal('0.00')


def test_year_book_limit_includes_deduction():
    snap = {
        'opening_balance': Decimal('0'),
        'accrued': Decimal('14'),
        'adjusted': Decimal('-6'),
    }
    assert year_book_limit_from_snapshot(snap) == Decimal('8.00')


def test_leave_type_supports_hr_deduction():
    from types import SimpleNamespace
    from app.services.leave_balance_service import leave_type_supports_hr_deduction

    annual = SimpleNamespace(is_active=True, days_per_year=Decimal('21'))
    unpaid = SimpleNamespace(is_active=True, days_per_year=Decimal('0'))
    assert leave_type_supports_hr_deduction(annual) is True
    assert leave_type_supports_hr_deduction(unpaid) is False
