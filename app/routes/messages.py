"""Internal messaging routes."""
import logging

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db, limiter
from app.forms.message_forms import ComposeMessageForm, ReplyMessageForm
from app.models.message import Message
from app.services.message_notification_service import deliver_message_emails
from app.services.message_service import (
    company_user_choices,
    create_thread_with_message,
    chat_sender_display_name,
    get_messages_after,
    get_read_receipt_updates,
    get_thread_for_user,
    get_thread_messages,
    inbox_threads,
    latest_message_id_for_user,
    mark_thread_read,
    message_read_status,
    parse_reply_parent_id,
    poll_message_notifications,
    reply_in_thread,
    resolve_recipient_user_ids,
    unread_message_count,
)
from app.utils.tenant import require_company_id

messages_bp = Blueprint('messages', __name__)
logger = logging.getLogger(__name__)

POLL_INTERVAL_MS = 2500


def _can_broadcast() -> bool:
    return current_user.has_permission('send_broadcast_messages')


def _wants_json() -> bool:
    return (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.accept_mimetypes.best_match(['application/json', 'text/html']) == 'application/json'
    )


def _thread_display_context(msg_thread, messages_list):
    messages_by_id = {m.id: m for m in messages_list}
    participants = [p.user for p in msg_thread.participants if p.user]
    show_sender_names = (
        msg_thread.thread_type in ('group', 'broadcast')
        or len(participants) > 2
    )
    return {
        'thread': msg_thread,
        'messages_by_id': messages_by_id,
        'participants': participants,
        'show_sender_names': show_sender_names,
        'chat_sender_name': lambda uid: chat_sender_display_name(uid, current_user.id),
        'message_read_status': lambda msg: message_read_status(msg, msg_thread.thread_type),
    }


def _render_message_rows(messages, ctx: dict) -> str:
    return render_template(
        'messages/_message_rows.html',
        messages=messages,
        current_user=current_user,
        **ctx,
    )


def _prepare_thread_panel(cid: int, thread_id: int, *, reply_to_id: int | None = None):
    msg_thread = get_thread_for_user(thread_id, cid, current_user.id)
    if not msg_thread:
        return None

    mark_thread_read(msg_thread, current_user.id)
    db.session.commit()

    messages_list = get_thread_messages(thread_id)
    ctx = _thread_display_context(msg_thread, messages_list)
    reply_form = ReplyMessageForm()
    if reply_to_id:
        reply_form.reply_to_message_id.data = reply_to_id

    panel_html = render_template(
        'messages/_thread_panel.html',
        messages=messages_list,
        reply_form=reply_form,
        initial_reply_to=reply_to_id,
        poll_interval_ms=POLL_INTERVAL_MS,
        current_user=current_user,
        **ctx,
    )
    return {
        'msg_thread': msg_thread,
        'messages_list': messages_list,
        'ctx': ctx,
        'reply_form': reply_form,
        'panel_html': panel_html,
    }


def _render_workspace(cid: int, thread_id: int | None = None, *, reply_to_id: int | None = None):
    items = inbox_threads(cid, current_user.id)
    prepared = None
    chat_sender_name = lambda uid: chat_sender_display_name(uid, current_user.id)

    if thread_id:
        prepared = _prepare_thread_panel(cid, thread_id, reply_to_id=reply_to_id)
        if not prepared:
            abort(404)

    thread = prepared['ctx']['thread'] if prepared else None
    participants = prepared['ctx']['participants'] if prepared else []
    show_sender_names = prepared['ctx']['show_sender_names'] if prepared else False
    read_status_fn = (
        prepared['ctx']['message_read_status']
        if prepared
        else lambda msg: message_read_status(msg, None)
    )

    return render_template(
        'messages/workspace.html',
        items=items,
        active_thread_id=thread_id,
        selected_thread_id=thread_id,
        thread=thread,
        participants=participants,
        show_sender_names=show_sender_names,
        chat_sender_name=chat_sender_name,
        message_read_status=read_status_fn,
        messages=prepared['messages_list'] if prepared else [],
        messages_by_id=prepared['ctx']['messages_by_id'] if prepared else {},
        reply_form=prepared['reply_form'] if prepared else ReplyMessageForm(),
        initial_reply_to=reply_to_id if prepared else None,
        poll_interval_ms=POLL_INTERVAL_MS,
    )


def _flash_send_result(stats: dict, *, is_reply: bool = False) -> None:
    label = 'Reply' if is_reply else 'Message'
    if stats.get('failed'):
        flash(f'{label} saved. Some emails could not be delivered.', 'warning')
    elif stats.get('confirmation'):
        flash(f'{label} sent. A confirmation email was sent to you.', 'success')
    else:
        flash(f'{label} sent.', 'success')


@messages_bp.route('/notifications/poll')
@login_required
@limiter.exempt
def notifications_poll():
    cid = require_company_id()
    init = request.args.get('init', type=int)
    after_id = request.args.get('after', type=int)
    exclude_thread_id = request.args.get('exclude_thread', type=int)

    if init:
        return jsonify({
            'ok': True,
            'unread_threads': unread_message_count(cid, current_user.id),
            'latest_message_id': latest_message_id_for_user(cid, current_user.id),
            'notifications': [],
        })

    result = poll_message_notifications(
        cid,
        current_user.id,
        after_message_id=after_id or 0,
        exclude_thread_id=exclude_thread_id,
    )
    return jsonify({'ok': True, **result})


@messages_bp.route('/inbox/poll')
@login_required
@limiter.exempt
def inbox_poll():
    cid = require_company_id()
    init = request.args.get('init', type=int)
    after_id = request.args.get('after', type=int)
    latest = latest_message_id_for_user(cid, current_user.id)

    active_thread_id = request.args.get('active_thread', type=int)

    if init:
        return jsonify({
            'ok': True,
            'changed': False,
            'latest_message_id': latest,
        })

    force_refresh = request.args.get('refresh', type=int)
    if force_refresh:
        items = inbox_threads(cid, current_user.id)
        return jsonify({
            'ok': True,
            'changed': True,
            'latest_message_id': latest,
            'unread_threads': unread_message_count(cid, current_user.id),
            'html': render_template(
                'messages/_inbox_content.html',
                items=items,
                active_thread_id=active_thread_id,
                current_user=current_user,
                chat_sender_name=lambda uid: chat_sender_display_name(uid, current_user.id),
            ),
        })

    if after_id is not None and latest <= after_id:
        return jsonify({
            'ok': True,
            'changed': False,
            'latest_message_id': latest,
        })

    items = inbox_threads(cid, current_user.id)
    return jsonify({
        'ok': True,
        'changed': True,
        'latest_message_id': latest,
        'unread_threads': unread_message_count(cid, current_user.id),
        'html': render_template(
            'messages/_inbox_content.html',
            items=items,
            active_thread_id=active_thread_id,
            current_user=current_user,
            chat_sender_name=lambda uid: chat_sender_display_name(uid, current_user.id),
        ),
    })


@messages_bp.route('/')
@login_required
def index():
    cid = require_company_id()
    return _render_workspace(cid)


@messages_bp.route('/<int:thread_id>/panel')
@login_required
def thread_panel(thread_id):
    cid = require_company_id()
    reply_to_id = request.args.get('reply_to', type=int)
    prepared = _prepare_thread_panel(cid, thread_id, reply_to_id=reply_to_id)
    if not prepared:
        abort(404)
    return jsonify({
        'ok': True,
        'thread_id': thread_id,
        'title': prepared['msg_thread'].subject,
        'html': prepared['panel_html'],
        'unread_threads': unread_message_count(cid, current_user.id),
    })


@messages_bp.route('/compose', methods=['GET', 'POST'])
@login_required
def compose():
    cid = require_company_id()
    can_broadcast = _can_broadcast()
    form = ComposeMessageForm(can_broadcast=can_broadcast)
    form.recipient_ids.choices = company_user_choices(cid, exclude_user_id=current_user.id)

    if form.validate_on_submit():
        try:
            recipient_ids = resolve_recipient_user_ids(
                cid,
                current_user.id,
                form.recipient_type.data,
                form.recipient_ids.data,
                allow_broadcast=can_broadcast,
            )
            thread = create_thread_with_message(
                company_id=cid,
                sender_user_id=current_user.id,
                subject=form.subject.data,
                body=form.body.data,
                recipient_user_ids=recipient_ids,
                recipient_type=form.recipient_type.data,
                send_email=form.send_email.data,
            )
            db.session.commit()

            last_msg = (
                db.session.query(Message)
                .filter(Message.thread_id == thread.id)
                .order_by(Message.id.desc())
                .first()
            )
            if form.send_email.data and last_msg:
                logger.info(
                    'Compose triggering email delivery message_id=%s thread_id=%s recipients=%s',
                    last_msg.id,
                    thread.id,
                    len(recipient_ids),
                )
                stats = deliver_message_emails(last_msg.id)
                _flash_send_result(stats)
            else:
                logger.info(
                    'Compose saved without email send_email=%s message_id=%s',
                    form.send_email.data,
                    last_msg.id if last_msg else None,
                )
                flash('Message sent.', 'success')

            return redirect(url_for('messages.thread', thread_id=thread.id))
        except PermissionError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
        except Exception as exc:
            db.session.rollback()
            flash(f'Could not send message: {exc}', 'danger')

    return render_template(
        'messages/compose.html',
        form=form,
        can_broadcast=can_broadcast,
    )


@messages_bp.route('/<int:thread_id>/poll')
@login_required
@limiter.exempt
def poll_messages(thread_id):
    cid = require_company_id()
    msg_thread = get_thread_for_user(thread_id, cid, current_user.id)
    if not msg_thread:
        abort(404)

    after_id = request.args.get('after', 0, type=int)
    mark_thread_read(msg_thread, current_user.id)

    new_messages = get_messages_after(thread_id, after_id)
    receipts = get_read_receipt_updates(
        thread_id,
        current_user.id,
        msg_thread.thread_type,
    )
    db.session.commit()

    messages_payload = []
    if new_messages:
        ctx = _thread_display_context(msg_thread, get_thread_messages(thread_id))
        messages_payload = [
            {'id': m.id, 'html': _render_message_rows([m], ctx)}
            for m in new_messages
        ]

    return jsonify({
        'ok': True,
        'messages': messages_payload,
        'receipts': receipts,
        'unread_threads': unread_message_count(cid, current_user.id),
    })


@messages_bp.route('/<int:thread_id>', methods=['GET', 'POST'])
@login_required
def thread(thread_id):
    cid = require_company_id()
    msg_thread = get_thread_for_user(thread_id, cid, current_user.id)
    if not msg_thread:
        abort(404)

    reply_form = ReplyMessageForm()
    reply_to_id = request.args.get('reply_to', type=int)
    if reply_to_id and request.method == 'GET':
        reply_form.reply_to_message_id.data = reply_to_id

    if request.method == 'POST' and reply_form.validate_on_submit():
        try:
            parent_id = parse_reply_parent_id(
                reply_form.reply_to_message_id.data or request.form.get('reply_to_message_id')
            )
            message = reply_in_thread(
                msg_thread,
                sender_user_id=current_user.id,
                body=reply_form.body.data,
                send_email=reply_form.send_email.data,
                parent_message_id=parent_id,
            )
            db.session.commit()
            email_warning = False
            if reply_form.send_email.data:
                logger.info('Reply triggering email delivery message_id=%s thread_id=%s', message.id, thread_id)
                stats = deliver_message_emails(message.id)
                email_warning = bool(stats.get('failed'))
                if not _wants_json():
                    _flash_send_result(stats, is_reply=True)
            else:
                logger.info('Reply saved without email message_id=%s', message.id)
                if not _wants_json():
                    flash('Reply sent.', 'success')

            if _wants_json():
                db.session.refresh(message)
                all_messages = get_thread_messages(thread_id)
                ctx = _thread_display_context(msg_thread, all_messages)
                payload = {
                    'ok': True,
                    'message_id': message.id,
                    'html': _render_message_rows([message], ctx),
                }
                if email_warning:
                    payload['email_warning'] = True
                return jsonify(payload)
            return redirect(url_for('messages.thread', thread_id=thread_id))
        except PermissionError as exc:
            db.session.rollback()
            if _wants_json():
                return jsonify({'ok': False, 'error': str(exc)}), 403
            flash(str(exc), 'danger')
        except ValueError as exc:
            db.session.rollback()
            if _wants_json():
                return jsonify({'ok': False, 'error': str(exc)}), 400
            flash(str(exc), 'danger')
        except Exception as exc:
            db.session.rollback()
            if _wants_json():
                return jsonify({'ok': False, 'error': f'Could not send reply: {exc}'}), 500
            flash(f'Could not send reply: {exc}', 'danger')
    elif request.method == 'POST' and _wants_json():
        error = 'Could not send message.'
        if reply_form.body.errors:
            error = reply_form.body.errors[0]
        return jsonify({'ok': False, 'error': error}), 400

    return _render_workspace(cid, thread_id, reply_to_id=reply_to_id)
