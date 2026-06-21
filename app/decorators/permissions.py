"""
Role-based permission decorators for routes.
"""
from functools import wraps
from flask import abort
from flask_login import current_user


def permission_required(permission_code: str):
    """Decorator: require specific permission (and login)."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(403)
            if not current_user.has_permission(permission_code):
                abort(403)
            return f(*args, **kwargs)
        return wrapped
    return decorator


def role_required(*role_codes: str):
    """Decorator: require any of the given roles."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(403)
            if not current_user.has_any_role(*role_codes):
                abort(403)
            return f(*args, **kwargs)
        return wrapped
    return decorator


def admin_required(f):
    """Require ADMIN role."""
    return role_required('ADMIN')(f)


def hr_manager_required(f):
    """Require HR_MANAGER or ADMIN."""
    return role_required('ADMIN', 'HR_MANAGER')(f)
