"""
Audit logging service - immutable audit trail for HRMS Kenya.
All sensitive changes MUST be logged. No updates or deletes on audit logs.
"""
from datetime import date, datetime
from decimal import Decimal

from flask import has_request_context, request
from flask_login import current_user
from sqlalchemy import event, inspect

from app.extensions import db
from app.models.audit import AuditLog

_AUTO_AUDIT_INSTALLED = False
_SENSITIVE_FIELDS = {'password_hash', 'password'}


def _to_audit_value(value):
    """JSON-safe compact values for audit payloads."""
    if value is None:
        return None
    if isinstance(value, (datetime, date, Decimal)):
        return str(value)
    return value


def _is_auditable_instance(obj) -> bool:
    if obj is None or not hasattr(obj, '__table__'):
        return False
    if isinstance(obj, AuditLog):
        return False
    return True


def _model_to_audit_dict_internal(model_instance, exclude=None):
    exclude = set(exclude or [])
    exclude |= _SENSITIVE_FIELDS
    return {
        c.name: _to_audit_value(getattr(model_instance, c.name, None))
        for c in model_instance.__table__.columns
        if c.name not in exclude
    }


def get_client_ip():
    """Get client IP from request (handles proxies)."""
    if not request:
        return None
    return request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()


def get_user_agent():
    """Get user agent string."""
    if not request:
        return None
    ua = request.headers.get('User-Agent') or ''
    return ua[:500] if ua else None


def log_audit(
    action: str,
    record_type: str = None,
    record_id: str = None,
    old_values: dict = None,
    new_values: dict = None,
    user_id: int = None,
    description: str = None,
):
    """
    Write an immutable audit log entry.
    action: CREATE | UPDATE | DELETE | LOGIN | LOGIN_FAILED | EXPORT
    """
    entry = AuditLog(
        user_id=user_id,
        ip_address=get_client_ip(),
        user_agent=get_user_agent(),
        action=action.upper(),
        record_type=record_type,
        record_id=str(record_id) if record_id is not None else None,
        old_values=old_values,
        new_values=new_values,
        description=description,
    )
    db.session.add(entry)
    db.session.flush()  # get id if needed
    return entry


def log_create(record_type: str, record_id, new_values: dict, user_id: int = None, description: str = None):
    """Log creation of a record."""
    return log_audit(
        action='CREATE',
        record_type=record_type,
        record_id=record_id,
        new_values=new_values,
        user_id=user_id,
        description=description,
    )


def log_update(record_type: str, record_id, old_values: dict, new_values: dict, user_id: int = None, description: str = None):
    """Log update with before/after."""
    return log_audit(
        action='UPDATE',
        record_type=record_type,
        record_id=record_id,
        old_values=old_values,
        new_values=new_values,
        user_id=user_id,
        description=description,
    )


def log_delete(record_type: str, record_id, old_values: dict, user_id: int = None, description: str = None):
    """Log deletion (store last state in old_values)."""
    return log_audit(
        action='DELETE',
        record_type=record_type,
        record_id=record_id,
        old_values=old_values,
        user_id=user_id,
        description=description,
    )


def log_login(user_id: int, success: bool = True):
    """Log login attempt."""
    return log_audit(
        action='LOGIN' if success else 'LOGIN_FAILED',
        record_type='User',
        record_id=user_id,
        new_values={'success': success},
        user_id=user_id if success else None,
        description='Login successful' if success else 'Login failed',
    )


def log_export(record_type: str, description: str, user_id: int = None, extra: dict = None):
    """Log data export (e.g. payroll export)."""
    return log_audit(
        action='EXPORT',
        record_type=record_type,
        new_values=extra or {},
        user_id=user_id,
        description=description,
    )


def model_to_audit_dict(model_instance, exclude=None):
    """Convert model to dict for audit old_values/new_values (exclude sensitive)."""
    return _model_to_audit_dict_internal(model_instance, exclude=exclude)


def register_auto_audit_listeners() -> None:
    """
    Auto-log INSERT/UPDATE/DELETE across mapped models.
    This is a safety net so DB changes are recorded even when routes forget manual logging.
    """
    global _AUTO_AUDIT_INSTALLED
    if _AUTO_AUDIT_INSTALLED:
        return
    _AUTO_AUDIT_INSTALLED = True

    SessionCls = db.session.__class__

    @event.listens_for(SessionCls, 'before_flush')
    def _collect_changes(session, flush_context, instances):  # noqa: ANN001
        if session.info.get('_auto_audit_writing'):
            return
        entries = []

        # CREATE
        for obj in session.new:
            if not _is_auditable_instance(obj):
                continue
            entries.append(
                {
                    'action': 'CREATE',
                    'record_type': obj.__class__.__name__,
                    'obj': obj,
                    'old_values': None,
                    'new_values': _model_to_audit_dict_internal(obj),
                    'description': 'Auto audit: record created',
                }
            )

        # UPDATE (columns only)
        for obj in session.dirty:
            if not _is_auditable_instance(obj):
                continue
            if not session.is_modified(obj, include_collections=False):
                continue
            state = inspect(obj)
            old_values = {}
            new_values = {}
            for c in obj.__table__.columns:
                if c.name in _SENSITIVE_FIELDS:
                    continue
                hist = state.attrs[c.name].history
                if not hist.has_changes():
                    continue
                old_val = hist.deleted[0] if hist.deleted else getattr(obj, c.name, None)
                new_val = hist.added[0] if hist.added else getattr(obj, c.name, None)
                old_values[c.name] = _to_audit_value(old_val)
                new_values[c.name] = _to_audit_value(new_val)
            if old_values or new_values:
                entries.append(
                    {
                        'action': 'UPDATE',
                        'record_type': obj.__class__.__name__,
                        'obj': obj,
                        'old_values': old_values,
                        'new_values': new_values,
                        'description': 'Auto audit: record updated',
                    }
                )

        # DELETE
        for obj in session.deleted:
            if not _is_auditable_instance(obj):
                continue
            entries.append(
                {
                    'action': 'DELETE',
                    'record_type': obj.__class__.__name__,
                    'obj': obj,
                    'old_values': _model_to_audit_dict_internal(obj),
                    'new_values': None,
                    'description': 'Auto audit: record deleted',
                }
            )

        if entries:
            session.info['_auto_audit_entries'] = entries

    @event.listens_for(SessionCls, 'after_flush_postexec')
    def _write_audit_entries(session, flush_context):  # noqa: ANN001
        entries = session.info.pop('_auto_audit_entries', None)
        if not entries:
            return
        user_id = None
        ip = None
        ua = None
        if has_request_context():
            if getattr(current_user, 'is_authenticated', False):
                user_id = current_user.id
            ip = get_client_ip()
            ua = get_user_agent()

        rows = []
        for e in entries:
            obj = e.get('obj')
            record_id = getattr(obj, 'id', None)
            rows.append(
                {
                    'user_id': user_id,
                    'ip_address': ip,
                    'user_agent': ua,
                    'action': e['action'],
                    'record_type': e['record_type'],
                    'record_id': str(record_id) if record_id is not None else None,
                    'old_values': e.get('old_values'),
                    'new_values': e.get('new_values'),
                    'description': e.get('description'),
                }
            )
        if rows:
            session.info['_auto_audit_writing'] = True
            try:
                session.connection().execute(AuditLog.__table__.insert(), rows)
            finally:
                session.info['_auto_audit_writing'] = False
