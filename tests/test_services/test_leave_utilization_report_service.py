"""Leave utilization report aggregation."""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.extensions import db
from app.models.company import Branch, Company
from app.models.department import Department
from app.models.employee import Employee
from app.models.leave import LeaveRequest, LeaveType
from app.services.leave_utilization_report_service import build_leave_utilization_report


@pytest.fixture
def leave_report_seed(db_session):
    company = Company(name='Leave Report Co', is_active=True)
    db_session.add(company)
    db_session.flush()

    branch = Branch(company_id=company.id, name='Nairobi', country_code='KE')
    dept_eng = Department(company_id=company.id, name='Engineering')
    dept_hr = Department(company_id=company.id, name='HR')
    db_session.add_all([branch, dept_eng, dept_hr])
    db_session.flush()

    annual = LeaveType(
        company_id=company.id,
        code='ANNUAL',
        name='Annual Leave',
        days_per_year=Decimal('21'),
        accrues_monthly=False,
        is_active=True,
    )
    sick = LeaveType(
        company_id=company.id,
        code='SICK',
        name='Sick Leave',
        days_per_year=Decimal('14'),
        accrues_monthly=False,
        is_active=True,
    )
    db_session.add_all([annual, sick])
    db_session.flush()

    alice = Employee(
        company_id=company.id,
        branch_id=branch.id,
        department_id=dept_eng.id,
        employee_number='E001',
        first_name='Alice',
        last_name='Ngugi',
        gender='Female',
        hire_date=date(2024, 1, 15),
        status='active',
    )
    bob = Employee(
        company_id=company.id,
        branch_id=branch.id,
        department_id=dept_hr.id,
        employee_number='E002',
        first_name='Bob',
        last_name='Otieno',
        gender='Male',
        hire_date=date(2023, 6, 1),
        status='active',
    )
    db_session.add_all([alice, bob])
    db_session.flush()

    year = date.today().year
    approved = LeaveRequest(
        employee_id=alice.id,
        leave_type_id=annual.id,
        start_date=date(year, 3, 3),
        end_date=date(year, 3, 7),
        days_requested=Decimal('5'),
        status='approved',
        reason='Holiday',
    )
    pending = LeaveRequest(
        employee_id=bob.id,
        leave_type_id=sick.id,
        start_date=date(year, 4, 1),
        end_date=date(year, 4, 2),
        days_requested=Decimal('2'),
        status='pending_hr',
        reason='Flu',
        created_at=datetime.utcnow() - timedelta(days=3),
    )
    db_session.add_all([approved, pending])
    db_session.commit()

    return {
        'company_id': company.id,
        'year': year,
        'annual_id': annual.id,
        'sick_id': sick.id,
        'dept_eng_id': dept_eng.id,
        'dept_hr_id': dept_hr.id,
        'alice_id': alice.id,
        'bob_id': bob.id,
    }


def test_leave_utilization_aggregates_used_remaining_and_backlog(leave_report_seed):
    seed = leave_report_seed
    report = build_leave_utilization_report(seed['company_id'], year=seed['year'])

    assert report['summary']['active_employees'] == 2
    assert report['summary']['total_used'] == Decimal('5.00')
    assert report['summary']['employees_with_usage'] == 1
    assert report['summary']['pending_count'] == 1
    assert report['summary']['pending_hr'] == 1
    assert report['summary']['pending_days'] == Decimal('2.00')

    by_type = {row['leave_type_id']: row for row in report['by_leave_type']}
    # Two employees × 21 annual entitlement; Alice used 5 → remaining 37
    assert by_type[seed['annual_id']]['used'] == Decimal('5.00')
    assert by_type[seed['annual_id']]['entitlement'] == Decimal('42.00')
    assert by_type[seed['annual_id']]['remaining'] == Decimal('37.00')

    by_dept = {row['department']: row for row in report['by_department']}
    assert by_dept['Engineering']['used'] == Decimal('5.00')
    assert by_dept['HR']['used'] == Decimal('0.00')

    assert len(report['backlog']) == 1
    assert report['backlog'][0]['employee_name'] == 'Bob Otieno'
    assert report['backlog'][0]['status'] == 'pending_hr'

    # The UI balance table has one row per employee, with leave types pivoted to columns.
    assert len(report['employee_balance_rows']) == 2
    alice = next(
        row for row in report['employee_balance_rows']
        if row['employee_id'] == seed['alice_id']
    )
    assert alice['balances_by_type'][seed['annual_id']]['used'] == Decimal('5.00')
    assert alice['balances_by_type'][seed['annual_id']]['remaining'] == Decimal('16.00')


def test_leave_utilization_filters_by_department_and_type(leave_report_seed):
    seed = leave_report_seed
    report = build_leave_utilization_report(
        seed['company_id'],
        year=seed['year'],
        department_id=seed['dept_eng_id'],
        leave_type_id=seed['annual_id'],
    )

    assert report['summary']['active_employees'] == 1
    assert report['summary']['total_used'] == Decimal('5.00')
    assert report['summary']['pending_count'] == 0
    assert all(r['leave_type_id'] == seed['annual_id'] for r in report['employee_rows'])
    assert all(r['department'] == 'Engineering' for r in report['employee_rows'])
    assert len(report['employee_balance_rows']) == 1
    assert set(report['employee_balance_rows'][0]['balances_by_type']) == {seed['annual_id']}
