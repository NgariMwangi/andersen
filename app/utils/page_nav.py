"""Top-bar page title / section from the current Flask endpoint."""
from __future__ import annotations

# (section, title) — section is the parent area shown before the page name.
_PAGE_NAV: dict[str, tuple[str, str]] = {
    'dashboard.index': ('', 'Dashboard'),
    'employees.profile': ('', 'My profile'),
    'employees.list': ('Employees', 'Employee list'),
    'employees.create': ('Employees', 'Add employee'),
    'employees.birthdays': ('Employees', 'Birthdays'),
    'employees.probation_dates': ('Employees', 'Probation dates'),
    'employees.contract_dates': ('Employees', 'Contract dates'),
    'employees.provision_login_accounts': ('Employees', 'Provision logins'),
    'employees.benefits_index': ('Employees', 'Benefits'),
    'employees.deductions_index': ('Employees', 'Deductions'),
    'employees.history': ('Employees', 'Career history'),
    'employees.documents': ('Employees', 'Documents'),
    'employees.link_user': ('Employees', 'Link login account'),
    'leave.index': ('Leave', 'Calendar & requests'),
    'leave.types_index': ('Leave', 'Leave types'),
    'leave.type_create': ('Leave', 'Add leave type'),
    'leave.balances': ('Leave', 'Leave balances'),
    'leave.admin_request_leave': ('Leave', 'Apply leave for employee'),
    'leave.holidays_index': ('Leave', 'Public holidays'),
    'leave.holiday_create': ('Leave', 'Add public holiday'),
    'leave.my_requests': ('Leave', 'Request leave'),
    'leave.requests': ('Leave', 'Leave requests'),
    'leave.tracker': ('Leave', 'Leave tracker'),
    'departments.index': ('Organization', 'Departments'),
    'departments.create': ('Organization', 'Add department'),
    'branches.index': ('Organization', 'Branches'),
    'branches.create': ('Organization', 'Add branch'),
    'job_titles.index': ('Organization', 'Job titles'),
    'job_titles.create': ('Organization', 'Add job title'),
    'allowances.index': ('Organization', 'Allowances'),
    'company_assets.index': ('Organization', 'Company assets'),
    'company_assets.create': ('Organization', 'Add asset'),
    'company_assets.view': ('Organization', 'Asset details'),
    'company_assets.edit': ('Organization', 'Edit asset'),
    'company_assets.assign': ('Organization', 'Assign asset'),
    'company_assets.employee_assets': ('Organization', 'Employee assets'),
    'company_assets.categories': ('Organization', 'Asset categories'),
    'it_tickets.my_tickets': ('IT Support', 'My tickets'),
    'it_tickets.create': ('IT Support', 'New ticket'),
    'it_tickets.queue': ('IT Support', 'IT queue'),
    'it_tickets.view': ('IT Support', 'Ticket details'),
    'it_tickets.categories': ('IT Support', 'Ticket categories'),
    'reports.index': ('Reports', 'Overview'),
    'reports.employee_list': ('Reports', 'Employee list'),
    'reports.executive_summary': ('Reports', 'Executive summary'),
    'reports.payroll_summary': ('Reports', 'Payroll summary'),
    'settings.index': ('Settings', 'Overview'),
    'settings.users': ('Settings', 'Users & roles'),
    'settings.user_form': ('Settings', 'User account'),
    'settings.employer': ('Settings', 'Employer details'),
    'settings.audit_log': ('Settings', 'Audit log'),
    'settings.companies_list': ('Settings', 'Companies'),
    'settings.companies_new': ('Settings', 'New company'),
    'auth.change_password': ('Account', 'Change password'),
    'messages.index': ('Messages', 'Inbox'),
    'messages.compose': ('Messages', 'New message'),
    'messages.thread': ('Messages', 'Conversation'),
    'overtime.index': ('Overtime', 'Requests'),
    'attendance.index': ('Attendance', 'Overview'),
    'payroll.index': ('Payroll', 'Payroll runs'),
    'payroll.my_payslips': ('Payroll', 'My payslips'),
    'payroll.run': ('Payroll', 'Run payroll'),
    'statutory.index': ('Statutory', 'Rates'),
    'statutory.hub': ('Statutory', 'By country'),
}

# Fallback title from endpoint action segment (employees.view -> View).
_ACTION_TITLES: dict[str, str] = {
    'index': 'Overview',
    'view': 'Details',
    'edit': 'Edit',
    'create': 'Add new',
    'list': 'List',
}


def _section_for_blueprint(blueprint: str) -> str:
    return {
        'employees': 'Employees',
        'leave': 'Leave',
        'departments': 'Organization',
        'branches': 'Organization',
        'job_titles': 'Organization',
        'allowances': 'Organization',
        'company_assets': 'Organization',
        'it_tickets': 'IT Support',
        'reports': 'Reports',
        'settings': 'Settings',
        'payroll': 'Payroll',
        'statutory': 'Statutory',
        'overtime': 'Overtime',
        'attendance': 'Attendance',
        'consultants': 'Consultants',
        'casual_workers': 'Casual workers',
        'dashboard': '',
        'auth': 'Account',
        'messages': 'Messages',
    }.get(blueprint, '')


def _title_from_action(action: str) -> str:
    if action in _ACTION_TITLES:
        return _ACTION_TITLES[action]
    return action.replace('_', ' ').title()


def resolve_page_nav(endpoint: str | None) -> dict[str, str] | None:
    """Return {section, title} for the top bar, or None if unauthenticated layout."""
    if not endpoint:
        return None
    if endpoint in _PAGE_NAV:
        section, title = _PAGE_NAV[endpoint]
        return {'section': section, 'title': title}
    if '.' not in endpoint:
        return None
    blueprint, action = endpoint.split('.', 1)
    section = _section_for_blueprint(blueprint)
    title = _title_from_action(action)
    if not section and not title:
        return None
    return {'section': section, 'title': title}
