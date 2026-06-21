"""Decorators for optional product modules."""
from functools import wraps

from flask import abort, current_app


def require_payroll(view):
    """Return 404 when payroll module is disabled."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_app.config.get('ENABLE_PAYROLL', False):
            abort(404)
        return view(*args, **kwargs)
    return wrapped


def require_branches(view):
    """Return 404 when branch management UI is disabled."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_app.config.get('ENABLE_BRANCHES', False):
            abort(404)
        return view(*args, **kwargs)
    return wrapped
