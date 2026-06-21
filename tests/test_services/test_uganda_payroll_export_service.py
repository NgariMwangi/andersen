"""Uganda payroll Excel export row building."""
from decimal import Decimal

from app.services.uganda_payroll_export_service import (
    total_payroll_cost,
    uganda_export_row,
)


class _FakeJobTitle:
    name = 'Engineer'


class _FakeEmployee:
    full_name = 'John Okello'
    employee_number = 'UG-042'
    job_title = _FakeJobTitle()


class _FakeItem:
    def __init__(self):
        self.employee = _FakeEmployee()
        self.employee_id = 2
        self.gross_pay = Decimal('2000000')
        self.paye = Decimal('450000')
        self.nssf_employee = Decimal('100000')
        self.nssf_employer = Decimal('200000')
        self.net_pay = Decimal('1400000')
        self.earnings_breakdown = [
            {'code': 'BASIC', 'amount': 1800000},
            {'code': 'BEN-1', 'name': 'Allowance', 'amount': 200000},
        ]
        self.deductions_breakdown = [
            {'code': 'NSSF', 'name': 'NSSF (Employee 5%)', 'amount': 100000},
            {'code': 'PAYE', 'name': 'PAYE', 'amount': 450000},
            {'code': 'DED_1', 'name': 'Welfare Kit', 'amount': 50000},
        ]


def test_total_payroll_cost():
    item = _FakeItem()
    assert total_payroll_cost(item) == Decimal('2200000.00')


def test_uganda_export_row():
    item = _FakeItem()
    row = uganda_export_row(item)
    assert row['employee_number'] == 'UG-042'
    assert row['employee_name'] == 'John Okello'
    assert row['job_title'] == 'Engineer'
    assert row['basic_salary'] == Decimal('1800000.00')
    assert row['benefits'] == Decimal('200000.00')
    assert row['gross_pay'] == Decimal('2000000.00')
    assert row['nssf'] == Decimal('100000.00')
    assert row['nssf_employer'] == Decimal('200000.00')
    assert row['total_payroll_cost'] == Decimal('2200000.00')
    assert row['total_deductions'] == Decimal('600000.00')
    assert row['welfare_kit'] == Decimal('50000.00')
