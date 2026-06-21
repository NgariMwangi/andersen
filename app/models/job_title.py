"""
Job positions and grades.
"""
from app.extensions import db
from app.models.base import BaseModel


class JobTitle(BaseModel):
    """Job title / position."""
    __tablename__ = 'job_titles'
    __table_args__ = (db.UniqueConstraint('company_id', 'code', name='uq_job_titles_company_code'),)

    company_id = db.Column(db.Integer, db.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    company = db.relationship('Company', backref='job_titles')

    code = db.Column(db.String(50), nullable=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    grade = db.Column(db.String(50), nullable=True)  # e.g. G5, G6
