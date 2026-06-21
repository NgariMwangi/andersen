"""Leave notification email helpers."""
from decimal import Decimal

from app.services.leave_notification_service import _employee_inbox, _format_leave_days, _supervisor_inboxes


class _User:
    def __init__(self, email):
        self.email = email


class _Emp:
    def __init__(self, email=None, user=None, manager=None, manager_id=None, supervisor_links=None):
        self.email = email
        self.secondary_email = None
        self.user = user
        self.manager = manager
        self.manager_id = manager_id
        self.supervisor_links = supervisor_links or []


def test_employee_inbox_prefers_login_email():
    emp = _Emp(email='work@co.com', user=_User('login@co.com'))
    assert _employee_inbox(emp) == 'login@co.com'


def test_employee_inbox_falls_back_to_work_email():
    emp = _Emp(email='work@co.com')
    assert _employee_inbox(emp) == 'work@co.com'


def test_supervisor_inboxes_from_manager_record():
    manager = _Emp(user=_User('boss@co.com'))
    emp = _Emp(manager=manager, manager_id=99)
    assert _supervisor_inboxes(emp) == ['boss@co.com']


def test_format_leave_days_removes_decimals():
    assert _format_leave_days(Decimal('5.00')) == '5'
    assert _format_leave_days(Decimal('1.00')) == '1'
    assert _format_leave_days(3) == '3'


def test_format_leave_days_keeps_half_days():
    assert _format_leave_days(Decimal('0.5')) == '0.5'
