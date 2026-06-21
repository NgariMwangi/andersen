"""IT helpdesk tickets."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.decorators.permissions import permission_required
from app.extensions import db
from app.forms.ticket_forms import (
    AssignTicketForm,
    TicketCategoryForm,
    TicketCommentForm,
    TicketForm,
    TicketStatusForm,
)
from app.models.it_ticket import TICKET_PRIORITY_LABELS, TICKET_STATUS_LABELS, Ticket, TicketCategory
from app.services.ticket_notification_service import (
    notify_ticket_assigned,
    notify_ticket_comment,
    notify_ticket_created,
    notify_ticket_status_changed,
)
from app.services.ticket_service import (
    add_ticket_comment,
    assign_ticket,
    category_choices,
    create_ticket,
    ensure_default_ticket_categories,
    get_ticket_for_company,
    it_assignee_choices,
    my_tickets_query,
    priority_choices,
    queue_query,
    requester_asset_choices,
    set_ticket_status,
    status_choices,
    user_can_manage_tickets,
    user_can_view_queue,
    user_can_view_ticket,
)
from app.utils.tenant import require_company_id

it_tickets_bp = Blueprint('it_tickets', __name__)


def _populate_ticket_form(form: TicketForm, company_id: int, user=None) -> None:
    form.category_id.choices = category_choices(company_id)
    form.priority.choices = priority_choices()
    employee_id = getattr(user, 'employee_id', None) if user else None
    asset_choices = requester_asset_choices(company_id, employee_id)
    form.related_asset_id.choices = [(0, '— No asset / not applicable —')] + asset_choices


@it_tickets_bp.route('/')
@login_required
def index():
    if user_can_view_queue(current_user):
        return redirect(url_for('it_tickets.queue'))
    if current_user.has_permission('submit_tickets'):
        return redirect(url_for('it_tickets.my_tickets'))
    abort(403)


@it_tickets_bp.route('/my')
@login_required
@permission_required('submit_tickets')
def my_tickets():
    cid = require_company_id()
    status_filter = (request.args.get('status') or '').strip()
    q = my_tickets_query(cid, current_user.id)
    if status_filter and status_filter in TICKET_STATUS_LABELS:
        q = q.filter_by(status=status_filter)
    tickets = q.order_by(Ticket.updated_at.desc()).all()
    return render_template(
        'it_tickets/my_tickets.html',
        tickets=tickets,
        status_filter=status_filter,
        status_labels=TICKET_STATUS_LABELS,
        priority_labels=TICKET_PRIORITY_LABELS,
    )


@it_tickets_bp.route('/queue')
@login_required
@permission_required('view_tickets')
def queue():
    cid = require_company_id()
    ensure_default_ticket_categories(cid)
    status_filter = (request.args.get('status') or '').strip()
    category_filter = request.args.get('category', type=int)
    assignee_filter = request.args.get('assignee', type=int)
    priority_filter = (request.args.get('priority') or '').strip()

    q = queue_query(cid)
    if status_filter and status_filter in TICKET_STATUS_LABELS:
        q = q.filter_by(status=status_filter)
    if category_filter:
        q = q.filter_by(category_id=category_filter)
    if assignee_filter:
        q = q.filter_by(assigned_to_user_id=assignee_filter)
    if priority_filter and priority_filter in TICKET_PRIORITY_LABELS:
        q = q.filter_by(priority=priority_filter)

    tickets = q.order_by(Ticket.updated_at.desc()).all()
    return render_template(
        'it_tickets/queue.html',
        tickets=tickets,
        status_filter=status_filter,
        category_filter=category_filter,
        assignee_filter=assignee_filter,
        priority_filter=priority_filter,
        categories=category_choices(cid),
        assignees=it_assignee_choices(cid),
        status_labels=TICKET_STATUS_LABELS,
        priority_labels=TICKET_PRIORITY_LABELS,
        can_manage=user_can_manage_tickets(current_user),
    )


@it_tickets_bp.route('/create', methods=['GET', 'POST'])
@login_required
@permission_required('submit_tickets')
def create():
    cid = require_company_id()
    ensure_default_ticket_categories(cid)
    form = TicketForm()
    _populate_ticket_form(form, cid, current_user)
    if form.validate_on_submit():
        asset_id = form.related_asset_id.data or None
        if asset_id == 0:
            asset_id = None
        try:
            ticket = create_ticket(
                company_id=cid,
                requester_user_id=current_user.id,
                requester_employee_id=getattr(current_user, 'employee_id', None),
                category_id=form.category_id.data,
                subject=form.subject.data,
                description=form.description.data,
                priority=form.priority.data,
                related_asset_id=asset_id,
            )
            db.session.commit()
            notify_ticket_created(ticket.id)
            db.session.commit()
            flash(f'Ticket {ticket.ticket_number} submitted.', 'success')
            return redirect(url_for('it_tickets.view', id=ticket.id))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
    has_assigned_assets = len(form.related_asset_id.choices) > 1
    return render_template(
        'it_tickets/create.html',
        form=form,
        has_assigned_assets=has_assigned_assets,
    )


@it_tickets_bp.route('/<int:id>')
@login_required
def view(id):
    cid = require_company_id()
    ticket = get_ticket_for_company(id, cid)
    if not ticket or not user_can_view_ticket(current_user, ticket):
        abort(404)
    can_manage = user_can_manage_tickets(current_user)
    assign_form = AssignTicketForm()
    status_form = TicketStatusForm()
    comment_form = TicketCommentForm()
    if can_manage:
        assign_form.assigned_to_user_id.choices = it_assignee_choices(cid)
        status_form.status.choices = status_choices()
        if ticket.assigned_to_user_id:
            assign_form.assigned_to_user_id.data = ticket.assigned_to_user_id
        status_form.status.data = ticket.status
    return render_template(
        'it_tickets/view.html',
        ticket=ticket,
        assign_form=assign_form,
        status_form=status_form,
        comment_form=comment_form,
        status_labels=TICKET_STATUS_LABELS,
        priority_labels=TICKET_PRIORITY_LABELS,
        can_manage=can_manage,
    )


@it_tickets_bp.route('/<int:id>/assign', methods=['POST'])
@login_required
@permission_required('manage_tickets')
def assign(id):
    cid = require_company_id()
    ticket = get_ticket_for_company(id, cid)
    if not ticket:
        abort(404)
    form = AssignTicketForm()
    form.assigned_to_user_id.choices = it_assignee_choices(cid)
    if form.validate_on_submit():
        try:
            assign_ticket(ticket, assigned_to_user_id=form.assigned_to_user_id.data)
            db.session.commit()
            notify_ticket_assigned(ticket.id)
            db.session.commit()
            flash('Ticket assigned.', 'success')
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
    return redirect(url_for('it_tickets.view', id=id))


@it_tickets_bp.route('/<int:id>/status', methods=['POST'])
@login_required
@permission_required('manage_tickets')
def update_status(id):
    cid = require_company_id()
    ticket = get_ticket_for_company(id, cid)
    if not ticket:
        abort(404)
    form = TicketStatusForm()
    form.status.choices = status_choices()
    if form.validate_on_submit():
        try:
            set_ticket_status(ticket, form.status.data)
            db.session.commit()
            notify_ticket_status_changed(ticket.id)
            db.session.commit()
            flash('Ticket status updated.', 'success')
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
    return redirect(url_for('it_tickets.view', id=id))


@it_tickets_bp.route('/<int:id>/comment', methods=['POST'])
@login_required
def add_comment(id):
    cid = require_company_id()
    ticket = get_ticket_for_company(id, cid)
    if not ticket or not user_can_view_ticket(current_user, ticket):
        abort(404)
    if ticket.status == 'closed' and not user_can_manage_tickets(current_user):
        flash('This ticket is closed.', 'warning')
        return redirect(url_for('it_tickets.view', id=id))
    form = TicketCommentForm()
    if form.validate_on_submit():
        comment = add_ticket_comment(
            ticket,
            author_user_id=current_user.id,
            body=form.body.data,
        )
        db.session.commit()
        notify_ticket_comment(ticket.id, comment.id)
        db.session.commit()
        flash('Comment added.', 'success')
    else:
        flash('Enter a comment.', 'danger')
    return redirect(url_for('it_tickets.view', id=id))


@it_tickets_bp.route('/categories', methods=['GET', 'POST'])
@login_required
@permission_required('manage_tickets')
def categories():
    cid = require_company_id()
    ensure_default_ticket_categories(cid)
    form = TicketCategoryForm()
    if form.validate_on_submit():
        code = form.code.data.strip().lower().replace(' ', '_')
        exists = (
            db.session.query(TicketCategory.id)
            .filter(TicketCategory.company_id == cid, TicketCategory.code == code)
            .first()
        )
        if exists:
            flash('A category with this code already exists.', 'danger')
        else:
            db.session.add(
                TicketCategory(
                    company_id=cid,
                    code=code,
                    name=form.name.data.strip(),
                    is_active=True,
                )
            )
            db.session.commit()
            flash('Category added.', 'success')
            return redirect(url_for('it_tickets.categories'))
    rows = (
        db.session.query(TicketCategory)
        .filter(TicketCategory.company_id == cid)
        .order_by(TicketCategory.name)
        .all()
    )
    return render_template('it_tickets/categories.html', form=form, categories=rows)
