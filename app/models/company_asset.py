"""Company asset register and employee assignments."""
from __future__ import annotations

from app.extensions import db
from app.models.base import BaseModel


ASSET_STATUS_NOT_ASSIGNED = 'not_assigned'
ASSET_STATUS_ASSIGNED = 'assigned'
ASSET_STATUS_REPAIR = 'repair'
ASSET_STATUS_LOST = 'lost'
ASSET_STATUS_DISPOSED = 'disposed'

ASSET_STATUS_LABELS = {
    ASSET_STATUS_NOT_ASSIGNED: 'Not assigned',
    ASSET_STATUS_ASSIGNED: 'Assigned',
    ASSET_STATUS_REPAIR: 'In repair',
    ASSET_STATUS_LOST: 'Lost',
    ASSET_STATUS_DISPOSED: 'Disposed',
}


class AssetCategory(BaseModel):
    __tablename__ = 'asset_categories'
    __table_args__ = (
        db.UniqueConstraint('company_id', 'code', name='uq_asset_categories_company_code'),
    )

    company_id = db.Column(db.Integer, db.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    code = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    company = db.relationship('Company', backref=db.backref('asset_categories', lazy='dynamic'))
    assets = db.relationship('CompanyAsset', back_populates='category', lazy='dynamic')


class CompanyAsset(BaseModel):
    __tablename__ = 'company_assets'
    __table_args__ = (
        db.UniqueConstraint('company_id', 'asset_tag', name='uq_company_assets_company_tag'),
    )

    company_id = db.Column(db.Integer, db.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey('asset_categories.id', ondelete='SET NULL'), nullable=True, index=True)
    asset_tag = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(200), nullable=True)
    brand = db.Column(db.String(100), nullable=True)
    model = db.Column(db.String(100), nullable=True)
    serial_number = db.Column(db.String(100), nullable=True)
    description = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    purchase_date = db.Column(db.Date, nullable=True)
    purchase_value = db.Column(db.Numeric(14, 2), nullable=True)
    status = db.Column(db.String(30), nullable=False, default=ASSET_STATUS_NOT_ASSIGNED)

    company = db.relationship('Company', backref=db.backref('company_assets', lazy='dynamic'))
    category = db.relationship('AssetCategory', back_populates='assets')
    assignments = db.relationship(
        'AssetAssignment',
        back_populates='asset',
        cascade='all, delete-orphan',
        lazy='select',
        order_by='AssetAssignment.assigned_at.desc()',
    )

    @property
    def status_label(self) -> str:
        return ASSET_STATUS_LABELS.get(self.status or '', self.status or '—')

    @property
    def active_assignment(self):
        for row in self.assignments or []:
            if row.returned_at is None:
                return row
        return None

    @property
    def assignee(self):
        active = self.active_assignment
        return active.employee if active else None


class AssetAssignment(BaseModel):
    __tablename__ = 'asset_assignments'
    __table_args__ = (
        db.Index('ix_asset_assignments_asset_id', 'asset_id'),
        db.Index('ix_asset_assignments_employee_id', 'employee_id'),
    )

    asset_id = db.Column(db.Integer, db.ForeignKey('company_assets.id', ondelete='CASCADE'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False)
    assigned_at = db.Column(db.DateTime, nullable=False)
    returned_at = db.Column(db.DateTime, nullable=True)
    condition_on_issue = db.Column(db.String(200), nullable=True)
    condition_on_return = db.Column(db.String(200), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    assigned_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    returned_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    asset = db.relationship('CompanyAsset', back_populates='assignments')
    employee = db.relationship('Employee', backref=db.backref('asset_assignments', lazy='dynamic'))
    assigned_by = db.relationship('User', foreign_keys=[assigned_by_user_id])
    returned_by = db.relationship('User', foreign_keys=[returned_by_user_id])
