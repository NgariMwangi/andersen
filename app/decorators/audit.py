"""
Decorator to log audit trail on successful create/update/delete.
Use in routes or services that modify sensitive data.
"""
from functools import wraps
from flask_login import current_user
from app.services.audit_service import log_create, log_update, log_delete, model_to_audit_dict


def audit_log(action: str, record_type: str, get_record_id=None, get_description=None):
    """
    Decorator to audit a function that creates/updates/deletes a record.
    action: 'create' | 'update' | 'delete'
    record_type: e.g. 'Employee', 'PayrollRun'
    get_record_id: callable(result) -> id of created/updated record
    get_description: callable(*args, **kwargs) -> optional description
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            result = f(*args, **kwargs)
            user_id = current_user.id if current_user.is_authenticated else None
            record_id = get_record_id(result) if get_record_id else (getattr(result, 'id', None))
            description = get_description(*args, **kwargs) if get_description else None
            if action == 'create' and result is not None:
                new_values = model_to_audit_dict(result) if hasattr(result, '__table__') else {'id': record_id}
                log_create(record_type, record_id, new_values, user_id=user_id, description=description)
            elif action in ('update', 'delete') and result is not None:
                # Caller may pass old_values via kwargs for update/delete
                old_vals = kwargs.get('_audit_old_values')
                new_vals = model_to_audit_dict(result) if action == 'update' and hasattr(result, '__table__') else None
                if action == 'update':
                    log_update(record_type, record_id, old_vals or {}, new_vals or {}, user_id=user_id, description=description)
                else:
                    log_delete(record_type, record_id, old_vals or {}, user_id=user_id, description=description)
            return result
        return wrapped
    return decorator
