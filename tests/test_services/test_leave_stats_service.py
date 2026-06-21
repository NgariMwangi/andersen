"""Leave statistics and gender-based leave type visibility."""
from decimal import Decimal
from types import SimpleNamespace

from app.services.leave_stats_service import (
    leave_type_display_name,
    leave_types_visible_for_gender,
    normalize_gender,
)
from app.services.leave_balance_service import (
    compute_accrued_for_year,
    is_fixed_annual_entitlement_leave,
    leave_type_uses_balance_ledger,
)


class _LeaveType:
    def __init__(self, code, name=None, days_per_year=None, accrues_monthly=False, carry_forward_max=0):
        self.code = code
        self.name = name or code
        self.days_per_year = days_per_year
        self.accrues_monthly = accrues_monthly
        self.carry_forward_max = carry_forward_max
        self.is_active = True


def test_normalize_gender_variants():
    assert normalize_gender('Female') == 'female'
    assert normalize_gender('Male') == 'male'
    assert normalize_gender('F') == 'female'


def test_female_sees_maternity_not_paternity():
    types = [
        _LeaveType('MATERNITY', 'Paternity Leave'),
        _LeaveType('PATERNITY', 'Maternity Leave'),
        _LeaveType('ANNUAL', 'Annual Leave'),
    ]
    visible = leave_types_visible_for_gender(types, 'female')
    codes = {lt.code for lt in visible}
    assert 'MATERNITY' in codes
    assert 'PATERNITY' not in codes


def test_leave_type_display_name_uses_canonical_label():
    lt = _LeaveType('MATERNITY', 'Paternity Leave')
    assert leave_type_display_name(lt) == 'Maternity Leave'


def test_sick_leave_fixed_annual_entitlement():
    sick = _LeaveType('SICK', days_per_year=Decimal('14'), carry_forward_max=10)
    assert is_fixed_annual_entitlement_leave(sick)
    assert leave_type_uses_balance_ledger(sick) is False

    emp = SimpleNamespace(hire_date=None)
    earned = compute_accrued_for_year(sick, emp, 2026, __import__('datetime').date(2026, 6, 1))
    assert earned == Decimal('14.00')
