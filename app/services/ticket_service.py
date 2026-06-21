"""IT ticket register: numbering, visibility, workflow."""
from __future__ import annotations

from datetime import date, datetime

from flask_login import UserMixin
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.it_ticket import (
    TICKET_PRIORITY_LABELS,
    TICKET_STATUS_CLOSED,
    TICKET_STATUS_IN_PROGRESS,
    TICKET_STATUS_LABELS,
    TICKET_STATUS_OPEN,
    TICKET_STATUS_RESOLVED,
    TICKET_STATUS_WAITING_ON_USER,
    Ticket,
    TicketCategory,
    TicketComment,
)
from app.models.user import User
from app.services.asset_service import employee_asset_rows, get_asset_for_company


DEFAULT_TICKET_CATEGORIES = [
    ('hardware', 'Hardware'),
    ('software', 'Software'),
    ('access', 'Access & accounts'),
    ('network', 'Network'),
    ('other', 'Other'),
]


def ensure_default_ticket_categories(company_id: int) -> None:
    for code, name in DEFAULT_TICKET_CATEGORIES:
        exists = (
            db.session.query(TicketCategory.id)
            .filter(TicketCategory.company_id == company_id, TicketCategory.code == code)
            .first()
        )
        if not exists:
            db.session.add(TicketCategory(company_id=company_id, code=code, name=name, is_active=True))
    db.session.commit()


def next_ticket_number(company_id: int) -> str:
    """Generate IT-YYYY-NNNN for the company."""
    year = date.today().year
    prefix = f'IT-{year}-'
    last = (
        db.session.query(Ticket.ticket_number)
        .filter(
            Ticket.company_id == company_id,
            Ticket.ticket_number.like(f'{prefix}%'),
        )
        .order_by(Ticket.id.desc())
        .first()
    )
    seq = 1
    if last and last[0]:
        try:
            seq = int(str(last[0]).split('-')[-1]) + 1
        except ValueError:
            seq = 1
    return f'{prefix}{seq:04d}'


def user_can_manage_tickets(user: UserMixin) -> bool:
    return bool(getattr(user, 'is_superuser', False) or user.has_permission('manage_tickets'))


def user_can_view_queue(user: UserMixin) -> bool:
    if getattr(user, 'is_superuser', False):
        return True
    return user.has_permission('view_tickets') or user.has_permission('manage_tickets')


def user_can_view_ticket(user: UserMixin, ticket: Ticket | None) -> bool:
    if ticket is None:
        return False
    if getattr(user, 'is_superuser', False):
        return True
    if user_can_view_queue(user):
        return True
    return int(ticket.requester_user_id or 0) == int(getattr(user, 'id', 0) or 0)


def get_ticket_for_company(ticket_id: int, company_id: int) -> Ticket | None:
    return (
        db.session.query(Ticket)
        .options(
            joinedload(Ticket.category),
            joinedload(Ticket.requester).joinedload(User.employee),
            joinedload(Ticket.assigned_to),
            joinedload(Ticket.related_asset),
            joinedload(Ticket.comments).joinedload(TicketComment.author),
        )
        .filter(Ticket.id == ticket_id, Ticket.company_id == company_id)
        .first()
    )


def my_tickets_query(company_id: int, user_id: int):
    return (
        db.session.query(Ticket)
        .options(joinedload(Ticket.category), joinedload(Ticket.assigned_to))
        .filter(Ticket.company_id == company_id, Ticket.requester_user_id == user_id)
    )


def queue_query(company_id: int):
    return (
        db.session.query(Ticket)
        .options(
            joinedload(Ticket.category),
            joinedload(Ticket.requester).joinedload(User.employee),
            joinedload(Ticket.assigned_to),
        )
        .filter(Ticket.company_id == company_id)
    )


def category_choices(company_id: int) -> list[tuple[int, str]]:
    rows = (
        db.session.query(TicketCategory)
        .filter(TicketCategory.company_id == company_id, TicketCategory.is_active.is_(True))
        .order_by(TicketCategory.name)
        .all()
    )
    return [(c.id, c.name) for c in rows]


def priority_choices() -> list[tuple[str, str]]:
    return list(TICKET_PRIORITY_LABELS.items())


def status_choices(*, include_closed: bool = True) -> list[tuple[str, str]]:
    choices = [
        (TICKET_STATUS_OPEN, TICKET_STATUS_LABELS[TICKET_STATUS_OPEN]),
        (TICKET_STATUS_IN_PROGRESS, TICKET_STATUS_LABELS[TICKET_STATUS_IN_PROGRESS]),
        (TICKET_STATUS_WAITING_ON_USER, TICKET_STATUS_LABELS[TICKET_STATUS_WAITING_ON_USER]),
        (TICKET_STATUS_RESOLVED, TICKET_STATUS_LABELS[TICKET_STATUS_RESOLVED]),
    ]
    if include_closed:
        choices.append((TICKET_STATUS_CLOSED, TICKET_STATUS_LABELS[TICKET_STATUS_CLOSED]))
    return choices


def it_assignee_choices(company_id: int) -> list[tuple[int, str]]:
    from app.models.user import Permission, Role, RolePermission, UserRole

    perm_ids = [
        row[0]
        for row in (
            db.session.query(Permission.id)
            .filter(Permission.code.in_(('view_tickets', 'manage_tickets')))
            .all()
        )
    ]
    if not perm_ids:
        return []
    rows = (
        db.session.query(User)
        .options(joinedload(User.employee))
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .filter(
            User.company_id == company_id,
            User.is_active.is_(True),
            RolePermission.permission_id.in_(perm_ids),
        )
        .distinct()
        .order_by(User.email)
        .all()
    )
    labels = []
    for user in rows:
        name = (user.email or '').strip()
        if user.employee:
            name = user.employee.full_name
        labels.append((user.id, name or f'User #{user.id}'))
    return labels


def requester_asset_choices(company_id: int, employee_id: int | None) -> list[tuple[int, str]]:
    """Assets currently assigned to the requester."""
    if not employee_id:
        return []
    choices: list[tuple[int, str]] = []
    for row in employee_asset_rows(employee_id, include_history=False):
        asset = row.asset
        if not asset or asset.company_id != company_id:
            continue
        label = asset.asset_tag
        detail = asset.name or (asset.category.name if asset.category else None)
        if detail:
            label = f'{label} — {detail}'
        choices.append((asset.id, label))
    return choices


def resolve_related_asset_id(
    *,
    company_id: int,
    employee_id: int | None,
    related_asset_id: int | None,
) -> int | None:
    if not related_asset_id:
        return None
    asset = get_asset_for_company(related_asset_id, company_id)
    if not asset:
        raise ValueError('Select a valid company asset.')
    if employee_id:
        active = asset.active_assignment
        if not active or int(active.employee_id) != int(employee_id):
            raise ValueError('You can only link assets currently assigned to you.')
    return asset.id


def create_ticket(
    *,
    company_id: int,
    requester_user_id: int,
    requester_employee_id: int | None,
    category_id: int,
    subject: str,
    description: str,
    priority: str,
    related_asset_id: int | None = None,
) -> Ticket:
    asset_id = resolve_related_asset_id(
        company_id=company_id,
        employee_id=requester_employee_id,
        related_asset_id=related_asset_id,
    )
    now = datetime.utcnow()
    ticket = Ticket(
        company_id=company_id,
        ticket_number=next_ticket_number(company_id),
        subject=subject.strip(),
        description=description.strip(),
        category_id=category_id,
        priority=priority,
        status=TICKET_STATUS_OPEN,
        requester_user_id=requester_user_id,
        requester_employee_id=requester_employee_id,
        related_asset_id=asset_id,
        created_at=now,
        updated_at=now,
    )
    db.session.add(ticket)
    db.session.flush()
    return ticket


def assign_ticket(ticket: Ticket, *, assigned_to_user_id: int) -> None:
    assignee = db.session.get(User, assigned_to_user_id)
    if not assignee or assignee.company_id != ticket.company_id:
        raise ValueError('Select a valid IT assignee.')
    ticket.assigned_to_user_id = assigned_to_user_id
    if ticket.status == TICKET_STATUS_OPEN:
        ticket.status = TICKET_STATUS_IN_PROGRESS
    ticket.updated_at = datetime.utcnow()


def set_ticket_status(ticket: Ticket, status: str) -> None:
    if status not in TICKET_STATUS_LABELS:
        raise ValueError('Invalid ticket status.')
    now = datetime.utcnow()
    ticket.status = status
    if status == TICKET_STATUS_RESOLVED and not ticket.resolved_at:
        ticket.resolved_at = now
    if status == TICKET_STATUS_CLOSED:
        ticket.closed_at = now
        if not ticket.resolved_at:
            ticket.resolved_at = now
    ticket.updated_at = now


def add_ticket_comment(
    ticket: Ticket,
    *,
    author_user_id: int,
    body: str,
) -> TicketComment:
    now = datetime.utcnow()
    comment = TicketComment(
        ticket_id=ticket.id,
        author_user_id=author_user_id,
        body=body.strip(),
        created_at=now,
        updated_at=now,
    )
    db.session.add(comment)
    ticket.updated_at = now
    return comment
