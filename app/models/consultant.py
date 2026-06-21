"""Consultants: monthly pay with withholding tax only (separate from employees)."""
from decimal import Decimal

from app.extensions import db
from app.models.base import BaseModel


class Consultant(BaseModel):
    __tablename__ = 'consultants'
    __table_args__ = (
        db.Index('ix_consultants_company_status', 'company_id', 'status'),
        db.Index('ix_consultants_branch', 'branch_id'),
    )

    company_id = db.Column(db.Integer, db.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id', ondelete='RESTRICT'), nullable=False)

    consultant_number = db.Column(db.String(30), nullable=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    middle_name = db.Column(db.String(100), nullable=True)

    email = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    national_id = db.Column(db.String(30), nullable=True)
    kra_pin = db.Column(db.String(20), nullable=True)

    bank_name = db.Column(db.String(100), nullable=True)
    bank_branch = db.Column(db.String(100), nullable=True)
    bank_account_number = db.Column(db.String(50), nullable=True)
    bank_code = db.Column(db.String(20), nullable=True)

    status = db.Column(db.String(30), default='active', nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)
    withholding_rate = db.Column(db.Numeric(6, 3), default=Decimal('5'), nullable=False)
    prorate_payroll = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.Text, nullable=True)

    company = db.relationship('Company', backref='consultants')
    branch = db.relationship('Branch', backref='consultants')

    @property
    def full_name(self):
        parts = [self.first_name]
        if self.middle_name:
            parts.append(self.middle_name)
        parts.append(self.last_name)
        return ' '.join(parts)

    def __str__(self):
        return f'{self.consultant_number or "—"} - {self.full_name}'


class ConsultantCompensation(BaseModel):
    """Monthly fee for a consultant (effective-dated)."""

    __tablename__ = 'consultant_compensation'
    __table_args__ = (
        db.Index('ix_consultant_compensation_consultant', 'consultant_id'),
        db.Index('ix_consultant_compensation_effective', 'effective_from'),
    )

    consultant_id = db.Column(db.Integer, db.ForeignKey('consultants.id', ondelete='CASCADE'), nullable=False)
    effective_from = db.Column(db.Date, nullable=False)
    effective_to = db.Column(db.Date, nullable=True)
    monthly_fee = db.Column(db.Numeric(14, 2), nullable=False)
    other_allowances = db.Column(db.Numeric(14, 2), default=Decimal('0'), nullable=False)
    notes = db.Column(db.Text, nullable=True)

    consultant = db.relationship('Consultant', backref='compensation_records')


class ConsultantPayrollRunExclusion(BaseModel):
    """Consultants excluded from a specific draft payroll run."""

    __tablename__ = 'consultant_payroll_run_exclusions'
    __table_args__ = (
        db.UniqueConstraint(
            'payroll_run_id',
            'consultant_id',
            name='uq_consultant_payroll_exclusion_run_consultant',
        ),
        db.Index('ix_consultant_payroll_exclusion_run', 'payroll_run_id'),
    )

    payroll_run_id = db.Column(db.Integer, db.ForeignKey('payroll_runs.id', ondelete='CASCADE'), nullable=False)
    consultant_id = db.Column(db.Integer, db.ForeignKey('consultants.id', ondelete='CASCADE'), nullable=False)
    reason = db.Column(db.String(255), nullable=True)

    payroll_run = db.relationship('PayrollRun', backref='excluded_consultants')
    consultant = db.relationship('Consultant', backref='payroll_run_exclusions')


class ConsultantPayrollItem(BaseModel):
    """One consultant's pay for one payroll run (withholding tax only)."""

    __tablename__ = 'consultant_payroll_items'
    __table_args__ = (
        db.UniqueConstraint(
            'payroll_run_id',
            'consultant_id',
            name='uq_consultant_payroll_item_run_consultant',
        ),
        db.Index('ix_consultant_payroll_items_run', 'payroll_run_id'),
        db.Index('ix_consultant_payroll_items_consultant', 'consultant_id'),
    )

    payroll_run_id = db.Column(db.Integer, db.ForeignKey('payroll_runs.id', ondelete='CASCADE'), nullable=False)
    consultant_id = db.Column(db.Integer, db.ForeignKey('consultants.id', ondelete='CASCADE'), nullable=False)

    gross_pay = db.Column(db.Numeric(14, 2), nullable=False)
    withholding_tax = db.Column(db.Numeric(14, 2), default=Decimal('0'), nullable=False)
    net_pay = db.Column(db.Numeric(14, 2), nullable=False)
    earnings_breakdown = db.Column(db.JSON, nullable=True)
    deductions_breakdown = db.Column(db.JSON, nullable=True)
    is_pro_rata = db.Column(db.Boolean, default=False, nullable=False)

    payroll_run = db.relationship('PayrollRun', backref='consultant_items')
    consultant = db.relationship('Consultant', backref='payroll_items')
