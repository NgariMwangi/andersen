"""Tanzania payroll engine tests."""
from datetime import date
from decimal import Decimal

import pytest
from app import create_app
from app.extensions import db
from app.models.company import Company
from app.services.tanzania_payroll_engine import calculate_employee_payroll_tanzania
from app.services.tanzania_statutory_service import (
    calculate_tanzania_nssf,
    calculate_tanzania_sdl,
    calculate_tanzania_surtax,
    calculate_tanzania_wcf,
)
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
    c = Company(name='Test Co TZ', is_active=True)
    db.session.add(c)
    db.session.commit()
    return c.id


def _seed_tz_statutory(company_id: int) -> None:
    from app.models.statutory import PayeBracket, StatutoryRate

    eff = date(2024, 1, 1)
    for order, min_a, max_a, rate in [
        (1, 0, 270000, 0),
        (2, 270001, 520000, 8),
        (3, 520001, 760000, 20),
        (4, 760001, 1000000, 25),
        (5, 1000001, None, 30),
    ]:
        db.session.add(
            PayeBracket(
                company_id=company_id,
                country_code='TZ',
                effective_from=eff,
                bracket_order=order,
                min_amount=min_a,
                max_amount=max_a,
                rate_percent=rate,
            )
        )
    for code, val in [
        ('NSSF_EMPLOYEE_PERCENT', 10),
        ('NSSF_EMPLOYER_PERCENT', 10),
        ('SDL_PERCENT', 3.5),
        ('WCF_PERCENT', 1),
        ('SURTAX_PERCENT', 10),
        ('SURTAX_THRESHOLD', 10000000),
        ('PERSONAL_RELIEF', 0),
    ]:
        db.session.add(
            StatutoryRate(
                company_id=company_id,
                country_code='TZ',
                code=code,
                effective_from=eff,
                value=val,
            )
        )
    db.session.commit()


def test_nssf_ten_ten_percent():
    emp, empr = calculate_tanzania_nssf(Decimal('1500000'), date(2026, 6, 1), company_id=1)
    assert emp == Decimal('150000.00')
    assert empr == Decimal('150000.00')


def test_sdl_and_wcf_employer_only():
    assert calculate_tanzania_sdl(Decimal('1000000'), date(2026, 6, 1), company_id=1) == Decimal('35000.00')
    assert calculate_tanzania_wcf(Decimal('1000000'), date(2026, 6, 1), company_id=1) == Decimal('10000.00')


def test_surtax_above_ten_million():
    assert calculate_tanzania_surtax(Decimal('9000000'), date(2026, 6, 1), company_id=1) == Decimal('0')
    assert calculate_tanzania_surtax(Decimal('12000000'), date(2026, 6, 1), company_id=1) == Decimal('200000.00')


def test_paye_and_net_1_5m_gross(app_ctx, tenant_company):
    """1.5M gross: NSSF 150k, taxable 1.35M, PAYE 233k, net 1,117,000."""
    cid = tenant_company
    _seed_tz_statutory(cid)

    calc = calculate_employee_payroll_tanzania(
        basic_salary=Decimal('1500000'),
        pay_date=date(2026, 6, 1),
        statutory_company_id=cid,
        pay_month=6,
        pay_year=2026,
    )
    assert calc['gross_pay'] == Decimal('1500000.00')
    assert calc['nssf_employee'] == Decimal('150000.00')
    assert calc['taxable_pay'] == Decimal('1350000.00')
    assert calc['nssf_employer'] == Decimal('150000.00')
    assert calc['paye'] == Decimal('233000.00')
    assert calc['surtax'] == Decimal('0')
    assert calc['sdl_employer'] == Decimal('52500.00')
    assert calc['wcf_employer'] == Decimal('15000.00')
    assert calc['shif'] == Decimal('0')
    assert calc['housing_levy'] == Decimal('0')
    assert calc['net_pay'] == Decimal('1117000.00')
    assert calc['payroll_engine'] == 'tanzania'


def test_router_tz_via_calculate_employee_payroll(app_ctx, tenant_company):
    from app.services.payroll_engine import calculate_employee_payroll

    cid = tenant_company
    _seed_tz_statutory(cid)
    calc = calculate_employee_payroll(
        basic_salary=Decimal('500000'),
        pay_date=date(2026, 6, 1),
        statutory_company_id=cid,
        statutory_country_code='TZ',
    )
    assert calc['payroll_engine'] == 'tanzania'
    assert calc['taxable_pay'] == Decimal('450000.00')
    assert calc['paye'] == Decimal('14400.00')
    assert calc['nssf_employee'] == Decimal('50000.00')
