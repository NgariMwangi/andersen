"""
Casual workers and off-payroll payouts.
This module is intentionally separate from payroll employees.
"""
from decimal import Decimal

from app.extensions import db
from app.models.base import BaseModel


class CasualWorker(BaseModel):
    __tablename__ = 'casual_workers'
    __table_args__ = (
        db.Index('ix_casual_workers_company_status', 'company_id', 'status'),
        db.Index('ix_casual_workers_branch', 'branch_id'),
    )

    company_id = db.Column(db.Integer, db.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id', ondelete='RESTRICT'), nullable=False)

    worker_number = db.Column(db.String(30), nullable=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(30), nullable=True)
    national_id = db.Column(db.String(30), nullable=True)
    daily_rate = db.Column(db.Numeric(14, 2), default=Decimal('0'), nullable=False)
    rate_unit = db.Column(db.String(20), default='daily', nullable=False)  # hourly, daily, weekly, monthly
    status = db.Column(db.String(20), default='active', nullable=False)  # active, inactive
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.String(500), nullable=True)

    company = db.relationship('Company', backref='casual_workers')
    branch = db.relationship('Branch', backref='casual_workers')

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()


class CasualPayment(BaseModel):
    __tablename__ = 'casual_payments'
    __table_args__ = (
        db.UniqueConstraint('worker_id', 'period_year', 'period_month', name='uq_casual_payment_worker_period'),
        db.Index('ix_casual_payments_company_period', 'company_id', 'period_year', 'period_month'),
    )

    company_id = db.Column(db.Integer, db.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    worker_id = db.Column(db.Integer, db.ForeignKey('casual_workers.id', ondelete='CASCADE'), nullable=False)
    period_year = db.Column(db.Integer, nullable=False)
    period_month = db.Column(db.Integer, nullable=False)  # 1..12
    days_worked = db.Column(db.Numeric(8, 2), default=Decimal('0'), nullable=False)
    rate_per_day = db.Column(db.Numeric(14, 2), default=Decimal('0'), nullable=False)
    gross_amount = db.Column(db.Numeric(14, 2), default=Decimal('0'), nullable=False)
    adjustments = db.Column(db.Numeric(14, 2), default=Decimal('0'), nullable=False)
    net_amount = db.Column(db.Numeric(14, 2), default=Decimal('0'), nullable=False)
    status = db.Column(db.String(20), default='pending', nullable=False)  # pending, paid
    paid_on = db.Column(db.Date, nullable=True)
    notes = db.Column(db.String(500), nullable=True)

    company = db.relationship('Company', backref='casual_payments')
    worker = db.relationship('CasualWorker', backref='payments')
