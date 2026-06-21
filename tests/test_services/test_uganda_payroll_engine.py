"""Uganda payroll engine tests."""
from datetime import date
from decimal import Decimal

import pytest
from app import create_app
from app.extensions import db
from app.models.company import Company
from app.services.uganda_payroll_engine import calculate_employee_payroll_uganda
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
    c = Company(name='Test Co UG', is_active=True)
    db.session.add(c)
    db.session.commit()
    return c.id

from app.services.uganda_statutory_service import (
    annual_lst_amount,
    monthly_lst_installment,
    calculate_uganda_nssf,
)


def test_annual_lst_bands():
    assert annual_lst_amount(Decimal('50000')) == Decimal('0')
    assert annual_lst_amount(Decimal('150000')) == Decimal('5000')
    assert annual_lst_amount(Decimal('500000')) == Decimal('30000')
    assert annual_lst_amount(Decimal('1500000')) == Decimal('100000')


def test_monthly_lst_july_october_only():
    assert monthly_lst_installment(Decimal('500000'), 6) == Decimal('0')
    assert monthly_lst_installment(Decimal('500000'), 7) == Decimal('10000')
    assert monthly_lst_installment(Decimal('500000'), 11) == Decimal('0')


def test_nssf_five_ten_percent():
    emp, empr = calculate_uganda_nssf(Decimal('1500000'), date(2026, 7, 1), company_id=1)
    assert emp == Decimal('75000.00')
    assert empr == Decimal('150000.00')


def test_paye_on_gross_minus_lst(app_ctx, tenant_company):
    """1.5M gross, 2026 UG bands: PAYE ~225,500; NSSF 75k; net after PAYE+NSSF only in non-LST month."""
    cid = tenant_company
    from app.models.statutory import PayeBracket, StatutoryRate
    from app.extensions import db

    eff = date(2026, 7, 1)
    for order, min_a, max_a, rate in [
        (1, 0, 335000, 0),
        (2, 335001, 410000, 10),
        (3, 410001, 10000000, 20),
        (4, 10000001, None, 30),
    ]:
        db.session.add(
            PayeBracket(
                company_id=cid,
                country_code='UG',
                effective_from=eff,
                bracket_order=order,
                min_amount=min_a,
                max_amount=max_a,
                rate_percent=rate,
            )
        )
    for code, val in [('NSSF_EMPLOYEE_PERCENT', 5), ('NSSF_EMPLOYER_PERCENT', 10)]:
        db.session.add(
            StatutoryRate(
                company_id=cid,
                country_code='UG',
                code=code,
                effective_from=eff,
                value=val,
            )
        )
    db.session.commit()

    calc = calculate_employee_payroll_uganda(
        basic_salary=Decimal('1500000'),
        pay_date=date(2026, 6, 1),
        statutory_company_id=cid,
        pay_month=6,
        pay_year=2026,
    )
    assert calc['gross_pay'] == Decimal('1500000.00')
    assert calc['nssf_employee'] == Decimal('75000.00')
    assert calc['paye'] == Decimal('225500.00')
    assert calc['shif'] == Decimal('0')
    assert calc['housing_levy'] == Decimal('0')
    assert calc['lst'] == Decimal('0')
    assert calc['net_pay'] == Decimal('1199500.00')
