"""Leave requests and approvals."""
import calendar
from decimal import Decimal

import mimetypes
import os

from flask import Blueprint, abort, jsonify, render_template, redirect, url_for, flash, request, send_file, current_app
from flask_login import login_required, current_user
from sqlalchemy import extract, func

from app.extensions import db
from app.models.employee import Employee
from app.models.leave import LeaveBalance, LeaveRequest, LeaveType, PublicHoliday
from app.services.leave_stats_service import (
    leave_type_display_name,
    leave_types_visible_for_gender,
    normalize_gender,
    statistics_for_employee,
)
from app.forms.leave_forms import (
    AdminLeaveRequestForm,
    LeaveRequestForm,
    LeaveApprovalForm,
    LeaveTypeForm,
    LeaveYearRolloverForm,
    PublicHolidayForm,
)
from app.services.leave_balance_service import (
    compute_balance_snapshot,
    get_available_days,
    leave_type_uses_balance_ledger,
    preview_leave_balance_for_apply,
    recalculate_balance,
    refresh_leave_balance_after_request_change,
    rollover_opening_for_next_year,
    ensure_balance,
)
from app.services.public_holiday_service import public_holiday_dates_in_range
from app.services.leave_document_service import (
    delete_leave_request_document,
    leave_max_attachment_mb,
    resolve_leave_document_full_path,
    save_leave_request_document,
)
from app.services.leave_bulk_entry_service import (
    bulk_entry_context,
    record_bulk_historical_leave,
)
from app.services.leave_approval_service import (
    EDITABLE_STATUSES,
    LEAVE_STATUS_APPROVED,
    LEAVE_STATUS_PENDING_HR,
    LEAVE_STATUS_REJECTED,
    RESUBMITTABLE_STATUSES,
    approval_stage_for_user,
    initial_leave_status_for_employee,
    leave_request_is_resubmittable,
    leave_status_label,
    reset_leave_request_for_resubmission,
    user_is_line_manager,
)
from app.services.employee_relations_service import employee_has_supervisor
from app.decorators.permissions import permission_required
from app.utils.tenant import require_company_id
from app.utils.date_helpers import (
    approved_leave_remaining_days,
    end_date_for_inclusive_leave_days,
    leave_days_between,
)
from datetime import date, datetime, timedelta
from collections import defaultdict
from sqlalchemy.orm import joinedload

leave_bp = Blueprint('leave', __name__)


def _leave_request_is_editable(lr: LeaveRequest) -> bool:
    """Pending (before supervisor acts) or rejected (resubmit) requests."""
    status = (lr.status or '').strip().lower()
    return status in EDITABLE_STATUSES or status in RESUBMITTABLE_STATUSES


def _leave_attachment_template_ctx(lr: LeaveRequest | None = None) -> dict:
    return {
        'existing_document': bool(lr and lr.document_path),
        'existing_document_request_id': lr.id if lr else None,
        'leave_max_attachment_mb': leave_max_attachment_mb(),
    }


def _process_leave_supporting_upload(lr: LeaveRequest, employee_id: int) -> tuple[bool, str | None, bool]:
    """
    Optional supporting document for any leave type.
    Returns (success, error_message, file_was_attached).
    """
    f = request.files.get('supporting_document')
    if not f or not (getattr(f, 'filename', None) or '').strip():
        return True, None, False
    try:
        if lr.document_path:
            delete_leave_request_document(lr.document_path)
        lr.document_path = save_leave_request_document(f, employee_id, lr.id)
        return True, None, True
    except ValueError as exc:
        return False, str(exc), False


def _leave_requests_visible_query(cid: int):
    """Base query for leave list scoped to company."""
    return (
        db.session.query(LeaveRequest)
        .join(Employee, LeaveRequest.employee_id == Employee.id)
        .filter(Employee.company_id == cid)
        .options(
            joinedload(LeaveRequest.leave_type),
            joinedload(LeaveRequest.employee).joinedload(Employee.manager),
            joinedload(LeaveRequest.handover_to),
            joinedload(LeaveRequest.supervisor_reviewed_by),
            joinedload(LeaveRequest.reviewed_by),
        )
    )


def _can_view_leave_request(lr: LeaveRequest, cid: int) -> bool:
    """Same visibility rules as the leave list."""
    emp = lr.employee
    if not emp or emp.company_id != cid:
        return False
    if current_user.has_permission('approve_leave'):
        return True
    if not current_user.employee_id:
        return False
    if lr.employee_id == current_user.employee_id:
        return True
    if user_is_line_manager(current_user, cid) and employee_has_supervisor(emp, current_user.employee_id):
        return True
    return False


def _leave_country_for_employee(emp: Employee | None) -> str:
    if not emp or not emp.branch:
        return 'KE'
    return (emp.branch.country_code or 'KE').upper()[:2]


def _days_requested_for_leave(
    lt: LeaveType, start: date, end: date, *, company_id: int, country_code: str
) -> Decimal:
    basis = (lt.days_count_basis or 'working').lower()
    if basis not in ('working', 'calendar'):
        basis = 'working'
    # Public holidays are never counted as leave days.
    excl = public_holiday_dates_in_range(start, end, company_id, country_code)
    return Decimal(str(leave_days_between(start, end, basis, exclude_dates=excl)))


def _validate_days_within_leave_limits(employee_id: int, lt: LeaveType, year: int, days_requested: Decimal) -> str | None:
    """
    Validate request against leave type configured limits.
    Allows negative accrued/available balances but enforces leave type caps.
    """
    if lt.min_days_request is not None and days_requested < Decimal(str(lt.min_days_request)):
        return f'Minimum request for {lt.name} is {lt.min_days_request} day(s).'

    if lt.max_consecutive_days is not None and days_requested > Decimal(str(lt.max_consecutive_days)):
        return f'Maximum consecutive days for {lt.name} is {lt.max_consecutive_days} day(s).'

    if lt.days_per_year is not None:
        entitlement = Decimal(str(lt.days_per_year))
        if days_requested > entitlement:
            return (
                f'Requested days exceed allowed days for {lt.name}. '
                f'Max per request/year is {entitlement} day(s).'
            )
        used_approved = (
            db.session.query(func.coalesce(func.sum(LeaveRequest.days_requested), 0))
            .filter(
                LeaveRequest.employee_id == employee_id,
                LeaveRequest.leave_type_id == lt.id,
                LeaveRequest.status == 'approved',
                extract('year', LeaveRequest.start_date) == year,
            )
            .scalar()
        )
        total_after_request = Decimal(str(used_approved or 0)) + days_requested
        if total_after_request > entitlement:
            return (
                f'Request exceeds allowed days for {year}. '
                f'Allowed: {entitlement} day(s), already approved: {Decimal(str(used_approved or 0))}, '
                f'requested: {days_requested}.'
            )
    return None


def _active_leave_type_choices_for_employee(employee_id: int | None) -> list[tuple[int, str]]:
    q = db.session.query(LeaveType).filter(LeaveType.is_active.is_(True))
    if not employee_id:
        q = q.filter(LeaveType.company_id == require_company_id())
        types_list = q.order_by(LeaveType.name).all()
        return [(lt.id, lt.name) for lt in types_list]
    emp = db.session.get(Employee, employee_id)
    if not emp:
        q = q.filter(LeaveType.company_id == require_company_id())
        types_list = q.order_by(LeaveType.name).all()
        return [(lt.id, lt.name) for lt in types_list]
    types_list = q.filter(LeaveType.company_id == emp.company_id).order_by(LeaveType.name).all()
    visible = leave_types_visible_for_gender(types_list, normalize_gender(emp.gender))
    return [(lt.id, leave_type_display_name(lt)) for lt in visible]


def _leave_type_allowed_for_employee(lt: LeaveType | None, emp: Employee | None) -> bool:
    if not lt or not emp or not lt.is_active or lt.company_id != emp.company_id:
        return False
    return bool(leave_types_visible_for_gender([lt], normalize_gender(emp.gender)))


def _handover_employee_choices(exclude_employee_id: int | None) -> list[tuple[int, str]]:
    """Active employees other than the person going on leave (same company only)."""
    q = (
        db.session.query(Employee)
        .filter(Employee.status == 'active')
        .order_by(Employee.last_name, Employee.first_name)
    )
    if exclude_employee_id:
        q = q.filter(Employee.id != exclude_employee_id)
        ex = db.session.get(Employee, exclude_employee_id)
        if ex:
            q = q.filter(Employee.company_id == ex.company_id)
    else:
        q = q.filter(Employee.company_id == require_company_id())
    return [(e.id, f'{e.employee_number} — {e.full_name}') for e in q.all()]


def _apply_handover_field(form, exclude_employee_id: int | None) -> bool:
    """
    Populate handover select.
    Handover is currently optional even when colleagues exist.
    """
    peers = _handover_employee_choices(exclude_employee_id)
    if peers:
        form.handover_to_id.choices = [('', '— Select colleague —')] + peers
        return False
    form.handover_to_id.choices = [
        ('', 'No other active employee (optional — contact HR if a cover is required)'),
    ]
    return False


def _apply_leave_type_form(form: LeaveTypeForm, lt: LeaveType) -> None:
    lt.code = form.code.data.strip().upper()
    lt.name = form.name.data.strip()
    lt.days_per_year = form.days_per_year.data if form.days_per_year.data is not None else None
    lt.accrues_monthly = bool(form.accrues_monthly.data)
    lt.days_per_month = form.days_per_month.data if form.days_per_month.data is not None else None
    lt.requires_approval = bool(form.requires_approval.data)
    lt.requires_document = bool(form.requires_document.data)
    lt.is_paid = bool(form.is_paid.data)
    lt.min_days_request = form.min_days_request.data if form.min_days_request.data is not None else Decimal('0.5')
    lt.max_consecutive_days = form.max_consecutive_days.data
    if current_app.config.get('LEAVE_ALLOW_CARRY_FORWARD', False):
        lt.carry_forward_max = form.carry_forward_max.data if form.carry_forward_max.data is not None else 0
    else:
        lt.carry_forward_max = 0
    lt.is_active = bool(form.is_active.data)
    basis = (form.days_count_basis.data or 'working').strip().lower()
    lt.days_count_basis = basis if basis in ('working', 'calendar') else 'working'


@leave_bp.route('/')
@login_required
def index():
    """Leave list - my requests or all (for HR/manager)."""
    cid = require_company_id()
    q = _leave_requests_visible_query(cid)
    if current_user.has_permission('approve_leave'):
        requests = q.order_by(LeaveRequest.created_at.desc()).all()
    elif current_user.employee_id and user_is_line_manager(current_user, cid):
        from app.services.employee_relations_service import subordinate_employee_ids

        team_ids = subordinate_employee_ids(current_user.employee_id, cid)
        team_ids.add(current_user.employee_id)
        requests = (
            q.filter(LeaveRequest.employee_id.in_(team_ids))
            .order_by(LeaveRequest.created_at.desc())
            .all()
        )
    else:
        emp_id = current_user.employee_id
        if not emp_id:
            requests = []
        else:
            requests = q.filter(LeaveRequest.employee_id == emp_id).order_by(LeaveRequest.created_at.desc()).all()
    today = date.today()
    remaining_days = {}
    for r in requests:
        if r.status != 'approved' or not r.leave_type or not r.start_date or not r.end_date:
            remaining_days[r.id] = None
            continue
        basis = (r.leave_type.days_count_basis or 'working').lower()
        if basis not in ('working', 'calendar'):
            basis = 'working'
        emp_row = r.employee
        co = emp_row.company_id if emp_row else cid
        cc = _leave_country_for_employee(emp_row)
        excl = public_holiday_dates_in_range(r.start_date, r.end_date, co, cc)
        remaining_days[r.id] = approved_leave_remaining_days(
            r.start_date, r.end_date, basis, today=today, exclude_dates=excl
        )
    leave_statistics = None
    stats_year = today.year
    if current_user.employee_id:
        leave_statistics = statistics_for_employee(current_user.employee_id, stats_year)
    return render_template(
        'leave/requests.html',
        requests=requests,
        remaining_days=remaining_days,
        leave_statistics=leave_statistics,
        stats_year=stats_year,
    )


@leave_bp.route('/request', methods=['GET', 'POST'])
@login_required
def request_leave():
    form = LeaveRequestForm()
    emp_id = current_user.employee_id
    emp_me = db.session.get(Employee, emp_id) if emp_id else None
    form.leave_type_id.choices = _active_leave_type_choices_for_employee(emp_id)
    attachment_ctx = _leave_attachment_template_ctx()
    handover_required = _apply_handover_field(form, emp_id)
    if form.validate_on_submit():
        if not emp_id:
            flash('No employee linked to your account. Contact HR.', 'warning')
            return render_template(
                'leave/my_requests.html',
                form=form,
                balance_preview_requires_employee_id=False,
                handover_required=handover_required,
                **attachment_ctx,
            )
        if handover_required and form.handover_to_id.data is None:
            flash('Choose a colleague to hand your duties over to for this leave.', 'danger')
            return render_template(
                'leave/my_requests.html',
                form=form,
                balance_preview_requires_employee_id=False,
                handover_required=handover_required,
                **attachment_ctx,
            )
        ho_id = form.handover_to_id.data
        emp_self = db.session.get(Employee, emp_id)
        if ho_id is not None:
            ho = db.session.get(Employee, ho_id)
            if (
                not ho
                or ho.status != 'active'
                or ho.id == emp_id
                or not emp_self
                or ho.company_id != emp_self.company_id
            ):
                flash('Invalid colleague selected for handover.', 'danger')
                return render_template(
                    'leave/my_requests.html',
                    form=form,
                    balance_preview_requires_employee_id=False,
                    handover_required=handover_required,
                    **attachment_ctx,
                )
        lt = db.session.get(LeaveType, form.leave_type_id.data)
        if not _leave_type_allowed_for_employee(lt, emp_self):
            flash('Invalid leave type for your profile.', 'danger')
            return render_template(
                'leave/my_requests.html',
                form=form,
                balance_preview_requires_employee_id=False,
                handover_required=handover_required,
                **attachment_ctx,
            )
        days_requested = _days_requested_for_leave(
            lt,
            form.start_date.data,
            form.end_date.data,
            company_id=emp_self.company_id,
            country_code=_leave_country_for_employee(emp_self),
        )
        req_year = form.start_date.data.year
        limit_error = _validate_days_within_leave_limits(emp_id, lt, req_year, days_requested)
        if limit_error:
            flash(limit_error, 'danger')
            return render_template(
                'leave/my_requests.html',
                form=form,
                balance_preview_requires_employee_id=False,
                handover_required=handover_required,
                **attachment_ctx,
            )
        lr = LeaveRequest(
            employee_id=emp_id,
            leave_type_id=form.leave_type_id.data,
            handover_to_id=ho_id,
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            days_requested=days_requested,
            reason=form.reason.data,
            status=initial_leave_status_for_employee(emp_self),
        )
        db.session.add(lr)
        db.session.flush()
        ok, upload_err, attached = _process_leave_supporting_upload(lr, emp_id)
        if not ok:
            db.session.rollback()
            flash(upload_err, 'danger')
            return render_template(
                'leave/my_requests.html',
                form=form,
                balance_preview_requires_employee_id=False,
                handover_required=handover_required,
                **attachment_ctx,
            )
        db.session.commit()
        try:
            notify_leave_submitted(lr.id)
        except Exception:
            current_app.logger.exception('Leave submission email failed for request %s', lr.id)
        if not attached:
            flash(
                'Leave request submitted. Attaching a supporting document is strongly recommended '
                'to help approvers process your request.',
                'warning',
            )
        else:
            flash('Leave request submitted.', 'success')
        return redirect(url_for('leave.index'))
    return render_template(
        'leave/my_requests.html',
        form=form,
        balance_preview_requires_employee_id=False,
        handover_required=handover_required,
        **attachment_ctx,
    )


@leave_bp.route('/admin/request', methods=['GET', 'POST'])
@login_required
@permission_required('manage_leave_types')
def admin_request_leave():
    """HR: submit leave on behalf of an employee (optionally approved immediately)."""
    pre_emp = request.args.get('employee_id', type=int)
    form = AdminLeaveRequestForm()
    cid = require_company_id()
    employees = (
        db.session.query(Employee)
        .filter(Employee.company_id == cid, Employee.status == 'active')
        .order_by(Employee.last_name, Employee.first_name)
        .all()
    )
    form.employee_id.choices = [(e.id, f'{e.employee_number} — {e.full_name}') for e in employees]
    if not form.employee_id.choices:
        flash('No active employees to assign leave.', 'warning')
        return redirect(url_for('leave.index'))

    if request.method == 'GET' and pre_emp:
        form.employee_id.data = pre_emp

    selected_emp = form.employee_id.data or pre_emp
    form.leave_type_id.choices = _active_leave_type_choices_for_employee(selected_emp)
    attachment_ctx_admin = _leave_attachment_template_ctx()
    if selected_emp:
        handover_required_admin = _apply_handover_field(form, selected_emp)
    else:
        form.handover_to_id.choices = [('', '— Select employee on leave first —')]
        handover_required_admin = False

    if form.validate_on_submit():
        emp_id = form.employee_id.data
        emp = db.session.get(Employee, emp_id)
        if not emp or emp.status != 'active' or emp.company_id != require_company_id():
            flash('Invalid or inactive employee.', 'danger')
            return redirect(url_for('leave.admin_request_leave', employee_id=emp_id))
        handover_required_admin = _apply_handover_field(form, emp_id)
        if handover_required_admin and form.handover_to_id.data is None:
            flash('Choose a colleague to hand duties over to during this leave.', 'danger')
            return render_template(
                'leave/admin_request.html',
                form=form,
                balance_preview_requires_employee_id=True,
                handover_required=handover_required_admin,
                **attachment_ctx_admin,
            )
        ho_id = form.handover_to_id.data
        if ho_id is not None:
            ho = db.session.get(Employee, ho_id)
            if (
                not ho
                or ho.status != 'active'
                or ho.id == emp_id
                or ho.company_id != emp.company_id
            ):
                flash('Invalid colleague selected for handover.', 'danger')
                return render_template(
                    'leave/admin_request.html',
                    form=form,
                    balance_preview_requires_employee_id=True,
                    handover_required=handover_required_admin,
                    **attachment_ctx_admin,
                )
        lt = db.session.get(LeaveType, form.leave_type_id.data)
        if not _leave_type_allowed_for_employee(lt, emp):
            flash('Invalid leave type for this employee’s profile.', 'danger')
            return render_template(
                'leave/admin_request.html',
                form=form,
                balance_preview_requires_employee_id=True,
                handover_required=handover_required_admin,
                **attachment_ctx_admin,
            )
        days_requested = _days_requested_for_leave(
            lt,
            form.start_date.data,
            form.end_date.data,
            company_id=emp.company_id,
            country_code=_leave_country_for_employee(emp),
        )
        req_year = form.start_date.data.year
        limit_error = _validate_days_within_leave_limits(emp_id, lt, req_year, days_requested)
        if limit_error:
            flash(limit_error, 'danger')
            return render_template(
                'leave/admin_request.html',
                form=form,
                balance_preview_requires_employee_id=True,
                handover_required=handover_required_admin,
                **attachment_ctx_admin,
            )
        auto = bool(form.auto_approve.data)
        notes_parts = ['Recorded on behalf of employee by admin.']
        if form.admin_notes.data and str(form.admin_notes.data).strip():
            notes_parts.append(str(form.admin_notes.data).strip())
        review_notes = ' '.join(notes_parts) if auto else None
        lr = LeaveRequest(
            employee_id=emp_id,
            leave_type_id=form.leave_type_id.data,
            handover_to_id=ho_id,
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            days_requested=days_requested,
            reason=form.reason.data,
            status='approved' if auto else initial_leave_status_for_employee(emp),
            reviewed_by_id=current_user.id if auto else None,
            reviewed_at=datetime.utcnow() if auto else None,
            review_notes=review_notes,
        )
        db.session.add(lr)
        db.session.flush()
        ok, upload_err, attached = _process_leave_supporting_upload(lr, emp_id)
        if not ok:
            db.session.rollback()
            flash(upload_err, 'danger')
            return render_template(
                'leave/admin_request.html',
                form=form,
                balance_preview_requires_employee_id=True,
                handover_required=handover_required_admin,
                **attachment_ctx_admin,
            )
        if auto:
            y0, y1 = lr.start_date.year, lr.end_date.year
            for y in range(y0, y1 + 1):
                refresh_leave_balance_after_request_change(lr.employee_id, lr.leave_type_id, y)
        db.session.commit()
        try:
            if auto:
                notify_leave_responded(lr.id, actor_stage='hr', action='approve')
            else:
                notify_leave_submitted(lr.id)
        except Exception:
            current_app.logger.exception('Leave admin submission email failed for request %s', lr.id)
        msg = 'Leave recorded.' + (' Approved.' if auto else ' Submitted as pending.')
        if not attached:
            flash(
                msg + ' No supporting document was attached; consider asking the employee for proof.',
                'warning',
            )
        else:
            flash(msg, 'success')
        return redirect(url_for('leave.index'))

    return render_template(
        'leave/admin_request.html',
        form=form,
        balance_preview_requires_employee_id=True,
        handover_required=handover_required_admin,
        **attachment_ctx_admin,
    )


@leave_bp.route('/<int:id>')
@login_required
def view_request(id):
    """Read-only detail for any leave request the user is allowed to see."""
    cid = require_company_id()
    lr = _leave_requests_visible_query(cid).filter(LeaveRequest.id == id).first()
    if not lr:
        abort(404)
    if not _can_view_leave_request(lr, cid):
        abort(403)

    remaining = None
    if lr.status == LEAVE_STATUS_APPROVED and lr.leave_type and lr.start_date and lr.end_date:
        basis = (lr.leave_type.days_count_basis or 'working').lower()
        if basis not in ('working', 'calendar'):
            basis = 'working'
        emp_row = lr.employee
        co = emp_row.company_id if emp_row else cid
        cc = _leave_country_for_employee(emp_row)
        excl = public_holiday_dates_in_range(lr.start_date, lr.end_date, co, cc)
        remaining = approved_leave_remaining_days(
            lr.start_date, lr.end_date, basis, today=date.today(), exclude_dates=excl
        )

    sup = supervisor_step_summary(lr)
    stage = approval_stage_for_user(current_user, lr)
    if stage == 'hr' and sup.get('state') == 'awaiting':
        sup = {**sup, 'hr_can_bypass': True}

    is_owner = (current_user.employee_id or 0) == lr.employee_id
    can_manage = current_user.has_permission('approve_leave') or is_owner

    return render_template(
        'leave/view_request.html',
        request=lr,
        supervisor_summary=sup,
        approval_stage=stage,
        remaining_days=remaining,
        can_edit=lr.status == 'pending' and can_manage,
        can_resubmit=leave_request_is_resubmittable(lr) and can_manage,
        can_review=bool(stage),
    )


@leave_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_request(id):
    """Edit a leave request."""
    lr = db.session.get(LeaveRequest, id)
    if not lr:
        abort(404)
    emp = db.session.get(Employee, lr.employee_id)
    if not emp or emp.company_id != require_company_id():
        abort(404)
    can_manage_all = current_user.has_permission('approve_leave')
    if not can_manage_all and (current_user.employee_id or 0) != lr.employee_id:
        abort(403)
    if not _leave_request_is_editable(lr):
        flash('This leave request can no longer be changed. Contact HR.', 'warning')
        return redirect(url_for('leave.index'))

    is_resubmit = leave_request_is_resubmittable(lr)
    form = LeaveRequestForm(obj=lr)
    form.leave_type_id.choices = _active_leave_type_choices_for_employee(lr.employee_id)
    handover_required = _apply_handover_field(form, lr.employee_id)
    edit_ctx = {
        'handover_required': handover_required,
        'balance_preview_requires_employee_id': False,
        'form_action': url_for('leave.edit_request', id=lr.id),
        'form_submit_label': 'Resubmit' if is_resubmit else 'Save Changes',
        'form_title': 'Resubmit Leave Request' if is_resubmit else 'Edit Leave Request',
        'edit_employee': emp,
        'is_resubmit': is_resubmit,
        **_leave_attachment_template_ctx(lr),
    }

    if request.method == 'GET':
        form.leave_type_id.data = lr.leave_type_id
        form.start_date.data = lr.start_date
        form.end_date.data = lr.end_date
        form.handover_to_id.data = lr.handover_to_id
        form.reason.data = lr.reason

    if form.validate_on_submit():
        if handover_required and form.handover_to_id.data is None:
            flash('Choose a colleague to hand your duties over to for this leave.', 'danger')
            return render_template(
                'leave/my_requests.html',
                form=form,
                **edit_ctx,
            )
        ho_id = form.handover_to_id.data
        if ho_id is not None:
            ho = db.session.get(Employee, ho_id)
            if (
                not ho
                or ho.status != 'active'
                or ho.id == lr.employee_id
                or ho.company_id != emp.company_id
            ):
                flash('Invalid colleague selected for handover.', 'danger')
                return render_template(
                    'leave/my_requests.html',
                    form=form,
                    **edit_ctx,
                )

        lt = db.session.get(LeaveType, form.leave_type_id.data)
        if not _leave_type_allowed_for_employee(lt, emp):
            flash('Invalid leave type for this employee’s profile.', 'danger')
            return render_template(
                'leave/my_requests.html',
                form=form,
                **edit_ctx,
            )

        days_requested = _days_requested_for_leave(
            lt,
            form.start_date.data,
            form.end_date.data,
            company_id=emp.company_id,
            country_code=_leave_country_for_employee(emp),
        )
        req_year = form.start_date.data.year
        limit_error = _validate_days_within_leave_limits(lr.employee_id, lt, req_year, days_requested)
        if limit_error:
            flash(limit_error, 'danger')
            return render_template(
                'leave/my_requests.html',
                form=form,
                **edit_ctx,
            )

        lr.leave_type_id = form.leave_type_id.data
        lr.handover_to_id = ho_id
        lr.start_date = form.start_date.data
        lr.end_date = form.end_date.data
        lr.days_requested = days_requested
        lr.reason = form.reason.data
        ok, upload_err, attached = _process_leave_supporting_upload(lr, lr.employee_id)
        if not ok:
            db.session.rollback()
            flash(upload_err, 'danger')
            return render_template(
                'leave/my_requests.html',
                form=form,
                **edit_ctx,
            )
        if is_resubmit:
            reset_leave_request_for_resubmission(lr, emp)
        db.session.commit()
        if is_resubmit:
            try:
                notify_leave_submitted(lr.id)
            except Exception:
                current_app.logger.exception('Leave resubmission email failed for request %s', lr.id)
            if not lr.document_path:
                flash(
                    'Leave request resubmitted. Attaching a supporting document is strongly recommended.',
                    'warning',
                )
            else:
                flash('Leave request resubmitted for approval.', 'success')
        elif not lr.document_path:
            flash(
                'Leave request updated. Attaching a supporting document is strongly recommended.',
                'warning',
            )
        else:
            flash('Leave request updated.', 'success')
        return redirect(url_for('leave.index'))

    return render_template(
        'leave/my_requests.html',
        form=form,
        **edit_ctx,
    )


@leave_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
def delete_request(id):
    """Delete a leave request."""
    lr = db.session.get(LeaveRequest, id)
    if not lr:
        abort(404)
    emp = db.session.get(Employee, lr.employee_id)
    if not emp or emp.company_id != require_company_id():
        abort(404)
    can_manage_all = current_user.has_permission('approve_leave')
    if not can_manage_all and (current_user.employee_id or 0) != lr.employee_id:
        abort(403)
    if not _leave_request_is_editable(lr):
        flash('This leave request can no longer be deleted.', 'warning')
        return redirect(url_for('leave.index'))
    delete_leave_request_document(lr.document_path)
    db.session.delete(lr)
    db.session.commit()
    flash('Leave request deleted.', 'success')
    return redirect(url_for('leave.index'))


@leave_bp.route('/<int:id>/document')
@login_required
def leave_request_document(id):
    """Download or view supporting document for a leave request."""
    lr = db.session.get(LeaveRequest, id)
    if not lr:
        abort(404)
    emp = db.session.get(Employee, lr.employee_id)
    if not emp or emp.company_id != require_company_id():
        abort(404)
    can_view = current_user.has_permission('approve_leave') or (current_user.employee_id or 0) == lr.employee_id
    if not can_view:
        abort(403)
    if not lr.document_path:
        abort(404)
    full_path = resolve_leave_document_full_path(lr.document_path)
    if not full_path:
        flash('Supporting document file is missing from storage.', 'danger')
        return redirect(url_for('leave.index'))
    download = request.args.get('download') in {'1', 'true', 'yes'}
    mime, _ = mimetypes.guess_type(full_path)
    return send_file(
        full_path,
        mimetype=mime or 'application/octet-stream',
        as_attachment=download,
        download_name=os.path.basename(full_path),
    )


@leave_bp.route('/api/suggest-end-date')
@login_required
def suggest_end_date():
    """
    Given leave type + start date, return suggested end date for the full entitlement
    (days_per_year) using that type's day-count basis — helps maternity / paternity planning.
    """
    leave_type_id = request.args.get('leave_type_id', type=int)
    start_raw = request.args.get('start_date')
    if not leave_type_id or not start_raw:
        return jsonify({'error': 'leave_type_id and start_date are required'}), 400
    lt = db.session.get(LeaveType, leave_type_id)
    if not lt or not lt.is_active:
        return jsonify({'error': 'Invalid leave type'}), 404
    emp_id = request.args.get('employee_id', type=int) or current_user.employee_id
    emp = db.session.get(Employee, emp_id) if emp_id else None
    if not emp or emp.company_id != require_company_id() or lt.company_id != emp.company_id:
        return jsonify({'error': 'Invalid employee or leave type for this company'}), 400
    try:
        start = date.fromisoformat(start_raw)
    except ValueError:
        return jsonify({'error': 'Invalid start_date (use YYYY-MM-DD)'}), 400
    entitlement = lt.days_per_year
    if entitlement is None or Decimal(str(entitlement)) <= 0:
        return jsonify({'suggest': False, 'message': 'This leave type has no fixed days-per-year entitlement.'})
    # Whole days for period end (90, 14, 21 — not fractional half-days)
    total = int(Decimal(str(entitlement)).quantize(Decimal('1')))
    basis = (lt.days_count_basis or 'working').lower()
    if basis not in ('working', 'calendar'):
        basis = 'working'
    exclude_h = public_holiday_dates_in_range(
        start,
        start + timedelta(days=400),
        emp.company_id,
        _leave_country_for_employee(emp),
    )
    end = end_date_for_inclusive_leave_days(start, total, basis, exclude_dates=exclude_h)
    basis_label = (
        'calendar days (including weekends; excluding public holidays you configure)'
        if basis == 'calendar'
        else 'working days (Mon–Fri; excludes weekends and public holidays you configure)'
    )
    return jsonify(
        {
            'suggest': True,
            'leave_type_code': lt.code,
            'leave_type_name': lt.name,
            'total_days': total,
            'basis': basis,
            'basis_label': basis_label,
            'start_date': start.isoformat(),
            'end_date': end.isoformat(),
            'end_date_display': end.strftime('%d %b %Y'),
        }
    )


@leave_bp.route('/api/leave-balance-preview')
@login_required
def leave_balance_preview():
    """Accrued / available (or yearly remaining) for the apply-leave forms."""
    leave_type_id = request.args.get('leave_type_id', type=int)
    if not leave_type_id:
        return jsonify({'error': 'leave_type_id is required'}), 400

    employee_id = request.args.get('employee_id', type=int)
    if employee_id:
        if not current_user.has_permission('manage_leave_types'):
            return jsonify({'error': 'Forbidden'}), 403
    else:
        employee_id = current_user.employee_id
        if not employee_id:
            return jsonify({'error': 'No employee linked to this account'}), 403

    start_raw = request.args.get('start_date')
    year = request.args.get('year', type=int)
    if start_raw:
        try:
            year = date.fromisoformat(start_raw).year
        except ValueError:
            return jsonify({'error': 'Invalid start_date'}), 400
    if year is None:
        year = date.today().year

    emp_chk = db.session.get(Employee, employee_id)
    if not emp_chk or emp_chk.company_id != require_company_id():
        return jsonify({'error': 'Invalid employee'}), 403

    data = preview_leave_balance_for_apply(employee_id, leave_type_id, year)
    if data.get('error'):
        code = 404 if data['error'] in ('invalid_leave_type', 'invalid_employee') else 400
        return jsonify(data), code
    return jsonify(data)


@leave_bp.route('/tracker')
@login_required
@permission_required('manage_leave_types')
def tracker():
    """Annual leave tracker: employee summary + day-by-day calendar grid."""
    cid = require_company_id()
    today = date.today()
    year = request.args.get('year', type=int) or today.year
    q = (request.args.get('q') or '').strip()
    y0 = date(year, 1, 1)
    y1 = date(year, 12, 31)

    emp_q = db.session.query(Employee).filter(Employee.company_id == cid)
    if q:
        like = f'%{q}%'
        emp_q = emp_q.filter(
            db.or_(
                Employee.first_name.ilike(like),
                Employee.last_name.ilike(like),
                Employee.employee_number.ilike(like),
            )
        )
    employees = emp_q.order_by(Employee.last_name, Employee.first_name).all()
    leave_types = (
        db.session.query(LeaveType)
        .filter(LeaveType.company_id == cid, LeaveType.is_active.is_(True))
        .order_by(LeaveType.name)
        .all()
    )
    emp_by_id = {e.id: e for e in employees}
    lt_by_id = {lt.id: lt for lt in leave_types}

    months = []
    for month in range(1, 13):
        first = date(year, month, 1)
        last = date(year, month, calendar.monthrange(year, month)[1])
        grid_start = first - timedelta(days=first.weekday())  # Monday-start weeks
        grid_end = last + timedelta(days=(6 - last.weekday()))
        weeks = []
        d = grid_start
        while d <= grid_end:
            week_days = []
            for _ in range(7):
                week_days.append(d if d.month == month else None)
                d += timedelta(days=1)
            weeks.append(week_days)
        months.append(
            {
                'month': month,
                'name': calendar.month_name[month],
                'weeks': weeks,
            }
        )

    emp_ids = [e.id for e in employees]
    requests = []
    if emp_ids:
        requests = (
            db.session.query(LeaveRequest)
            .filter(
                LeaveRequest.employee_id.in_(emp_ids),
                LeaveRequest.status == 'approved',
                LeaveRequest.start_date <= y1,
                LeaveRequest.end_date >= y0,
            )
            .order_by(LeaveRequest.employee_id, LeaveRequest.start_date, LeaveRequest.id)
            .all()
        )

    employee_day_marks: dict[int, dict[date, list[str]]] = defaultdict(lambda: defaultdict(list))
    for r in requests:
        lt = lt_by_id.get(r.leave_type_id)
        if not lt:
            continue
        emp = emp_by_id.get(r.employee_id)
        if not emp:
            continue
        basis = (lt.days_count_basis or 'working').lower()
        if basis not in ('working', 'calendar'):
            basis = 'working'
        req_start = max(r.start_date, y0)
        req_end = min(r.end_date, y1)
        excl = public_holiday_dates_in_range(
            req_start,
            req_end,
            emp.company_id,
            _leave_country_for_employee(emp),
        )
        dd = req_start
        code = (lt.code or lt.name or 'L')[:3].upper()
        while dd <= req_end:
            is_leave_day = False
            if basis == 'working':
                is_leave_day = dd.weekday() < 5 and dd not in excl
            else:
                is_leave_day = dd not in excl
            if is_leave_day and code not in employee_day_marks[emp.id][dd]:
                employee_day_marks[emp.id][dd].append(code)
            dd += timedelta(days=1)

    rows = []
    for emp in employees:
        stats = statistics_for_employee(emp.id, year)
        stat_map = {row['leave_type_id']: row for row in stats}
        visible_leave_types = leave_types_visible_for_gender(
            leave_types, normalize_gender(emp.gender)
        )
        used_by_type = {}
        remaining_by_type = {}
        carry_forward_total = Decimal('0')
        for lt in visible_leave_types:
            s = stat_map.get(lt.id)
            used = s.get('used') if s else Decimal('0')
            remaining = s.get('remaining') if s else None
            used_by_type[lt.id] = used
            remaining_by_type[lt.id] = remaining
            if s and s.get('mode') == 'ledger':
                carry_forward_total += Decimal(str(s.get('opening_balance') or 0))
        rows.append(
            {
                'employee': emp,
                'visible_leave_types': visible_leave_types,
                'stats_by_type': stat_map,
                'carry_forward_total': carry_forward_total,
                'used_by_type': used_by_type,
                'remaining_by_type': remaining_by_type,
                'day_marks': employee_day_marks.get(emp.id, {}),
            }
        )

    return render_template(
        'leave/tracker.html',
        year=year,
        q=q,
        year_choices=[year - 1, year, year + 1],
        months=months,
        weekday_names=['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
        leave_types=leave_types,
        rows=rows,
    )


@leave_bp.route('/<int:id>/approve', methods=['GET', 'POST'])
@login_required
def approve(id):
    lr = db.session.get(LeaveRequest, id)
    if not lr:
        abort(404)
    emp_lr = db.session.get(Employee, lr.employee_id)
    if not emp_lr or emp_lr.company_id != require_company_id():
        abort(404)
    stage = approval_stage_for_user(current_user, lr)
    if not stage:
        abort(403)
    form = LeaveApprovalForm()
    if form.validate_on_submit():
        action = form.action.data
        now = datetime.utcnow()
        notes = form.review_notes.data
        if action == 'reject':
            lr.status = LEAVE_STATUS_REJECTED
            if stage == 'supervisor':
                lr.supervisor_reviewed_by_id = current_user.id
                lr.supervisor_reviewed_at = now
                lr.supervisor_notes = notes
            else:
                lr.reviewed_by_id = current_user.id
                lr.reviewed_at = now
                lr.review_notes = notes
        elif stage == 'supervisor':
            lr.status = LEAVE_STATUS_PENDING_HR
            lr.supervisor_reviewed_by_id = current_user.id
            lr.supervisor_reviewed_at = now
            lr.supervisor_notes = notes
        else:
            lr.status = LEAVE_STATUS_APPROVED
            lr.reviewed_by_id = current_user.id
            lr.reviewed_at = now
            lr.review_notes = notes
            y0, y1 = lr.start_date.year, lr.end_date.year
            db.session.flush()
            for y in range(y0, y1 + 1):
                refresh_leave_balance_after_request_change(lr.employee_id, lr.leave_type_id, y)
        db.session.commit()
        try:
            notify_leave_responded(lr.id, actor_stage=stage, action=action)
        except Exception:
            current_app.logger.exception('Leave response email failed for request %s', lr.id)
        flash('Leave request updated.', 'success')
        return redirect(url_for('leave.index'))
    stage_labels = {'supervisor': 'Supervisor', 'hr': 'HR'}
    sup = supervisor_step_summary(lr)
    if stage == 'hr' and sup.get('state') == 'awaiting':
        sup['hr_can_bypass'] = True
    return render_template(
        'leave/approve.html',
        request=lr,
        form=form,
        approval_stage=stage,
        stage_label=stage_labels.get(stage, stage),
        supervisor_summary=sup,
    )


@leave_bp.route('/types')
@login_required
@permission_required('manage_leave_types')
def types_index():
    """HR: list leave categories (annual, sick, etc.)."""
    types_list = (
        db.session.query(LeaveType)
        .filter(LeaveType.company_id == require_company_id())
        .order_by(LeaveType.name)
        .all()
    )
    return render_template('leave/types.html', types_list=types_list)


@leave_bp.route('/types/create', methods=['GET', 'POST'])
@login_required
@permission_required('manage_leave_types')
def type_create():
    form = LeaveTypeForm()
    if form.validate_on_submit():
        code = form.code.data.strip().upper()
        cid = require_company_id()
        if db.session.query(LeaveType).filter(LeaveType.company_id == cid, LeaveType.code == code).first():
            flash('A leave type with this code already exists.', 'danger')
            return render_template('leave/type_form.html', form=form, leave_type=None)
        lt = LeaveType(company_id=cid)
        _apply_leave_type_form(form, lt)
        db.session.add(lt)
        db.session.commit()
        flash('Leave type created.', 'success')
        return redirect(url_for('leave.types_index'))
    return render_template('leave/type_form.html', form=form, leave_type=None)


@leave_bp.route('/types/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('manage_leave_types')
def type_edit(id):
    lt = db.session.get(LeaveType, id)
    if not lt or lt.company_id != require_company_id():
        abort(404)
    form = LeaveTypeForm()
    if form.validate_on_submit():
        code = form.code.data.strip().upper()
        existing = (
            db.session.query(LeaveType)
            .filter(
                LeaveType.company_id == lt.company_id,
                LeaveType.code == code,
                LeaveType.id != id,
            )
            .first()
        )
        if existing:
            flash('Another leave type already uses this code.', 'danger')
            return render_template('leave/type_form.html', form=form, leave_type=lt)
        _apply_leave_type_form(form, lt)
        db.session.commit()
        flash('Leave type updated.', 'success')
        return redirect(url_for('leave.types_index'))
    if request.method == 'GET':
        form.code.data = lt.code
        form.name.data = lt.name
        form.days_per_year.data = lt.days_per_year
        form.accrues_monthly.data = lt.accrues_monthly
        form.days_per_month.data = lt.days_per_month
        form.requires_approval.data = lt.requires_approval
        form.requires_document.data = lt.requires_document
        form.is_paid.data = lt.is_paid
        form.min_days_request.data = lt.min_days_request
        form.max_consecutive_days.data = lt.max_consecutive_days
        form.carry_forward_max.data = lt.carry_forward_max
        form.is_active.data = lt.is_active
        form.days_count_basis.data = lt.days_count_basis or 'working'
    return render_template('leave/type_form.html', form=form, leave_type=lt)


@leave_bp.route('/types/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('manage_leave_types')
def type_delete(id):
    lt = db.session.get(LeaveType, id)
    if not lt or lt.company_id != require_company_id():
        flash('Leave type not found.', 'danger')
        return redirect(url_for('leave.types_index'))
    n_requests = (
        db.session.query(func.count(LeaveRequest.id))
        .filter(LeaveRequest.leave_type_id == id)
        .scalar()
    )
    n_balances = (
        db.session.query(func.count(LeaveBalance.id))
        .filter(LeaveBalance.leave_type_id == id)
        .scalar()
    )
    if (n_requests or 0) > 0:
        flash(
            'Cannot delete this leave type: it has leave requests on file. '
            'Deactivate it instead (set Active to No on edit).',
            'warning',
        )
        return redirect(url_for('leave.types_index'))
    if (n_balances or 0) > 0:
        flash(
            'Cannot delete this leave type: employee leave balances exist for it. '
            'Clear or adjust balances first, or deactivate the type.',
            'warning',
        )
        return redirect(url_for('leave.types_index'))
    name = lt.name
    db.session.delete(lt)
    db.session.commit()
    flash(f'Leave type "{name}" was deleted.', 'success')
    return redirect(url_for('leave.types_index'))


@leave_bp.route('/holidays')
@login_required
@permission_required('manage_leave_types')
def holidays_index():
    """HR: recurring (every year) + one-off holidays for a selected year."""
    cid = require_company_id()
    year = request.args.get('year', type=int) or date.today().year
    recurring = (
        db.session.query(PublicHoliday)
        .filter(PublicHoliday.company_id == cid, PublicHoliday.kind == 'recurring')
        .order_by(PublicHoliday.recurring_month, PublicHoliday.recurring_day)
        .all()
    )
    one_offs = (
        db.session.query(PublicHoliday)
        .filter(
            PublicHoliday.company_id == cid,
            PublicHoliday.kind == 'one_off',
            PublicHoliday.date.isnot(None),
            extract('year', PublicHoliday.date) == year,
        )
        .order_by(PublicHoliday.date)
        .all()
    )
    return render_template(
        'leave/holidays.html',
        recurring=recurring,
        one_offs=one_offs,
        year=year,
    )


def _apply_public_holiday_form(
    form: PublicHolidayForm, existing_id: int | None, company_id: int
) -> PublicHoliday | None:
    """Build model from validated form; return None if duplicate."""
    name = form.name.data.strip()
    cc = (form.country_code.data or 'KE').strip().upper()[:2]
    if form.kind.data == 'recurring':
        m, d = form.recurring_month.data, form.recurring_day.data
        q = db.session.query(PublicHoliday).filter(
            PublicHoliday.company_id == company_id,
            PublicHoliday.country_code == cc,
            PublicHoliday.kind == 'recurring',
            PublicHoliday.recurring_month == m,
            PublicHoliday.recurring_day == d,
        )
        if existing_id:
            q = q.filter(PublicHoliday.id != existing_id)
        if q.first():
            flash('A fixed annual holiday already exists on that month and day.', 'danger')
            return None
        return PublicHoliday(
            company_id=company_id,
            country_code=cc,
            kind='recurring',
            name=name,
            recurring_month=m,
            recurring_day=d,
            date=None,
        )
    d = form.holiday_date.data
    q = db.session.query(PublicHoliday).filter(
        PublicHoliday.company_id == company_id,
        PublicHoliday.country_code == cc,
        PublicHoliday.kind == 'one_off',
        PublicHoliday.date == d,
    )
    if existing_id:
        q = q.filter(PublicHoliday.id != existing_id)
    if q.first():
        flash('A one-off public holiday already exists on that date.', 'danger')
        return None
    return PublicHoliday(
        company_id=company_id,
        country_code=cc,
        kind='one_off',
        name=name,
        date=d,
        recurring_month=None,
        recurring_day=None,
    )


@leave_bp.route('/holidays/create', methods=['GET', 'POST'])
@login_required
@permission_required('manage_leave_types')
def holiday_create():
    form = PublicHolidayForm()
    if form.validate_on_submit():
        h = _apply_public_holiday_form(form, existing_id=None, company_id=require_company_id())
        if h is None:
            return render_template('leave/holiday_form.html', form=form, holiday=None)
        db.session.add(h)
        db.session.commit()
        flash('Public holiday added.', 'success')
        red_year = h.date.year if h.kind == 'one_off' and h.date else date.today().year
        return redirect(url_for('leave.holidays_index', year=red_year))
    return render_template('leave/holiday_form.html', form=form, holiday=None)


@leave_bp.route('/holidays/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('manage_leave_types')
def holiday_edit(id):
    h = db.session.get(PublicHoliday, id)
    if not h or h.company_id != require_company_id():
        abort(404)
    form = PublicHolidayForm()
    if form.validate_on_submit():
        new = _apply_public_holiday_form(form, existing_id=h.id, company_id=h.company_id)
        if new is None:
            return render_template('leave/holiday_form.html', form=form, holiday=h)
        h.kind = new.kind
        h.name = new.name
        h.country_code = new.country_code
        h.date = new.date
        h.recurring_month = new.recurring_month
        h.recurring_day = new.recurring_day
        db.session.commit()
        flash('Public holiday updated.', 'success')
        red_year = h.date.year if h.kind == 'one_off' and h.date else date.today().year
        return redirect(url_for('leave.holidays_index', year=red_year))
    if request.method == 'GET':
        form.name.data = h.name
        form.country_code.data = (h.country_code or 'KE').upper()
        if getattr(h, 'kind', None) == 'recurring' or (
            h.recurring_month is not None and h.recurring_day is not None
        ):
            form.kind.data = 'recurring'
            form.recurring_month.data = h.recurring_month
            form.recurring_day.data = h.recurring_day
        else:
            form.kind.data = 'one_off'
            form.holiday_date.data = h.date
    return render_template('leave/holiday_form.html', form=form, holiday=h)


@leave_bp.route('/holidays/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('manage_leave_types')
def holiday_delete(id):
    h = db.session.get(PublicHoliday, id)
    if not h or h.company_id != require_company_id():
        flash('Holiday not found.', 'danger')
        return redirect(url_for('leave.holidays_index'))
    return_year = request.form.get('return_year', type=int) or date.today().year
    if h.kind == 'one_off' and h.date:
        return_year = h.date.year
    name = h.name
    db.session.delete(h)
    db.session.commit()
    flash(f'Removed public holiday: {name}.', 'success')
    return redirect(url_for('leave.holidays_index', year=return_year))


def _ledger_leave_types():
    cid = require_company_id()
    return [
        lt
        for lt in db.session.query(LeaveType)
        .filter(LeaveType.company_id == cid, LeaveType.is_active.is_(True))
        .order_by(LeaveType.name)
        .all()
        if leave_type_uses_balance_ledger(lt)
    ]


@leave_bp.route('/balances', methods=['GET', 'POST'])
@login_required
@permission_required('manage_leave_types')
def balances():
    """HR: manual opening/carry and adjustments per employee; year-end rollover."""
    today = date.today()
    rollover_form = LeaveYearRolloverForm()
    if request.method == 'GET':
        rollover_form.from_year.data = today.year - 1
        rollover_form.to_year.data = today.year

    employee_id = request.args.get('employee_id', type=int) or request.form.get('employee_id', type=int)
    year = request.args.get('year', type=int) or request.form.get('year', type=int) or today.year

    ledger_types = _ledger_leave_types()

    if request.method == 'POST' and request.form.get('save_balances') and employee_id:
        emp = db.session.get(Employee, employee_id)
        if not emp or emp.company_id != require_company_id():
            flash('Employee not found.', 'danger')
            return redirect(url_for('leave.balances'))
        for lt in ledger_types:
            okey = f'opening_{lt.id}'
            akey = f'adjusted_{lt.id}'
            if okey not in request.form and akey not in request.form:
                continue
            try:
                o_val = Decimal(str(request.form.get(okey, '0') or '0').strip() or '0')
                a_val = Decimal(str(request.form.get(akey, '0') or '0').strip() or '0')
            except Exception:
                flash(f'Invalid number for leave type {lt.name}.', 'danger')
                return redirect(url_for('leave.balances', employee_id=employee_id, year=year))
            row = ensure_balance(employee_id, lt.id, year)
            if row:
                row.opening_balance = o_val
                row.adjusted = a_val
                recalculate_balance(row)
        db.session.commit()
        flash('Leave balances saved.', 'success')
        return redirect(url_for('leave.balances', employee_id=employee_id, year=year))

    if request.method == 'POST' and request.form.get('rollover_submit'):
        if not current_app.config.get('LEAVE_ALLOW_CARRY_FORWARD', False):
            flash('Year-end leave carry is disabled for this company.', 'warning')
            return redirect(url_for('leave.balances'))
        rollover_form = LeaveYearRolloverForm(formdata=request.form)
        if rollover_form.validate_on_submit():
            fy, ty = rollover_form.from_year.data, rollover_form.to_year.data
            if ty != fy + 1:
                flash('"To year" must be exactly one year after "From year".', 'danger')
            else:
                try:
                    count, msgs = rollover_opening_for_next_year(
                        fy, ty, company_id=require_company_id(), as_of=today
                    )
                    for m in msgs:
                        flash(m, 'success')
                except ValueError as e:
                    flash(str(e), 'danger')
        return redirect(url_for('leave.balances'))

    cid = require_company_id()
    employees = (
        db.session.query(Employee)
        .filter(Employee.company_id == cid)
        .order_by(Employee.last_name, Employee.first_name)
        .all()
    )
    employee = db.session.get(Employee, employee_id) if employee_id else None
    if employee and employee.company_id != cid:
        employee = None

    balance_rows = []
    if employee and ledger_types:
        for lt in ledger_types:
            snap = compute_balance_snapshot(employee.id, lt.id, year)
            balance_rows.append(
                {
                    'leave_type': lt,
                    'snapshot': snap,
                    'opening_field': snap['opening_balance'] if snap else Decimal('0'),
                    'adjusted_field': snap['adjusted'] if snap else Decimal('0'),
                    'closing': snap['closing_balance'] if snap else Decimal('0'),
                }
            )

    return render_template(
        'leave/balances.html',
        employees=employees,
        employee=employee,
        year=year,
        ledger_types=ledger_types,
        balance_rows=balance_rows,
        rollover_form=rollover_form,
    )


@leave_bp.route('/bulk-entry', methods=['GET', 'POST'])
@login_required
@permission_required('manage_leave_types')
def bulk_entry():
    """HR: pick many leave days on a year calendar for one employee and leave type."""
    today = date.today()
    cid = require_company_id()
    employee_id = request.args.get('employee_id', type=int) or request.form.get('employee_id', type=int)
    leave_type_id = request.args.get('leave_type_id', type=int) or request.form.get('leave_type_id', type=int)
    year = request.args.get('year', type=int) or request.form.get('year', type=int) or today.year

    employees = (
        db.session.query(Employee)
        .filter(Employee.company_id == cid, Employee.status == 'active')
        .order_by(Employee.last_name, Employee.first_name)
        .all()
    )
    leave_types = (
        db.session.query(LeaveType)
        .filter(LeaveType.company_id == cid, LeaveType.is_active.is_(True))
        .order_by(LeaveType.name)
        .all()
    )

    employee = db.session.get(Employee, employee_id) if employee_id else None
    leave_type = db.session.get(LeaveType, leave_type_id) if leave_type_id else None
    if employee and employee.company_id != cid:
        employee = None
    if leave_type and leave_type.company_id != cid:
        leave_type = None

    if request.method == 'POST' and request.form.get('save_bulk_leave'):
        if not employee or not leave_type:
            flash('Select an employee and leave type.', 'danger')
            return redirect(url_for('leave.bulk_entry', year=year))

        raw_dates = (request.form.get('selected_dates') or '').strip()
        selected: list[date] = []
        for part in raw_dates.split(','):
            part = part.strip()
            if not part:
                continue
            try:
                selected.append(date.fromisoformat(part))
            except ValueError:
                continue

        notes = (request.form.get('notes') or '').strip() or None
        result = record_bulk_historical_leave(
            employee_id=employee.id,
            leave_type_id=leave_type.id,
            year=year,
            selected_dates=selected,
            recorded_by_user_id=current_user.id,
            notes=notes,
        )
        if result.errors:
            for err in result.errors:
                flash(err, 'danger')
            return redirect(
                url_for(
                    'leave.bulk_entry',
                    employee_id=employee.id,
                    leave_type_id=leave_type.id,
                    year=year,
                )
            )

        db.session.commit()
        flash(
            f'Recorded {result.created_requests} leave period(s) '
            f'({result.total_days} day(s)) for {employee.full_name} — {leave_type.name}.',
            'success',
        )
        return redirect(
            url_for(
                'leave.bulk_entry',
                employee_id=employee.id,
                leave_type_id=leave_type.id,
                year=year,
            )
        )

    return render_template(
        'leave/bulk_entry.html',
        employees=employees,
        leave_types=leave_types,
        employee=employee,
        leave_type=leave_type,
        year=year,
    )


@leave_bp.route('/api/bulk-entry-context')
@login_required
@permission_required('manage_leave_types')
def bulk_entry_context_api():
    employee_id = request.args.get('employee_id', type=int)
    leave_type_id = request.args.get('leave_type_id', type=int)
    year = request.args.get('year', type=int)
    if not employee_id or not leave_type_id or not year:
        return jsonify(error='employee_id, leave_type_id, and year are required.'), 400
    emp = db.session.get(Employee, employee_id)
    if not emp or emp.company_id != require_company_id():
        return jsonify(error='Employee not found.'), 404
    ctx = bulk_entry_context(employee_id, leave_type_id, year)
    if not ctx:
        return jsonify(error='Invalid leave type.'), 400
    return jsonify(ctx)
