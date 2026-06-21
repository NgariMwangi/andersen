"""Kenya payroll Excel export row building."""
from decimal import Decimal

from app.services.kenya_payroll_export_service import (
    KENYA_NITA_PER_EMPLOYEE,
    basic_salary_total,
    benefits_total,
    compute_kenya_taxes_summary,
    gross_pay_by_department,
    kenya_export_row,
    nssf_employee_employer_total,
    voluntary_pension_total,
    _named_deduction_total,
)


class _FakeDepartment:
    name = 'Head office'


class _FakeJobTitle:
    name = 'Accountant'


class _FakeEmployee:
    full_name = 'Jane Doe'
    employee_number = 'E-1001'
    job_title = _FakeJobTitle()
    department = _FakeDepartment()


class _FakeItem:
    def __init__(self):
        self.employee = _FakeEmployee()
        self.employee_id = 1
        self.gross_pay = Decimal('100000')
        self.taxable_pay = Decimal('85000')
        self.net_pay = Decimal('72000')
        self.shif = Decimal('2750')
        self.nssf_employee = Decimal('4320')
        self.paye = Decimal('15000')
        self.housing_levy = Decimal('1500')
        self.earnings_breakdown = [
            {'code': 'BASIC', 'amount': 80000},
            {'code': 'BEN-1', 'name': 'Bonus', 'amount': 20000},
        ]
        self.deductions_breakdown = [
            {'code': 'NSSF_TIER1', 'name': 'NSSF (Tier 1)', 'amount': 1080},
            {'code': 'NSSF_TIER2', 'name': 'NSSF (Tier 2)', 'amount': 3240},
            {'code': 'SHIF', 'name': 'SHIF', 'amount': 2750},
            {'code': 'HOUSING_LEVY', 'name': 'Housing Levy', 'amount': 1500},
            {'code': 'PAYE', 'name': 'PAYE', 'amount': 15000},
            {'code': 'PENSION_PERCENT', 'name': 'Pension (%)', 'amount': 5000},
            {'code': 'DED_1', 'name': 'Welfare Kit', 'amount': 500},
            {'code': 'DED_2', 'name': 'SHELLOYEES SACCO', 'amount': 3000},
            {'code': 'DED_3', 'name': 'MAISHA BORA SACCO', 'amount': 2000},
        ]


def test_basic_salary_from_breakdown():
    item = _FakeItem()
    assert basic_salary_total(item) == Decimal('80000.00')


def test_benefits_total_sums_ben_lines():
    item = _FakeItem()
    assert benefits_total(item) == Decimal('20000.00')


def test_named_deduction_matching():
    item = _FakeItem()
    assert _named_deduction_total(item, 'WELFARE', 'KIT') == Decimal('500.00')
    assert _named_deduction_total(item, 'SHELLOYEES', 'SACCO') == Decimal('3000.00')
    assert _named_deduction_total(item, 'MAISHA', 'BORA') == Decimal('2000.00')


def test_voluntary_pension_from_breakdown():
    item = _FakeItem()
    assert voluntary_pension_total(item) == Decimal('5000.00')


def test_nssf_employee_employer_is_double():
    assert nssf_employee_employer_total(Decimal('4320')) == Decimal('8640.00')


def test_kenya_export_row():
    item = _FakeItem()
    row = kenya_export_row(item)
    assert row['employee_number'] == 'E-1001'
    assert row['employee_name'] == 'Jane Doe'
    assert row['job_title'] == 'Accountant'
    assert row['basic_salary'] == Decimal('80000.00')
    assert row['benefits'] == Decimal('20000.00')
    assert row['gross_pay'] == Decimal('100000.00')
    assert row['total_nssf'] == Decimal('4320.00')
    assert row['welfare_kit'] == Decimal('500.00')
    assert row['total_deductions'] == Decimal('28000.00')
    assert row['net_pay'] == Decimal('72000.00')


def test_gross_pay_by_department():
    item = _FakeItem()
    rows = gross_pay_by_department([item])
    assert rows == [('Head office', Decimal('100000.00'))]


def test_compute_kenya_taxes_summary():
    item = _FakeItem()

    class _Con:
        consultant_number = '005'
        full_name = 'Sammy Ndolo'

    class _CI:
        gross_pay = Decimal('300000')
        net_pay = Decimal('285000')
        withholding_tax = Decimal('15000')
        consultant_id = 1
        consultant = _Con()

    summary = compute_kenya_taxes_summary([item], [_CI()])
    assert summary['dept_gross'] == [('Head office', Decimal('100000.00'))]
    assert summary['consultant_gross_rows'][0][1] == Decimal('300000.00')
    assert summary['paye'] == Decimal('15000.00')
    assert summary['wht'] == Decimal('15000.00')
    assert summary['nita'] == KENYA_NITA_PER_EMPLOYEE
    assert summary['total_gross'] == Decimal('400000.00')
    assert summary['total_net'] == Decimal('357000.00')
