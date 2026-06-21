"""Tenant company and physical branches (e.g. per country)."""
from app.extensions import db
from app.models.base import BaseModel


class Company(BaseModel):
    """Organization using the HRMS (multi-tenant key)."""
    __tablename__ = 'companies'
    __table_args__ = (db.Index('ix_companies_name', 'name'),)

    name = db.Column(db.String(200), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    branches = db.relationship('Branch', back_populates='company', lazy='dynamic')
    employer_profile = db.relationship(
        'Employer',
        back_populates='company',
        uselist=False,
        cascade='all, delete-orphan',
    )


class Branch(BaseModel):
    """Office / site; country drives public holidays and statutory rate packs."""
    __tablename__ = 'branches'
    __table_args__ = (
        db.Index('ix_branches_company_id', 'company_id'),
        db.UniqueConstraint('company_id', 'name', name='uq_branches_company_name'),
    )

    company_id = db.Column(db.Integer, db.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    # ISO 3166-1 alpha-2 (e.g. KE, UG)
    country_code = db.Column(db.String(2), nullable=False, default='KE')
    # ISO 4217 (e.g. KES, UGX); null = infer from country_code via app mapping
    currency_code = db.Column(db.String(3), nullable=True)
    timezone = db.Column(db.String(64), nullable=True)

    company = db.relationship('Company', back_populates='branches')
