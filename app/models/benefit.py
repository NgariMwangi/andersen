"""
Employee off-payroll benefits / reimbursements.
These are simple payroll additions scheduled for a specific payroll month.
"""
from decimal import Decimal
from app.extensions import db
from app.models.base import BaseModel


class EmployeeBenefit(BaseModel):
    """Employee benefit scheduled for payroll (one-off or recurring monthly)."""
    __tablename__ = 'employee_benefits'
    __table_args__ = (
        db.Index('ix_employee_benefits_employee_id', 'employee_id'),
        db.Index('ix_employee_benefits_payroll_period', 'payroll_year', 'payroll_month'),
    )

    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Numeric(14, 2), default=Decimal('0'), nullable=False)
    frequency = db.Column(db.String(20), default='one_off', nullable=False)  # one_off, monthly
    effective_date = db.Column(db.Date, nullable=True)  # legacy compatibility
    payroll_year = db.Column(db.Integer, nullable=True)
    payroll_month = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.String(500), nullable=True)
    is_taxable = db.Column(db.Boolean, default=True, nullable=False)
    is_pensionable = db.Column(db.Boolean, default=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    employee = db.relationship('Employee', backref='benefit_assignments')


class EmployeeBenefitPayment(BaseModel):
    """Payment lines for off-payroll employee benefits."""
    __tablename__ = 'employee_benefit_payments'
    __table_args__ = (
        db.Index('ix_employee_benefit_payments_benefit_id', 'benefit_id'),
        db.Index('ix_employee_benefit_payments_period', 'period_year', 'period_month'),
        db.UniqueConstraint(
            'benefit_id',
            'period_year',
            'period_month',
            name='uq_employee_benefit_payment_period',
        ),
    )

    benefit_id = db.Column(db.Integer, db.ForeignKey('employee_benefits.id', ondelete='CASCADE'), nullable=False)
    period_year = db.Column(db.Integer, nullable=False)
    period_month = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Numeric(14, 2), default=Decimal('0'), nullable=False)
    status = db.Column(db.String(20), default='pending', nullable=False)  # pending, paid
    paid_on = db.Column(db.Date, nullable=True)
    notes = db.Column(db.String(500), nullable=True)

    benefit = db.relationship('EmployeeBenefit', backref='payments')
