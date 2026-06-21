"""Feature flags for optional product modules."""
from flask import current_app


def payroll_enabled() -> bool:
    return bool(current_app.config.get('ENABLE_PAYROLL', False))


def branches_enabled() -> bool:
    return bool(current_app.config.get('ENABLE_BRANCHES', False))
