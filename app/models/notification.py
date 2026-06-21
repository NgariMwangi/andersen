"""
In-app notifications.
"""
from app.extensions import db
from app.models.base import BaseModel


class Notification(BaseModel):
    """In-app notification for a user."""
    __tablename__ = 'notifications'
    __table_args__ = (
        db.Index('ix_notifications_user_id', 'user_id'),
        db.Index('ix_notifications_read', 'read'),
    )

    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=True)
    link = db.Column(db.String(500), nullable=True)
    read = db.Column(db.Boolean, default=False, nullable=False)
    read_at = db.Column(db.DateTime, nullable=True)

    # Optional: link to related entity
    related_type = db.Column(db.String(50), nullable=True)  # 'leave_request', 'payroll_run'
    related_id = db.Column(db.Integer, nullable=True)
