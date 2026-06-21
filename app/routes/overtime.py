"""Overtime compensation requests (days) and approvals."""
from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from app.decorators.permissions import permission_required
from app.extensions import db
from app.forms.overtime_forms import OvertimeForEmployeeForm, OvertimeRequestForm, OvertimeReviewForm
from app.models.employee import Employee
from app.models.overtime import OvertimeRequest
from app.utils.tenant import require_company_id
from app.services.employee_relations_service import (
    employee_has_supervisor,
    subordinate_employee_ids,
)

overtime_bp = Blueprint('overtime', __name__)


def _can_submit_for_other(submitter_emp: Employee | None, target: Employee) -> bool:
    """Manager same department, line manager, or payroll/HR."""
    if not submitter_emp or submitter_emp.company_id != target.company_id:
        return False
    if current_user.has_permission('process_payroll'):
        return True
    if employee_has_supervisor(target, submitter_emp.id):
        return True
    if (
        submitter_emp.department_id
        and target.department_id
        and submitter_emp.department_id == target.department_id
    ):
        return True
    return False


def _can_approve(req: OvertimeRequest) -> bool:
    subject = req.employee
    if not subject:
        return False
    if current_user.has_permission('approve_overtime'):
        return True
    eid = current_user.employee_id
    if eid and employee_has_supervisor(subject, eid):
        return True
    return False


@overtime_bp.route('/')
@login_required
def index():
    cid = require_company_id()
    q = (
        db.session.query(OvertimeRequest)
        .join(Employee, OvertimeRequest.employee_id == Employee.id)
        .filter(OvertimeRequest.company_id == cid)
        .options(
            joinedload(OvertimeRequest.employee),
            joinedload(OvertimeRequest.submitted_by),
            joinedload(OvertimeRequest.reviewed_by),
        )
    )
    if current_user.has_permission('approve_overtime'):
        requests_list = q.order_by(OvertimeRequest.created_at.desc()).all()
    else:
        eid = current_user.employee_id
        if not eid:
            requests_list = []
        else:
            team_ids = subordinate_employee_ids(eid, cid)
            team_ids.add(eid)
            requests_list = (
                q.filter(OvertimeRequest.employee_id.in_(team_ids))
                .order_by(OvertimeRequest.created_at.desc())
                .all()
            )
    return render_template('overtime/index.html', requests=requests_list)


@overtime_bp.route('/request', methods=['GET', 'POST'])
@login_required
@permission_required('request_overtime')
def new_request():
    emp_id = current_user.employee_id
    if not emp_id:
        flash('Your account is not linked to an employee record.', 'warning')
        return redirect(url_for('overtime.index'))
    emp = db.session.get(Employee, emp_id)
    if not emp or emp.company_id != require_company_id():
        abort(403)
    form = OvertimeRequestForm()
    if request.method == 'GET' and not form.for_pay_year.data:
        form.for_pay_year.data = datetime.utcnow().year
        form.for_pay_month.data = datetime.utcnow().month
    if form.validate_on_submit():
        worked = form.parsed_worked_dates()
        latest = max(worked)
        row = OvertimeRequest(
            company_id=emp.company_id,
            employee_id=emp.id,
            days=len(worked),
            worked_dates=','.join(d.isoformat() for d in worked),
            for_pay_month=latest.month,
            for_pay_year=latest.year,
            status='pending',
            reason=(form.reason.data or '').strip() or None,
            submitted_by_user_id=current_user.id,
        )
        db.session.add(row)
        db.session.commit()
        flash('Overtime request submitted.', 'success')
        return redirect(url_for('overtime.index'))
    return render_template('overtime/form.html', form=form, title='Request overtime', for_employee=None)


@overtime_bp.route('/request-for-employee', methods=['GET', 'POST'])
@login_required
@permission_required('submit_overtime_same_dept')
def new_for_employee():
    cid = require_company_id()
    submitter = (
        db.session.get(Employee, current_user.employee_id) if current_user.employee_id else None
    )
    if not submitter or submitter.company_id != cid:
        flash('Your account must be linked to an employee in this company.', 'warning')
        return redirect(url_for('overtime.index'))
    form = OvertimeForEmployeeForm()
    peers = (
        db.session.query(Employee)
        .filter(Employee.company_id == cid, Employee.status == 'active', Employee.id != submitter.id)
        .order_by(Employee.last_name, Employee.first_name)
        .all()
    )
    choices = []
    for e in peers:
        if _can_submit_for_other(submitter, e):
            choices.append((e.id, f'{e.employee_number} — {e.full_name}'))
    form.employee_id.choices = [('', '— Select employee —')] + choices
    if request.method == 'GET' and not form.for_pay_year.data:
        form.for_pay_year.data = datetime.utcnow().year
        form.for_pay_month.data = datetime.utcnow().month
    if form.validate_on_submit():
        worked = form.parsed_worked_dates()
        latest = max(worked)
        target = db.session.get(Employee, form.employee_id.data)
        if not target or not _can_submit_for_other(submitter, target):
            flash('You cannot submit overtime for that employee.', 'danger')
            return redirect(url_for('overtime.new_for_employee'))
        row = OvertimeRequest(
            company_id=cid,
            employee_id=target.id,
            days=len(worked),
            worked_dates=','.join(d.isoformat() for d in worked),
            for_pay_month=latest.month,
            for_pay_year=latest.year,
            status='pending',
            reason=(form.reason.data or '').strip() or None,
            submitted_by_user_id=current_user.id,
        )
        db.session.add(row)
        db.session.commit()
        flash('Overtime request submitted for employee.', 'success')
        return redirect(url_for('overtime.index'))
    return render_template(
        'overtime/form.html',
        form=form,
        title='Overtime for employee',
        for_employee=True,
    )


@overtime_bp.route('/<int:id>/review', methods=['GET', 'POST'])
@login_required
def review(id):
    req = db.session.get(OvertimeRequest, id)
    if not req or req.company_id != require_company_id():
        abort(404)
    if req.status != 'pending':
        flash('This request is no longer pending.', 'warning')
        return redirect(url_for('overtime.index'))
    if not _can_approve(req):
        abort(403)
    form = OvertimeReviewForm()
    if form.validate_on_submit():
        action = form.action.data
        req.reviewed_by_user_id = current_user.id
        req.reviewed_at = datetime.utcnow()
        req.review_notes = (form.review_notes.data or '').strip() or None
        if action == 'approve':
            req.status = 'approved'
            flash('Overtime request approved.', 'success')
        else:
            req.status = 'rejected'
            flash('Overtime request rejected.', 'info')
        db.session.commit()
        return redirect(url_for('overtime.index'))
    return render_template('overtime/review.html', form=form, ot=req)


@overtime_bp.route('/<int:id>/cancel', methods=['POST'])
@login_required
def cancel(id):
    req = db.session.get(OvertimeRequest, id)
    if not req or req.company_id != require_company_id():
        abort(404)
    if req.status != 'pending':
        flash('Only pending requests can be cancelled.', 'warning')
        return redirect(url_for('overtime.index'))
    if req.employee_id != current_user.employee_id and not current_user.has_permission('approve_overtime'):
        abort(403)
    req.status = 'cancelled'
    db.session.commit()
    flash('Request cancelled.', 'info')
    return redirect(url_for('overtime.index'))
