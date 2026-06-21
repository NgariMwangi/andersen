"""Internal messaging: threaded conversations with optional email delivery."""
from datetime import datetime

from app.extensions import db
from app.models.base import BaseModel


class MessageThread(BaseModel):
    """Conversation thread (direct, group, or organization broadcast)."""
    __tablename__ = 'message_threads'

    company_id = db.Column(db.Integer, db.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    subject = db.Column(db.String(300), nullable=False)
    thread_type = db.Column(db.String(20), nullable=False, default='direct')  # direct, group, broadcast
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    company = db.relationship('Company', backref=db.backref('message_threads', lazy='dynamic'))
    created_by = db.relationship('User', foreign_keys=[created_by_user_id])
    participants = db.relationship(
        'MessageThreadParticipant',
        back_populates='thread',
        cascade='all, delete-orphan',
        lazy='select',
    )
    messages = db.relationship(
        'Message',
        back_populates='thread',
        cascade='all, delete-orphan',
        lazy='select',
        order_by='Message.created_at',
    )


class MessageThreadParticipant(BaseModel):
    """Users who can read and reply in a thread."""
    __tablename__ = 'message_thread_participants'
    __table_args__ = (
        db.UniqueConstraint('thread_id', 'user_id', name='uq_message_thread_participants'),
    )

    thread_id = db.Column(db.Integer, db.ForeignKey('message_threads.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    last_read_at = db.Column(db.DateTime, nullable=True)

    thread = db.relationship('MessageThread', back_populates='participants')
    user = db.relationship('User', backref=db.backref('message_thread_participations', lazy='dynamic'))


class Message(BaseModel):
    """One message in a thread (original or reply)."""
    __tablename__ = 'messages'

    thread_id = db.Column(db.Integer, db.ForeignKey('message_threads.id', ondelete='CASCADE'), nullable=False, index=True)
    parent_message_id = db.Column(db.Integer, db.ForeignKey('messages.id', ondelete='SET NULL'), nullable=True)
    sender_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    body = db.Column(db.Text, nullable=False)
    send_email = db.Column(db.Boolean, default=False, nullable=False)

    thread = db.relationship('MessageThread', back_populates='messages')
    parent = db.relationship('Message', remote_side='Message.id', backref='replies')
    sender = db.relationship('User', foreign_keys=[sender_user_id])
    recipients = db.relationship(
        'MessageRecipient',
        back_populates='message',
        cascade='all, delete-orphan',
        lazy='select',
    )


class MessageRecipient(BaseModel):
    """Delivery + read state for each recipient of a message (not the sender)."""
    __tablename__ = 'message_recipients'
    __table_args__ = (
        db.UniqueConstraint('message_id', 'user_id', name='uq_message_recipients'),
    )

    message_id = db.Column(db.Integer, db.ForeignKey('messages.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    read_at = db.Column(db.DateTime, nullable=True)
    email_status = db.Column(db.String(20), nullable=True)  # sent, failed, skipped, pending
    email_sent_at = db.Column(db.DateTime, nullable=True)

    message = db.relationship('Message', back_populates='recipients')
    user = db.relationship('User', backref=db.backref('message_receipts', lazy='dynamic'))
