"""Payslip email service."""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask import Flask

from app.services.payslip_email_service import send_payslip_email


class _User:
    def __init__(self, email):
        self.email = email


class _Emp:
    def __init__(self, email=None, user=None, full_name='Jane Doe', employee_number=None):
        self.email = email
        self.secondary_email = None
        self.user = user
        self.full_name = full_name
        self.employee_number = employee_number
        self.branch = SimpleNamespace(country_code='KE')
        self.company_id = 1


class _Run:
    def __init__(self, status='approved'):
        self.status = status
        self.pay_year = 2026
        self.pay_month = 5
        self.company = SimpleNamespace(name='Acme Ltd')


class _Item:
    def __init__(self, employee=None, run=None):
        self.employee = employee
        self.payroll_run = run or _Run()
        self.employee_id = 1
        self.gross_pay = Decimal('100000')
        self.taxable_pay = Decimal('90000')
        self.net_pay = Decimal('85000')
        self.paye = Decimal('5000')
        self.nssf_employee = Decimal('0')
        self.shif = Decimal('0')
        self.housing_levy = Decimal('0')
        self.earnings_breakdown = [{'code': 'BASIC', 'name': 'Basic', 'amount': 100000}]
        self.deductions_breakdown = []


@pytest.fixture
def app_context():
    app = Flask(__name__)
    app.config['APP_NAME'] = 'HRMS Test'
    app.config['DEFAULT_CURRENCY'] = 'KES'
    with app.app_context():
        yield


def test_send_payslip_email_no_address(app_context):
    item = _Item(employee=_Emp())
    ok, message = send_payslip_email(item)
    assert ok is False
    assert 'No email address' in message


@patch('app.services.payslip_email_service.brevo_configured', return_value=True)
@patch('app.services.payslip_email_service.send_transactional_email', return_value=True)
@patch('app.services.payslip_email_service.build_payslip_pdf', return_value=b'%PDF-1.4')
@patch('app.services.payslip_email_service.build_payslip_context')
def test_send_payslip_email_success(mock_ctx, mock_pdf, mock_send, mock_brevo, app_context):
    from datetime import date

    mock_ctx.return_value = {
        'period_date': date(2026, 5, 1),
        'payslip_currency': 'KES',
        'company_name': 'Acme Ltd',
    }
    item = _Item(employee=_Emp(email='jane@example.com'))
    ok, message = send_payslip_email(item)
    assert ok is True
    assert 'jane@example.com' in message
    mock_send.assert_called_once()
    args, kwargs = mock_send.call_args
    assert args[0] == 'jane@example.com'
    assert kwargs['attachments']
    assert kwargs['attachments'][0][0].endswith('.pdf')


@patch('app.services.payslip_email_service.brevo_configured', return_value=False)
def test_send_payslip_email_not_configured(mock_brevo, app_context):
    item = _Item(employee=_Emp(email='jane@example.com'))
    ok, message = send_payslip_email(item)
    assert ok is False
    assert 'not configured' in message.lower()
