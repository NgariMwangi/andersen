"""
Department hierarchy.
"""
from app.extensions import db
from app.models.base import BaseModel


class Department(BaseModel):
    """Department with optional parent for hierarchy."""
    __tablename__ = 'departments'
    __table_args__ = (
        db.UniqueConstraint('company_id', 'code', name='uq_departments_company_code'),
        db.Index('ix_departments_parent_id', 'parent_id'),
    )

    company_id = db.Column(db.Integer, db.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    company = db.relationship('Company', backref='departments')

    code = db.Column(db.String(50), nullable=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('departments.id', ondelete='SET NULL'), nullable=True)

    parent = db.relationship('Department', remote_side='Department.id', backref='children')
