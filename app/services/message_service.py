"""Internal messaging: create threads, replies, inbox queries."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.message import Message, MessageRecipient, MessageThread, MessageThreadParticipant
from app.models.user import User


THREAD_TYPE_DIRECT = 'direct'
THREAD_TYPE_GROUP = 'group'
THREAD_TYPE_BROADCAST = 'broadcast'


def company_user_choices(company_id: int, exclude_user_id: int | None = None) -> list[tuple[int, str]]:
    q = (
        db.session.query(User)
        .options(joinedload(User.employee))
        .filter(User.company_id == company_id, User.is_active.is_(True))
        .order_by(User.email)
    )
    if exclude_user_id:
        q = q.filter(User.id != exclude_user_id)
    rows = q.all()
    labels: list[tuple[int, str]] = []
    for u in rows:
        name = _user_display_name(u)
        labels.append((u.id, f'{name} ({u.email})'))
    return labels


def organization_recipient_ids(company_id: int, exclude_user_id: int | None = None) -> list[int]:
    q = db.session.query(User.id).filter(User.company_id == company_id, User.is_active.is_(True))
    if exclude_user_id:
        q = q.filter(User.id != exclude_user_id)
    return [row[0] for row in q.all()]


def resolve_recipient_user_ids(
    company_id: int,
    sender_user_id: int,
    recipient_type: str,
    selected_ids: list[int] | None,
    *,
    allow_broadcast: bool,
) -> list[int]:
    rtype = (recipient_type or '').strip()
    if rtype == 'organization':
        if not allow_broadcast:
            raise PermissionError('Not allowed to message the whole organization.')
        return organization_recipient_ids(company_id, exclude_user_id=sender_user_id)

    raw = selected_ids or []
    cleaned: list[int] = []
    seen: set[int] = set()
    for uid in raw:
        uid = int(uid)
        if uid == sender_user_id or uid in seen:
            continue
        user = db.session.get(User, uid)
        if not user or user.company_id != company_id or not user.is_active:
            continue
        seen.add(uid)
        cleaned.append(uid)

    if not cleaned:
        raise ValueError('Select at least one valid recipient.')

    if rtype == 'individual' and len(cleaned) != 1:
        raise ValueError('Select exactly one recipient for a direct message.')

    return cleaned


def _infer_thread_type(recipient_type: str, recipient_count: int) -> str:
    if recipient_type == 'organization':
        return THREAD_TYPE_BROADCAST
    if recipient_count == 1:
        return THREAD_TYPE_DIRECT
    return THREAD_TYPE_GROUP


def create_thread_with_message(
    *,
    company_id: int,
    sender_user_id: int,
    subject: str,
    body: str,
    recipient_user_ids: list[int],
    recipient_type: str,
    send_email: bool,
) -> MessageThread:
    thread_type = _infer_thread_type(recipient_type, len(recipient_user_ids))
    now = datetime.utcnow()

    thread = MessageThread(
        company_id=company_id,
        subject=subject.strip(),
        thread_type=thread_type,
        created_by_user_id=sender_user_id,
        created_at=now,
        updated_at=now,
    )
    db.session.add(thread)
    db.session.flush()

    participant_ids = set(recipient_user_ids)
    participant_ids.add(sender_user_id)
    for uid in participant_ids:
        db.session.add(MessageThreadParticipant(
            thread_id=thread.id,
            user_id=uid,
            last_read_at=now if uid == sender_user_id else None,
        ))

    message = _add_message_to_thread(
        thread,
        sender_user_id=sender_user_id,
        body=body,
        send_email=send_email,
        recipient_user_ids=recipient_user_ids,
        parent_message_id=None,
    )
    thread.updated_at = message.created_at
    return thread


def get_messages_after(thread_id: int, after_id: int) -> list[Message]:
    """New messages in a thread since the given message id."""
    return (
        db.session.query(Message)
        .filter(Message.thread_id == thread_id, Message.id > after_id)
        .options(
            joinedload(Message.sender),
            joinedload(Message.parent).joinedload(Message.sender),
            joinedload(Message.recipients),
        )
        .order_by(Message.created_at)
        .all()
    )


def get_thread_messages(thread_id: int) -> list[Message]:
    """Messages in a thread with sender and quoted parent loaded."""
    return (
        db.session.query(Message)
        .filter(Message.thread_id == thread_id)
        .options(
            joinedload(Message.sender),
            joinedload(Message.parent).joinedload(Message.sender),
            joinedload(Message.recipients),
        )
        .order_by(Message.created_at)
        .all()
    )


def parse_reply_parent_id(raw_value) -> int | None:
    if raw_value is None or raw_value == '':
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def resolve_reply_parent(thread_id: int, parent_message_id: int | None) -> int | None:
    """Validate that a reply target belongs to the same thread."""
    if not parent_message_id:
        return None
    parent = (
        db.session.query(Message.id)
        .filter(
            Message.id == int(parent_message_id),
            Message.thread_id == thread_id,
        )
        .first()
    )
    if not parent:
        raise ValueError('The message you are replying to was not found in this conversation.')
    return int(parent_message_id)


def reply_in_thread(
    thread: MessageThread,
    *,
    sender_user_id: int,
    body: str,
    send_email: bool,
    parent_message_id: int | None = None,
) -> Message:
    if not user_can_access_thread(thread, sender_user_id):
        raise PermissionError('You are not a participant in this conversation.')

    resolved_parent = resolve_reply_parent(thread.id, parent_message_id)

    recipient_ids = [
        p.user_id
        for p in thread.participants
        if p.user_id != sender_user_id
    ]
    message = _add_message_to_thread(
        thread,
        sender_user_id=sender_user_id,
        body=body,
        send_email=send_email,
        recipient_user_ids=recipient_ids,
        parent_message_id=resolved_parent,
    )
    thread.updated_at = message.created_at

    participant = _participant_row(thread.id, sender_user_id)
    if participant:
        participant.last_read_at = datetime.utcnow()

    return message


def _add_message_to_thread(
    thread: MessageThread,
    *,
    sender_user_id: int,
    body: str,
    send_email: bool,
    recipient_user_ids: list[int],
    parent_message_id: int | None,
) -> Message:
    now = datetime.utcnow()
    message = Message(
        thread_id=thread.id,
        parent_message_id=parent_message_id,
        sender_user_id=sender_user_id,
        body=body.strip(),
        send_email=bool(send_email),
        created_at=now,
        updated_at=now,
    )
    db.session.add(message)
    db.session.flush()

    for uid in recipient_user_ids:
        if uid == sender_user_id:
            continue
        db.session.add(MessageRecipient(
            message_id=message.id,
            user_id=uid,
            email_status='pending' if send_email else 'skipped',
            created_at=now,
            updated_at=now,
        ))
    return message


def user_can_access_thread(thread: MessageThread | None, user_id: int) -> bool:
    if not thread or not user_id:
        return False
    return _participant_row(thread.id, user_id) is not None


def _participant_row(thread_id: int, user_id: int) -> MessageThreadParticipant | None:
    return (
        db.session.query(MessageThreadParticipant)
        .filter(
            MessageThreadParticipant.thread_id == thread_id,
            MessageThreadParticipant.user_id == user_id,
        )
        .first()
    )


def mark_thread_read(thread: MessageThread, user_id: int) -> None:
    """Mark thread read for a participant and update per-message read receipts."""
    now = datetime.utcnow()
    participant = _participant_row(thread.id, user_id)
    if participant:
        participant.last_read_at = now

    thread_message_ids = select(Message.id).where(Message.thread_id == thread.id)
    (
        db.session.query(MessageRecipient)
        .filter(
            MessageRecipient.message_id.in_(thread_message_ids),
            MessageRecipient.user_id == user_id,
            MessageRecipient.read_at.is_(None),
        )
        .update(
            {MessageRecipient.read_at: now, MessageRecipient.updated_at: now},
            synchronize_session=False,
        )
    )


def message_read_status(message: Message, thread_type: str | None = None) -> str:
    """Return 'sent' (grey tick) or 'read' (blue double tick) for the sender's message."""
    recipients = list(message.recipients or [])
    if not recipients:
        return 'sent'
    if thread_type == THREAD_TYPE_BROADCAST:
        return 'sent'
    if all(recipient.read_at for recipient in recipients):
        return 'read'
    return 'sent'


def get_read_receipt_updates(
    thread_id: int,
    sender_user_id: int,
    thread_type: str | None = None,
) -> list[dict]:
    """Read-receipt status for messages sent by sender_user_id in a thread."""
    messages = (
        db.session.query(Message)
        .options(joinedload(Message.recipients))
        .filter(
            Message.thread_id == thread_id,
            Message.sender_user_id == sender_user_id,
        )
        .order_by(Message.id)
        .all()
    )
    return [
        {
            'message_id': message.id,
            'status': message_read_status(message, thread_type),
        }
        for message in messages
    ]


def get_thread_for_user(thread_id: int, company_id: int, user_id: int) -> MessageThread | None:
    thread = (
        db.session.query(MessageThread)
        .options(
            joinedload(MessageThread.participants).joinedload(MessageThreadParticipant.user),
            joinedload(MessageThread.messages).joinedload(Message.sender),
            joinedload(MessageThread.messages).joinedload(Message.parent).joinedload(Message.sender),
            joinedload(MessageThread.created_by),
        )
        .filter(MessageThread.id == thread_id, MessageThread.company_id == company_id)
        .first()
    )
    if not thread or not user_can_access_thread(thread, user_id):
        return None
    return thread


def inbox_threads(company_id: int, user_id: int) -> list[dict]:
    """Threads for inbox with preview and unread flag."""
    threads = (
        db.session.query(MessageThread)
        .join(MessageThreadParticipant)
        .filter(
            MessageThread.company_id == company_id,
            MessageThreadParticipant.user_id == user_id,
        )
        .options(
            joinedload(MessageThread.participants).joinedload(MessageThreadParticipant.user),
            joinedload(MessageThread.created_by),
        )
        .order_by(MessageThread.updated_at.desc())
        .all()
    )

    items: list[dict] = []
    for thread in threads:
        last_message = (
            db.session.query(Message)
            .filter(Message.thread_id == thread.id)
            .order_by(Message.created_at.desc())
            .first()
        )
        participant = _participant_row(thread.id, user_id)
        unread = _thread_has_unread(thread.id, user_id, participant.last_read_at if participant else None)
        items.append({
            'thread': thread,
            'last_message': last_message,
            'unread': unread,
            'label': thread_inbox_label(thread, user_id),
        })
    return items


def _thread_has_unread(thread_id: int, user_id: int, last_read_at: datetime | None) -> bool:
    q = db.session.query(Message.id).filter(
        Message.thread_id == thread_id,
        Message.sender_user_id != user_id,
    )
    if last_read_at:
        q = q.filter(Message.created_at > last_read_at)
    return q.limit(1).first() is not None


def unread_message_count(company_id: int, user_id: int) -> int:
    """Count of threads with at least one unread message for this user."""
    parts = (
        db.session.query(MessageThreadParticipant)
        .join(MessageThread, MessageThread.id == MessageThreadParticipant.thread_id)
        .filter(
            MessageThread.company_id == company_id,
            MessageThreadParticipant.user_id == user_id,
        )
        .all()
    )
    total = 0
    for part in parts:
        if _thread_has_unread(part.thread_id, user_id, part.last_read_at):
            total += 1
    return total


def latest_message_id_for_user(company_id: int, user_id: int) -> int:
    """Highest message id in any thread the user participates in."""
    row = (
        db.session.query(db.func.max(Message.id))
        .join(MessageThread, MessageThread.id == Message.thread_id)
        .join(
            MessageThreadParticipant,
            MessageThreadParticipant.thread_id == MessageThread.id,
        )
        .filter(
            MessageThread.company_id == company_id,
            MessageThreadParticipant.user_id == user_id,
        )
        .scalar()
    )
    return int(row or 0)


def poll_message_notifications(
    company_id: int,
    user_id: int,
    *,
    after_message_id: int = 0,
    exclude_thread_id: int | None = None,
) -> dict:
    """Unread badge count and new incoming messages since after_message_id."""
    unread_threads = unread_message_count(company_id, user_id)
    latest_message_id = latest_message_id_for_user(company_id, user_id)

    participant_thread_ids = [
        row[0]
        for row in (
            db.session.query(MessageThreadParticipant.thread_id)
            .join(MessageThread, MessageThread.id == MessageThreadParticipant.thread_id)
            .filter(
                MessageThread.company_id == company_id,
                MessageThreadParticipant.user_id == user_id,
            )
            .all()
        )
    ]

    notifications: list[dict] = []
    if participant_thread_ids:
        message_filters = [
            Message.thread_id.in_(participant_thread_ids),
            Message.sender_user_id != user_id,
            Message.id > after_message_id,
        ]
        if exclude_thread_id:
            message_filters.append(Message.thread_id != exclude_thread_id)

        q = (
            db.session.query(Message)
            .options(
                joinedload(Message.sender),
                joinedload(Message.thread),
            )
            .filter(*message_filters)
            .order_by(Message.id.asc())
            .limit(15)
        )

        for message in q.all():
            thread = message.thread
            preview = (message.body or '').strip()
            if len(preview) > 100:
                preview = preview[:99] + '…'
            notifications.append({
                'message_id': message.id,
                'thread_id': message.thread_id,
                'thread_subject': thread.subject if thread else 'Message',
                'sender_name': chat_sender_display_name(message.sender_user_id, user_id),
                'preview': preview,
            })
            if message.id > latest_message_id:
                latest_message_id = message.id

    return {
        'unread_threads': unread_threads,
        'latest_message_id': latest_message_id,
        'notifications': notifications,
    }


def thread_inbox_label(thread: MessageThread, current_user_id: int) -> str:
    if thread.thread_type == THREAD_TYPE_BROADCAST:
        return 'Whole organization'
    others = [
        p.user for p in (thread.participants or [])
        if p.user_id != current_user_id and p.user
    ]
    if not others:
        return thread.subject
    if len(others) == 1:
        return chat_sender_display_name(others[0].id, current_user_id)
    names = ', '.join(
        chat_sender_display_name(u.id, current_user_id) for u in others[:3]
    )
    if len(others) > 3:
        names += f' +{len(others) - 3} more'
    return names


def _user_display_name(user: User | None) -> str:
    if not user:
        return 'Unknown'
    emp = getattr(user, 'employee', None)
    if emp and hasattr(emp, 'full_name'):
        return emp.full_name
    return (user.email or '').split('@')[0] or f'User #{user.id}'


def sender_display_name(user_id: int | None) -> str:
    if not user_id:
        return 'Unknown'
    return _user_display_name(db.session.get(User, user_id))


def chat_sender_display_name(user_id: int | None, viewer_user_id: int) -> str:
    """Chat UI label: show 'Me' for the signed-in user instead of their name."""
    if user_id and user_id == viewer_user_id:
        return 'Me'
    return sender_display_name(user_id)
