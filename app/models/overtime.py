"""Overtime compensation requests (days-based), manager approval, payroll linkage."""
from app.extensions import db
from app.models.base import BaseModel


class OvertimeRequest(BaseModel):
    """
    Employee requests overtime in calendar days. Rate at payroll: (monthly_gross * 12) / 365 per day.
    """

    __tablename__ = 'overtime_requests'
    __table_args__ = (
        db.Index('ix_overtime_employee', 'employee_id'),
        db.Index('ix_overtime_status', 'status'),
        db.Index('ix_overtime_period', 'for_pay_year', 'for_pay_month'),
        db.Index('ix_overtime_applied_run', 'applied_to_payroll_run_id'),
    )

    company_id = db.Column(db.Integer, db.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False)
    days = db.Column(db.Numeric(8, 4), nullable=False)
    worked_dates = db.Column(db.Text, nullable=False)  # comma-separated ISO dates (YYYY-MM-DD)
    for_pay_month = db.Column(db.Integer, nullable=False)  # 1–12
    for_pay_year = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')  # pending, approved, rejected, cancelled
    reason = db.Column(db.Text, nullable=True)

    submitted_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_notes = db.Column(db.Text, nullable=True)

    applied_to_payroll_run_id = db.Column(
        db.Integer, db.ForeignKey('payroll_runs.id', ondelete='SET NULL'), nullable=True
    )

    company = db.relationship('Company', backref='overtime_requests')
    employee = db.relationship('Employee', foreign_keys=[employee_id], backref='overtime_requests')
    submitted_by = db.relationship('User', foreign_keys=[submitted_by_user_id])
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_user_id])
    applied_to_payroll_run = db.relationship('PayrollRun', backref='overtime_requests_applied')
