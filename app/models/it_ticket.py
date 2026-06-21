"""IT helpdesk tickets and comments."""
from __future__ import annotations

from app.extensions import db
from app.models.base import BaseModel


TICKET_STATUS_OPEN = 'open'
TICKET_STATUS_IN_PROGRESS = 'in_progress'
TICKET_STATUS_WAITING_ON_USER = 'waiting_on_user'
TICKET_STATUS_RESOLVED = 'resolved'
TICKET_STATUS_CLOSED = 'closed'

TICKET_STATUS_LABELS = {
    TICKET_STATUS_OPEN: 'Open',
    TICKET_STATUS_IN_PROGRESS: 'In progress',
    TICKET_STATUS_WAITING_ON_USER: 'Waiting on user',
    TICKET_STATUS_RESOLVED: 'Resolved',
    TICKET_STATUS_CLOSED: 'Closed',
}

TICKET_PRIORITY_LOW = 'low'
TICKET_PRIORITY_NORMAL = 'normal'
TICKET_PRIORITY_HIGH = 'high'
TICKET_PRIORITY_URGENT = 'urgent'

TICKET_PRIORITY_LABELS = {
    TICKET_PRIORITY_LOW: 'Low',
    TICKET_PRIORITY_NORMAL: 'Normal',
    TICKET_PRIORITY_HIGH: 'High',
    TICKET_PRIORITY_URGENT: 'Urgent',
}


class TicketCategory(BaseModel):
    __tablename__ = 'ticket_categories'
    __table_args__ = (
        db.UniqueConstraint('company_id', 'code', name='uq_ticket_categories_company_code'),
    )

    company_id = db.Column(db.Integer, db.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    code = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    company = db.relationship('Company', backref=db.backref('ticket_categories', lazy='dynamic'))
    tickets = db.relationship('Ticket', back_populates='category', lazy='dynamic')


class Ticket(BaseModel):
    __tablename__ = 'tickets'
    __table_args__ = (
        db.UniqueConstraint('company_id', 'ticket_number', name='uq_tickets_company_number'),
        db.Index('ix_tickets_company_id', 'company_id'),
        db.Index('ix_tickets_status', 'status'),
    )

    company_id = db.Column(db.Integer, db.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    ticket_number = db.Column(db.String(30), nullable=False)
    subject = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text, nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('ticket_categories.id', ondelete='SET NULL'), nullable=True)
    priority = db.Column(db.String(20), nullable=False, default=TICKET_PRIORITY_NORMAL)
    status = db.Column(db.String(30), nullable=False, default=TICKET_STATUS_OPEN)
    requester_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    requester_employee_id = db.Column(db.Integer, db.ForeignKey('employees.id', ondelete='SET NULL'), nullable=True)
    assigned_to_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    related_asset_id = db.Column(db.Integer, db.ForeignKey('company_assets.id', ondelete='SET NULL'), nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)

    company = db.relationship('Company', backref=db.backref('tickets', lazy='dynamic'))
    category = db.relationship('TicketCategory', back_populates='tickets')
    requester = db.relationship('User', foreign_keys=[requester_user_id])
    requester_employee = db.relationship('Employee', foreign_keys=[requester_employee_id])
    assigned_to = db.relationship('User', foreign_keys=[assigned_to_user_id])
    related_asset = db.relationship('CompanyAsset', foreign_keys=[related_asset_id])
    comments = db.relationship(
        'TicketComment',
        back_populates='ticket',
        cascade='all, delete-orphan',
        lazy='select',
        order_by='TicketComment.created_at',
    )

    @property
    def status_label(self) -> str:
        return TICKET_STATUS_LABELS.get(self.status or '', self.status or '—')

    @property
    def priority_label(self) -> str:
        return TICKET_PRIORITY_LABELS.get(self.priority or '', self.priority or '—')


class TicketComment(BaseModel):
    __tablename__ = 'ticket_comments'
    __table_args__ = (
        db.Index('ix_ticket_comments_ticket_id', 'ticket_id'),
    )

    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False)
    author_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    body = db.Column(db.Text, nullable=False)

    ticket = db.relationship('Ticket', back_populates='comments')
    author = db.relationship('User', foreign_keys=[author_user_id])
