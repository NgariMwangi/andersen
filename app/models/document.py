"""
Employee document management - contracts, ID, KRA PIN, etc.
"""
from app.extensions import db
from app.models.base import BaseModel


class DocumentCategory(db.Model):
    """Category: Contract, ID, KRA PIN, NSSF, Certificate, etc."""
    __tablename__ = 'document_categories'
    __table_args__ = (db.UniqueConstraint('company_id', 'code', name='uq_document_categories_company_code'),)

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    company = db.relationship('Company', backref='document_categories')

    code = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    track_expiry = db.Column(db.Boolean, default=False, nullable=False)


class EmployeeDocument(BaseModel):
    """Uploaded document linked to employee."""
    __tablename__ = 'employee_documents'
    __table_args__ = (
        db.Index('ix_employee_documents_employee_id', 'employee_id'),
        db.Index('ix_employee_documents_category_id', 'category_id'),
    )

    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('document_categories.id', ondelete='SET NULL'), nullable=True)
    name = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=True)  # as chosen at upload
    file_path = db.Column(db.String(500), nullable=False)  # relative storage path
    file_size = db.Column(db.Integer, nullable=True)
    expiry_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    # Employee self-service uploads require HR approval; HR uploads default to approved.
    approval_status = db.Column(db.String(20), nullable=False, default='approved', server_default='approved')
    uploaded_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_notes = db.Column(db.Text, nullable=True)

    employee = db.relationship('Employee', backref='documents')
    category = db.relationship('DocumentCategory', backref='documents')
    uploaded_by = db.relationship('User', foreign_keys=[uploaded_by_user_id])
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_user_id])

    @property
    def is_pending_approval(self) -> bool:
        return self.approval_status == 'pending'

    @property
    def approval_status_label(self) -> str:
        labels = {
            'approved': 'Approved',
            'pending': 'Pending HR approval',
            'rejected': 'Rejected',
        }
        return labels.get(self.approval_status or 'approved', (self.approval_status or 'approved').title())

    @property
    def file_extension(self) -> str:
        """Lowercase extension from stored path, e.g. pdf, docx."""
        path = (self.file_path or '').replace('\\', '/').strip()
        if not path or path.startswith('cld::') or path.startswith(('http://', 'https://')):
            return ''
        filename = path.rsplit('/', 1)[-1]
        if '.' not in filename:
            return ''
        return filename.rsplit('.', 1)[-1].lower()

    @property
    def display_filename(self) -> str:
        """Filename as shown to users (original upload name when available)."""
        if self.original_filename:
            return self.original_filename
        ext = self.file_extension
        name = (self.name or '').strip() or 'Document'
        if ext and not name.lower().endswith(f'.{ext}'):
            return f'{name}.{ext}'
        return name
