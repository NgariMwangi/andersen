"""
Immutable audit trail for HRMS Kenya.
All create/update/delete on sensitive data MUST be logged.
Cannot modify or delete audit logs.
"""
from app.extensions import db


class AuditLog(db.Model):
    """
    Immutable audit log. No updates or deletes allowed at application level.
    Stores: user, timestamp, action, record type, record id, old/new values (JSON), IP, user agent.
    """
    __tablename__ = 'audit_logs'
    __table_args__ = (
        db.Index('ix_audit_logs_user_id', 'user_id'),
        db.Index('ix_audit_logs_created_at', 'created_at'),
        db.Index('ix_audit_logs_record_type_record_id', 'record_type', 'record_id'),
        db.Index('ix_audit_logs_action', 'action'),
    )

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    created_at = db.Column(db.DateTime, nullable=False, default=db.func.now())

    # Who and where
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)

    # What
    action = db.Column(db.String(20), nullable=False)  # CREATE, UPDATE, DELETE, LOGIN, LOGIN_FAILED, EXPORT
    record_type = db.Column(db.String(100), nullable=True)  # e.g. 'Employee', 'PayrollRun', 'StatutoryRate'
    record_id = db.Column(db.String(100), nullable=True)

    # Payload (JSON). For UPDATE: old_values and new_values. For CREATE: new_values only. For DELETE: old_values only.
    old_values = db.Column(db.JSON, nullable=True)
    new_values = db.Column(db.JSON, nullable=True)

    # Optional description (e.g. "Password reset", "Payroll approved")
    description = db.Column(db.String(500), nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'user_id': self.user_id,
            'ip_address': self.ip_address,
            'action': self.action,
            'record_type': self.record_type,
            'record_id': self.record_id,
            'old_values': self.old_values,
            'new_values': self.new_values,
            'description': self.description,
        }
