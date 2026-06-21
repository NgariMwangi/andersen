"""Kenya payroll: non-taxable benefits add to net without increasing PAYE."""
from datetime import date
from decimal import Decimal

import pytest

from app import create_app
from app.extensions import db
from app.models.company import Company
from app.services.company_bootstrap import bootstrap_company_defaults
from app.services.payroll_engine import calculate_employee_payroll
from config import TestingConfig


@pytest.fixture
def app():
    return create_app(TestingConfig)


@pytest.fixture
def app_ctx(app):
    with app.app_context():
        yield


@pytest.fixture
def tenant_company(app_ctx):
    db.create_all()
    c = Company(name='Test Co KE', is_active=True)
    db.session.add(c)
    db.session.commit()
    bootstrap_company_defaults(c.id, 'KE')
    return c.id


def test_non_taxable_benefit_adds_to_net_not_paye(app_ctx, tenant_company):
    cid = tenant_company
    base = calculate_employee_payroll(
        basic_salary=Decimal('100000'),
        pay_date=date(2026, 6, 1),
        statutory_company_id=cid,
        statutory_country_code='KE',
    )
    with_benefit = calculate_employee_payroll(
        basic_salary=Decimal('100000'),
        pay_date=date(2026, 6, 1),
        allowance_breakdown=[
            {
                'amount': Decimal('5000'),
                'is_taxable': False,
                'is_pensionable': False,
                'prorate': False,
                'code': 'BEN-1',
                'name': 'Medical reimbursement',
            },
        ],
        statutory_company_id=cid,
        statutory_country_code='KE',
    )

    assert with_benefit['gross_pay'] == base['gross_pay'] + Decimal('5000.00')
    assert with_benefit['paye'] == base['paye']
    assert with_benefit['nssf_employee'] == base['nssf_employee']
    assert with_benefit['net_pay'] == base['net_pay'] + Decimal('5000.00')
    assert with_benefit['non_taxable_earnings'] == Decimal('5000.00')
