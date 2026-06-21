"""
Payroll runs, items, employee salary and earnings/deduction types.
"""
from decimal import Decimal
from app.extensions import db
from app.models.base import BaseModel


class Allowance(BaseModel):
    """Company-wide allowance types (House, Transport, Meal, etc.)."""
    __tablename__ = 'allowances'
    __table_args__ = (db.UniqueConstraint('company_id', 'code', name='uq_allowances_company_code'),)

    company_id = db.Column(db.Integer, db.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    company = db.relationship('Company', backref='allowances')

    code = db.Column(db.String(50), nullable=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(500), nullable=True)
    is_taxable = db.Column(db.Boolean, default=True, nullable=False)
    is_pensionable = db.Column(db.Boolean, default=False, nullable=False)  # for NSSF base (e.g. house often is)

    employee_allowances = db.relationship('EmployeeAllowance', backref='allowance', lazy='dynamic')


class EmployeeAllowance(BaseModel):
    """Amount of an allowance assigned to an employee (effective date range)."""
    __tablename__ = 'employee_allowances'
    __table_args__ = (
        db.Index('ix_employee_allowances_employee_id', 'employee_id'),
        db.Index('ix_employee_allowances_effective', 'effective_from'),
    )

    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False)
    allowance_id = db.Column(db.Integer, db.ForeignKey('allowances.id', ondelete='CASCADE'), nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    effective_from = db.Column(db.Date, nullable=False)
    effective_to = db.Column(db.Date, nullable=True)

    employee = db.relationship('Employee', backref='allowance_assignments')


class EarningsDeductionType(BaseModel):
    """Lookup: Basic Salary, House Allowance, NSSF, PAYE, etc."""
    __tablename__ = 'earnings_deduction_types'
    __table_args__ = (db.Index('ix_earnings_deduction_types_code', 'code'),)

    code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(20), nullable=False)  # 'earning' or 'deduction'
    is_taxable = db.Column(db.Boolean, default=True, nullable=False)
    is_pensionable = db.Column(db.Boolean, default=False, nullable=False)  # for NSSF base
    is_statutory = db.Column(db.Boolean, default=False, nullable=False)
    affects_net = db.Column(db.Boolean, default=True, nullable=False)  # deduction reduces net


class Deduction(BaseModel):
    """Company-wide deduction types (loan, SACCO, court order, etc.)."""

    __tablename__ = 'deductions'
    __table_args__ = (db.UniqueConstraint('company_id', 'code', name='uq_deductions_company_code'),)

    company_id = db.Column(db.Integer, db.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    company = db.relationship('Company', backref='deduction_types')

    code = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(500), nullable=True)


class EmployeeDeduction(BaseModel):
    """Recurring/other deductions assigned to an employee (effective date range)."""

    __tablename__ = 'employee_deductions'
    __table_args__ = (
        db.Index('ix_employee_deductions_employee_id', 'employee_id'),
        db.Index('ix_employee_deductions_effective', 'effective_from'),
    )

    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False)
    # Optional legacy link to catalog; payslip uses `title` when set.
    deduction_id = db.Column(db.Integer, db.ForeignKey('deductions.id', ondelete='SET NULL'), nullable=True)
    title = db.Column(db.String(200), nullable=True)
    # fixed = fixed KES/month; percent_basic / percent_gross use rate_percent
    calculation_mode = db.Column(db.String(20), nullable=False, default='fixed')
    amount = db.Column(db.Numeric(14, 2), default=Decimal('0'), nullable=False)
    rate_percent = db.Column(db.Numeric(8, 4), nullable=True)
    effective_from = db.Column(db.Date, nullable=False)
    effective_to = db.Column(db.Date, nullable=True)
    remaining_balance = db.Column(db.Numeric(14, 2), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.Text, nullable=True)

    employee = db.relationship('Employee', backref='deduction_assignments')
    deduction = db.relationship('Deduction', backref='employee_deductions')


class EmployeeSalary(BaseModel):
    """Current salary structure per employee (basic, allowances). Used for payroll calculation."""
    __tablename__ = 'employee_salaries'
    __table_args__ = (
        db.Index('ix_employee_salaries_employee_id', 'employee_id'),
        db.Index('ix_employee_salaries_effective_from', 'effective_from'),
    )

    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False)
    effective_from = db.Column(db.Date, nullable=False)
    effective_to = db.Column(db.Date, nullable=True)
    basic_salary = db.Column(db.Numeric(14, 2), nullable=False)
    house_allowance = db.Column(db.Numeric(14, 2), default=Decimal('0'), nullable=False)
    transport_allowance = db.Column(db.Numeric(14, 2), default=Decimal('0'), nullable=False)
    meal_allowance = db.Column(db.Numeric(14, 2), default=Decimal('0'), nullable=False)
    other_allowances = db.Column(db.Numeric(14, 2), default=Decimal('0'), nullable=False)
    pension_employee_percent = db.Column(db.Numeric(5, 2), default=Decimal('0'), nullable=True)  # if org has pension
    pension_employee_fixed_amount = db.Column(db.Numeric(14, 2), default=Decimal('0'), nullable=True)
    pension_employer_percent = db.Column(db.Numeric(5, 2), default=Decimal('0'), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    employee = db.relationship('Employee', backref='salary_records')


class PayrollRun(BaseModel):
    """A single payroll run for a month/year."""
    __tablename__ = 'payroll_runs'
    __table_args__ = (
        db.UniqueConstraint('company_id', 'country_code', 'pay_month', 'pay_year', name='uq_payroll_run_company_country_month_year'),
        db.Index('ix_payroll_runs_status', 'status'),
        db.Index('ix_payroll_runs_company_country_pay_month_year', 'company_id', 'country_code', 'pay_month', 'pay_year'),
    )

    company_id = db.Column(db.Integer, db.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    company = db.relationship('Company', backref='payroll_runs')
    country_code = db.Column(db.String(2), nullable=False, default='KE')

    pay_month = db.Column(db.Integer, nullable=False)  # 1-12
    pay_year = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(30), default='draft', nullable=False)  # draft, submitted, approved, finance_reviewed, paid
    processed_at = db.Column(db.DateTime, nullable=True)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    finance_reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    finance_reviewed_at = db.Column(db.DateTime, nullable=True)
    paid_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    paid_at = db.Column(db.DateTime, nullable=True)
    payment_reference = db.Column(db.String(120), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    items = db.relationship('PayrollItem', backref='payroll_run', lazy='dynamic', cascade='all, delete-orphan')
    manual_deductions = db.relationship(
        'PayrollRunManualDeduction',
        backref='payroll_run',
        lazy='dynamic',
        cascade='all, delete-orphan',
    )


class PayrollRunManualDeduction(BaseModel):
    """One-off deductions for a specific draft payroll run (manual override)."""

    __tablename__ = 'payroll_run_manual_deductions'
    __table_args__ = (
        db.Index('ix_manual_deductions_run', 'payroll_run_id'),
        db.Index('ix_manual_deductions_employee', 'employee_id'),
    )

    payroll_run_id = db.Column(db.Integer, db.ForeignKey('payroll_runs.id', ondelete='CASCADE'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False)
    label = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    notes = db.Column(db.Text, nullable=True)

    employee = db.relationship('Employee', backref='payroll_manual_deductions')


class PayrollRunExclusion(BaseModel):
    """Employees explicitly excluded from a specific draft payroll run."""

    __tablename__ = 'payroll_run_exclusions'
    __table_args__ = (
        db.UniqueConstraint('payroll_run_id', 'employee_id', name='uq_payroll_run_exclusion_run_employee'),
        db.Index('ix_payroll_exclusions_run', 'payroll_run_id'),
        db.Index('ix_payroll_exclusions_employee', 'employee_id'),
    )

    payroll_run_id = db.Column(db.Integer, db.ForeignKey('payroll_runs.id', ondelete='CASCADE'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False)
    reason = db.Column(db.String(255), nullable=True)

    payroll_run = db.relationship('PayrollRun', backref='excluded_employees')
    employee = db.relationship('Employee', backref='payroll_run_exclusions')


class PayrollItem(BaseModel):
    """One employee's pay for one payroll run (one row per employee per run)."""
    __tablename__ = 'payroll_items'
    __table_args__ = (
        db.Index('ix_payroll_items_employee_id', 'employee_id'),
        db.Index('ix_payroll_items_payroll_run_id', 'payroll_run_id'),
    )

    payroll_run_id = db.Column(db.Integer, db.ForeignKey('payroll_runs.id', ondelete='CASCADE'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False)
    # Snapshot for audit
    gross_pay = db.Column(db.Numeric(14, 2), nullable=False)
    taxable_pay = db.Column(db.Numeric(14, 2), nullable=False)
    paye = db.Column(db.Numeric(14, 2), default=Decimal('0'), nullable=False)
    nssf_employee = db.Column(db.Numeric(14, 2), default=Decimal('0'), nullable=False)
    nssf_employer = db.Column(db.Numeric(14, 2), default=Decimal('0'), nullable=False)
    shif = db.Column(db.Numeric(14, 2), default=Decimal('0'), nullable=False)
    housing_levy = db.Column(db.Numeric(14, 2), default=Decimal('0'), nullable=False)
    other_deductions = db.Column(db.Numeric(14, 2), default=Decimal('0'), nullable=False)
    net_pay = db.Column(db.Numeric(14, 2), nullable=False)
    # JSON for line-item breakdown: [{ "code": "BASIC", "amount": 50000 }, ...]
    earnings_breakdown = db.Column(db.JSON, nullable=True)
    deductions_breakdown = db.Column(db.JSON, nullable=True)
    days_worked = db.Column(db.Numeric(5, 2), nullable=True)  # for pro-rata
    is_pro_rata = db.Column(db.Boolean, default=False, nullable=False)

    employee = db.relationship('Employee', backref='payroll_items')
    statutory_remitances = db.relationship(
        'PayrollStatutoryRemittance',
        backref='payroll_item',
        lazy='dynamic',
        cascade='all, delete-orphan',
    )


class PayrollStatutoryRemittance(BaseModel):
    """
    Snapshot of statutory amounts per employee per payroll run, recorded when payroll is approved.
    Used for remittance reporting to KRA, NSSF, SHA, Housing Fund, etc.
    """

    __tablename__ = 'payroll_statutory_remitances'
    __table_args__ = (
        db.UniqueConstraint('payroll_item_id', 'statutory_code', name='uq_statutory_remittance_item_code'),
        db.Index('ix_statutory_remittance_run', 'payroll_run_id'),
        db.Index('ix_statutory_remittance_employee', 'employee_id'),
        db.Index('ix_statutory_remittance_code', 'statutory_code'),
    )

    payroll_run_id = db.Column(db.Integer, nullable=False)  # denormalized for aggregation (matches item.payroll_run_id)
    payroll_item_id = db.Column(
        db.Integer,
        db.ForeignKey('payroll_items.id', ondelete='CASCADE'),
        nullable=False,
    )
    employee_id = db.Column(
        db.Integer,
        db.ForeignKey('employees.id', ondelete='CASCADE'),
        nullable=False,
    )
    statutory_code = db.Column(db.String(50), nullable=False)
    institution_name = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False)

    employee = db.relationship('Employee', backref='statutory_remitances')
