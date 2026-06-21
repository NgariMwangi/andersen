"""Post-login and sidebar home routing by role."""
from flask import redirect, url_for
from flask_login import current_user


def is_employee_self_service_user(user=None):
    """Linked employee without HR employee-directory access (typical EMPLOYEE role)."""
    u = user or current_user
    if not getattr(u, 'is_authenticated', False):
        return False
    return bool(u.employee_id) and not u.has_permission('view_employees')


def user_home_endpoint(user=None):
    """Flask endpoint name for this user's default landing page."""
    if is_employee_self_service_user(user):
        return 'employees.profile'
    return 'dashboard.index'


def redirect_to_user_home(user=None):
    return redirect(url_for(user_home_endpoint(user)))
