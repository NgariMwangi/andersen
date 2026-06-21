"""Email notifications for internal messages (Brevo)."""
from __future__ import annotations

import logging
from datetime import datetime
from html import escape

from flask import current_app, url_for
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.message import Message, MessageRecipient
from app.models.user import User
from app.services.brevo_service import brevo_configured, send_transactional_email
from app.services.message_service import _user_display_name, sender_display_name
from app.services.password_reset_service import external_base_url

logger = logging.getLogger(__name__)


def _app_name() -> str:
    return (current_app.config.get('APP_NAME') or 'HRMS').strip() or 'HRMS'


def _thread_url(thread_id: int) -> str:
    return external_base_url() + url_for('messages.thread', thread_id=thread_id)


def _user_email(user: User | None) -> str | None:
    if not user or not (user.email or '').strip():
        return None
    return user.email.strip().lower()


def _email_button(url: str, label: str = 'View message') -> str:
    return (
        f'<p><a href="{escape(url)}" style="display:inline-block;padding:10px 18px;'
        f'background:#ab0e1e;color:#fff;text-decoration:none;border-radius:6px;">{escape(label)}</a></p>'
    )


def _quote_block_html(message: Message) -> str:
    parent = message.parent
    if not parent:
        return ''
    parent_sender = escape(sender_display_name(parent.sender_user_id))
    parent_preview = escape(_message_preview(parent.body, 200)).replace(chr(10), '<br>')
    return (
        f'<div style="margin:0 0 0.75em;padding:0.5em 0.75em;border-left:3px solid #64748b;'
        f'background:#f1f5f9;border-radius:4px;font-size:13px;">'
        f'<div style="font-weight:600;color:#475569;margin-bottom:0.25em;">{parent_sender}</div>'
        f'<div style="color:#64748b;">{parent_preview}</div></div>'
    )


def _message_preview(body: str, limit: int = 400) -> str:
    text = (body or '').strip()
    if len(text) > limit:
        return text[: limit - 1] + '…'
    return text


def _quote_block_text(message: Message) -> str:
    parent = message.parent
    if not parent:
        return ''
    parent_sender = sender_display_name(parent.sender_user_id)
    return (
        f'Replying to {parent_sender}:\n'
        f'{_message_preview(parent.body, 200)}\n\n'
    )


def deliver_message_emails(message_id: int) -> dict:
    """
    Send recipient emails and sender confirmation for one message.
    Returns counts: {sent, failed, skipped, confirmation}.
    """
    logger.info('Message email delivery started message_id=%s', message_id)

    message = (
        db.session.query(Message)
        .options(
            joinedload(Message.thread),
            joinedload(Message.sender),
            joinedload(Message.parent).joinedload(Message.sender),
            joinedload(Message.recipients).joinedload(MessageRecipient.user),
        )
        .filter(Message.id == message_id)
        .first()
    )
    if not message:
        logger.error('Message email delivery aborted — message_id=%s not found', message_id)
        return {'sent': 0, 'failed': 0, 'skipped': 0, 'confirmation': False}

    stats = {'sent': 0, 'failed': 0, 'skipped': 0, 'confirmation': False}

    logger.info(
        'Message email context message_id=%s thread_id=%s send_email=%s recipient_rows=%s sender_user_id=%s',
        message.id,
        message.thread_id,
        message.send_email,
        len(message.recipients or []),
        message.sender_user_id,
    )

    if not message.send_email:
        logger.info('Message email delivery skipped — send_email=False message_id=%s', message_id)
        for rec in message.recipients:
            rec.email_status = 'skipped'
        db.session.commit()
        return stats

    if not brevo_configured():
        logger.error(
            'Message email delivery cannot proceed — Brevo not configured message_id=%s',
            message_id,
        )
        for rec in message.recipients:
            rec.email_status = 'failed'
        db.session.commit()
        stats['failed'] = len(message.recipients)
        return stats

    thread = message.thread
    if not thread:
        logger.error('Message email delivery aborted — no thread for message_id=%s', message_id)
        return stats

    app_name = _app_name()
    thread_link = _thread_url(thread.id)
    app_base = (current_app.config.get('APP_BASE_URL') or '').strip() or '(from request host)'
    logger.info('Message email thread_link=%s APP_BASE_URL=%r', thread_link, app_base)

    sender_name = sender_display_name(message.sender_user_id)
    subject_line = thread.subject if thread else 'Message'
    preview = escape(_message_preview(message.body))

    if not message.recipients:
        logger.warning(
            'Message email delivery — no recipient rows for message_id=%s (nothing to email)',
            message_id,
        )

    for rec in message.recipients:
        if rec.email_status == 'skipped':
            logger.info(
                'Message recipient skipped (pre-marked) message_id=%s user_id=%s',
                message_id,
                rec.user_id,
            )
            stats['skipped'] += 1
            continue
        email = _user_email(rec.user)
        if not email:
            logger.warning(
                'Message recipient has no email — skipped message_id=%s user_id=%s',
                message_id,
                rec.user_id,
            )
            rec.email_status = 'skipped'
            stats['skipped'] += 1
            continue

        logger.info(
            'Message emailing recipient message_id=%s user_id=%s email=%s',
            message_id,
            rec.user_id,
            email,
        )

        html = f"""
        <p>Hello,</p>
        <p><strong>{escape(sender_name)}</strong> sent you a message in {escape(app_name)}.</p>
        <p><strong>Subject:</strong> {escape(subject_line)}</p>
        {_quote_block_html(message)}
        <blockquote style="margin:1em 0;padding:0.75em 1em;border-left:3px solid #ab0e1e;background:#f8fafc;">
        {preview.replace(chr(10), '<br>')}
        </blockquote>
        {_email_button(thread_link)}
        <p style="color:#64748b;font-size:12px;">{escape(app_name)}</p>
        """
        text = (
            f'Message from {sender_name}\n'
            f'Subject: {subject_line}\n\n'
            f'{_quote_block_text(message)}'
            f'{_message_preview(message.body)}\n\n'
            f'View: {thread_link}\n'
        )
        ok = send_transactional_email(email, f'{app_name} — {subject_line}', html, text_content=text)
        rec.email_sent_at = datetime.utcnow()
        rec.email_status = 'sent' if ok else 'failed'
        if ok:
            stats['sent'] += 1
            logger.info('Message recipient email OK message_id=%s user_id=%s', message_id, rec.user_id)
        else:
            stats['failed'] += 1
            logger.error('Message recipient email FAILED message_id=%s user_id=%s email=%s', message_id, rec.user_id, email)

    sender = message.sender or db.session.get(User, message.sender_user_id)
    sender_email = _user_email(sender)
    recipient_count = len(message.recipients)
    if sender_email and recipient_count > 0:
        logger.info('Message sending confirmation email to sender=%s', sender_email)
        names = []
        for rec in message.recipients[:10]:
            if rec.user:
                names.append(_user_display_name(rec.user))
        name_summary = ', '.join(names)
        if recipient_count > 10:
            name_summary += f' and {recipient_count - 10} more'

        conf_subject = f'{app_name} — Message sent: {subject_line}'
        conf_html = f"""
        <p>Hello,</p>
        <p>Your message was delivered successfully to <strong>{recipient_count}</strong>
        recipient{'s' if recipient_count != 1 else ''}.</p>
        <p><strong>Subject:</strong> {escape(subject_line)}</p>
        <p><strong>To:</strong> {escape(name_summary)}</p>
        {_email_button(thread_link, 'Open conversation')}
        <p style="color:#64748b;font-size:12px;">{escape(app_name)}</p>
        """
        conf_text = (
            f'Your message was sent to {recipient_count} recipient(s).\n'
            f'Subject: {subject_line}\n'
            f'View: {thread_link}\n'
        )
        stats['confirmation'] = send_transactional_email(
            sender_email, conf_subject, conf_html, text_content=conf_text,
        )
        if stats['confirmation']:
            logger.info('Message sender confirmation email OK sender=%s', sender_email)
        else:
            logger.error('Message sender confirmation email FAILED sender=%s', sender_email)
    elif recipient_count > 0:
        logger.warning(
            'Message sender confirmation skipped — sender has no email message_id=%s sender_user_id=%s',
            message_id,
            message.sender_user_id,
        )

    db.session.commit()
    logger.info(
        'Message email delivery finished message_id=%s sent=%s failed=%s skipped=%s confirmation=%s',
        message_id,
        stats['sent'],
        stats['failed'],
        stats['skipped'],
        stats['confirmation'],
    )
    return stats
