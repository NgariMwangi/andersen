"""
Saved reports and report definitions.
"""
from app.extensions import db
from app.models.base import BaseModel


class SavedReport(BaseModel):
    """User-saved report (name, filters, schedule)."""
    __tablename__ = 'saved_reports'
    __table_args__ = (db.Index('ix_saved_reports_user_id', 'user_id'),)

    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    report_type = db.Column(db.String(100), nullable=False)  # employee_list, payroll_summary, etc.
    name = db.Column(db.String(200), nullable=False)
    parameters = db.Column(db.JSON, nullable=True)  # filters, date range
    last_run_at = db.Column(db.DateTime, nullable=True)
