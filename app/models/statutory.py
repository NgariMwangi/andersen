"""
Statutory rate configuration for Kenya (PAYE, NSSF, SHIF, Housing Levy).
Rates stored in DB with effective dates; no code change needed when legislation changes.
"""
from decimal import Decimal
from app.extensions import db
from app.models.base import BaseModel


class StatutoryRateType(db.Model):
    """Lookup: PAYE_RELIEF, NSSF_TIER1_EMPLOYEE, SHIF_PERCENT, HOUSING_LEVY_PERCENT, etc."""
    __tablename__ = 'statutory_rate_types'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    unit = db.Column(db.String(20), nullable=True)  # 'percent', 'amount', 'currency'


class StatutoryRate(BaseModel):
    """Single rate value with effective date range. Used for percentages (SHIF, Housing) and fixed amounts (relief)."""
    __tablename__ = 'statutory_rates'
    __table_args__ = (
        db.Index('ix_statutory_rates_scope_code_effective', 'company_id', 'country_code', 'code', 'effective_from'),
    )

    company_id = db.Column(db.Integer, db.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    country_code = db.Column(db.String(2), nullable=False, default='KE')
    company = db.relationship('Company', backref='statutory_rates')

    code = db.Column(db.String(50), nullable=False)  # e.g. SHIF_PERCENT, HOUSING_LEVY_PERCENT, PERSONAL_RELIEF
    effective_from = db.Column(db.Date, nullable=False)
    effective_to = db.Column(db.Date, nullable=True)  # NULL = still in force
    value = db.Column(db.Numeric(12, 4), nullable=False)  # percentage or amount in KES
    description = db.Column(db.String(500), nullable=True)


class PayeBracket(BaseModel):
    """PAYE tax bracket: min, max (nullable for top bracket), rate percent."""
    __tablename__ = 'paye_brackets'
    __table_args__ = (
        db.Index('ix_paye_brackets_scope_effective', 'company_id', 'country_code', 'effective_from', 'effective_to'),
    )

    company_id = db.Column(db.Integer, db.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    country_code = db.Column(db.String(2), nullable=False, default='KE')
    company = db.relationship('Company', backref='paye_brackets')

    effective_from = db.Column(db.Date, nullable=False)
    effective_to = db.Column(db.Date, nullable=True)
    bracket_order = db.Column(db.Integer, nullable=False, default=1)  # 1 = first bracket
    min_amount = db.Column(db.Numeric(12, 2), nullable=False)  # taxable pay min (monthly)
    max_amount = db.Column(db.Numeric(12, 2), nullable=True)   # NULL = no cap
    rate_percent = db.Column(db.Numeric(5, 2), nullable=False)


class NssfTier(BaseModel):
    """NSSF tier: lower/upper pensionable pay and employee + employer rates (Feb 2026)."""
    __tablename__ = 'nssf_tiers'
    __table_args__ = (
        db.Index('ix_nssf_tiers_scope_effective', 'company_id', 'country_code', 'effective_from', 'effective_to'),
    )

    company_id = db.Column(db.Integer, db.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    country_code = db.Column(db.String(2), nullable=False, default='KE')
    company = db.relationship('Company', backref='nssf_tiers')

    effective_from = db.Column(db.Date, nullable=False)
    effective_to = db.Column(db.Date, nullable=True)
    tier_number = db.Column(db.Integer, nullable=False)  # 1 or 2
    pensionable_min = db.Column(db.Numeric(12, 2), nullable=False)
    pensionable_max = db.Column(db.Numeric(12, 2), nullable=True)  # NULL = no pensionable cap for this tier
    employee_percent = db.Column(db.Numeric(5, 2), nullable=False)
    employer_percent = db.Column(db.Numeric(5, 2), nullable=False)
    # Optional cap on contribution amount (some tiers have max contribution)
    employee_max_amount = db.Column(db.Numeric(12, 2), nullable=True)
    employer_max_amount = db.Column(db.Numeric(12, 2), nullable=True)
