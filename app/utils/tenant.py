"""Multi-company scope: current user's tenant company."""
from flask import abort
from flask_login import current_user


def current_company_id() -> int | None:
    """Logged-in user's company, or None if not authenticated / no company set."""
    if not current_user.is_authenticated:
        return None
    return getattr(current_user, 'company_id', None)


def require_company_id() -> int:
    """Use in routes that must be scoped to a company."""
    cid = current_company_id()
    if cid is None:
        abort(403)
    return cid
