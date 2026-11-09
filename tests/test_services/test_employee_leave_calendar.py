"""Calendar rendering with historical fractions and working-day ranges."""
import calendar
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from flask import Flask
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader

import app.routes.leave as leave


@pytest.fixture
def calendar_page(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(leave.leave_bp, url_prefix='/leave')
    templates = Path(leave.__file__).parents[1] / 'templates'
    app.jinja_loader = ChoiceLoader([
        DictLoader({'layouts/base.html': '{% block content %}{% endblock %}'}),
        FileSystemLoader(str(templates)),
    ])
    app.jinja_env.filters['fmt_days'] = lambda value: str(value)
    app.jinja_env.globals['leave_status_label'] = lambda value: value.title()
    employee = SimpleNamespace(id=1, full_name='Ann Wangechi', first_name='Ann',
                               last_name='Wangechi', employee_number='001', gender='female', company_id=1)
    lt = SimpleNamespace(id=1, code='ANNUAL', name='Annual Leave', days_count_basis='working')
    requests = []
    def query(model):
        mock = MagicMock()
        mock.filter.return_value = mock
        mock.order_by.return_value = mock
        mock.all.return_value = {leave.Employee: [employee], leave.LeaveType: [lt], leave.LeaveRequest: requests}[model]
        return mock
    monkeypatch.setattr(leave, 'db', SimpleNamespace(session=SimpleNamespace(query=query)))
    monkeypatch.setattr(leave, 'require_company_id', lambda: 1)
    monkeypatch.setattr(leave, '_leave_country_for_employee', lambda emp: 'KE')
    monkeypatch.setattr(leave, 'public_holiday_dates_in_range', lambda *args: {date(2026, 1, 1)})
    monkeypatch.setattr(leave, 'statistics_for_employee', lambda *args: [])
    def render(args='year=2026&employee_id=1'):
        with app.test_request_context('/leave/tracker?' + args):
            return leave.tracker.__wrapped__.__wrapped__()
    return requests, lt, render


def test_fractional_historical_weekend_is_visible(calendar_page):
    requests, lt, render = calendar_page
    requests.append(SimpleNamespace(id=7, employee_id=1, leave_type_id=1,
        leave_type=lt, start_date=date(2026, 7, 26), end_date=date(2026, 7, 26),
        days_requested=Decimal('0.25'), status='approved'))
    html = render()
    assert '0.25 day(s)' in html
    assert '/leave/7' in html
    assert 'datetime="2026-07-26"' in html
    assert html.count('calendar-entry badge') == 1


def test_range_excludes_holidays_and_weekends(calendar_page):
    requests, lt, render = calendar_page
    requests.append(SimpleNamespace(id=8, employee_id=1, leave_type_id=1,
        leave_type=lt, start_date=date(2025, 12, 31), end_date=date(2026, 1, 5),
        days_requested=Decimal('3'), status='booked'))
    html = render()
    assert html.count('calendar-entry badge') == 2  # Jan 2 and Jan 5
    assert '3 total' in html
    assert 'Booked' in html


def test_empty_year_and_invalid_employee(calendar_page):
    _, _, render = calendar_page
    assert 'No approved or booked leave recorded' in render()
    from werkzeug.exceptions import NotFound, BadRequest
    with pytest.raises(NotFound):
        render('year=2026&employee_id=999')
    with pytest.raises(BadRequest):
        render('year=99999&employee_id=1')
