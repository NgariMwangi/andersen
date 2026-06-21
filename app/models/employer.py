"""
Employer legal / payroll identity — one profile per tenant Company.
"""
from decimal import Decimal

from app.extensions import db
from app.models.base import BaseModel


class Employer(BaseModel):
    __tablename__ = 'employers'

    company_id = db.Column(db.Integer, db.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, unique=True)
    company = db.relationship('Company', back_populates='employer_profile')

    # Common employer identifiers
    name = db.Column(db.String(250), nullable=False, default='')
    kra_pin = db.Column(db.String(30), nullable=True)

    # Contacts
    email = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(40), nullable=True)

    # Addresses
    physical_address = db.Column(db.Text, nullable=True)
    postal_address = db.Column(db.String(255), nullable=True)

    # Optional identifiers (useful for payroll/statutory docs)
    registration_number = db.Column(db.String(80), nullable=True)
    welfare_kit_deduction = db.Column(db.Numeric(14, 2), nullable=False, default=Decimal('0'))

    def __repr__(self) -> str:
        return f"<Employer id={self.id} name={self.name!r}>"

