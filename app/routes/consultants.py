"""Consultants: monthly fee, withholding tax only, on shared payroll runs."""
from datetime import date
from decimal import Decimal

from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, current_app
from flask_login import login_required
from sqlalchemy.orm import joinedload

from app.decorators.permissions import permission_required
from app.extensions import db
from app.forms.consultant_forms import ConsultantForm, ConsultantCompensationForm
from app.models.company import Branch
from app.models.consultant import Consultant, ConsultantCompensation
from app.models.employee import Employee
from app.utils.currency import currency_for_branch
from app.utils.tenant import require_company_id


consultants_bp = Blueprint('consultants', __name__)


def _load_consultant(consultant_id: int) -> Consultant:
    cid = require_company_id()
    c = (
        db.session.query(Consultant)
        .options(joinedload(Consultant.branch))
        .filter(Consultant.id == consultant_id, Consultant.company_id == cid)
        .first()
    )
    if not c:
        abort(404)
    return c


def _branch_choices():
    cid = require_company_id()
    branches = db.session.query(Branch).filter(Branch.company_id == cid).order_by(Branch.name).all()
    return [(b.id, b.name) for b in branches]


def _kra_pin_taken(kra_pin: str | None, exclude_consultant_id: int | None = None) -> bool:
    if not kra_pin or not kra_pin.strip():
        return False
    pin = kra_pin.strip().upper()
    cid = require_company_id()
    q_emp = db.session.query(Employee.id).filter(
        Employee.company_id == cid,
        db.func.upper(Employee.kra_pin) == pin,
    )
    q_con = db.session.query(Consultant.id).filter(
        Consultant.company_id == cid,
        db.func.upper(Consultant.kra_pin) == pin,
    )
    if exclude_consultant_id:
        q_con = q_con.filter(Consultant.id != exclude_consultant_id)
    return q_emp.first() is not None or q_con.first() is not None


@consultants_bp.route('/')
@login_required
@permission_required('view_employees')
def index():
    cid = require_company_id()
    status = (request.args.get('status') or '').strip().lower()
    search = (request.args.get('q') or '').strip()
    q = (
        db.session.query(Consultant)
        .options(joinedload(Consultant.branch))
        .filter(Consultant.company_id == cid)
    )
    if status in {'active', 'inactive', 'terminated'}:
        q = q.filter(Consultant.status == status)
    if search:
        q = q.filter(
            db.or_(
                Consultant.first_name.ilike(f'%{search}%'),
                Consultant.last_name.ilike(f'%{search}%'),
                Consultant.consultant_number.ilike(f'%{search}%'),
                Consultant.email.ilike(f'%{search}%'),
                Consultant.kra_pin.ilike(f'%{search}%'),
            )
        )
    consultants = q.order_by(Consultant.first_name, Consultant.last_name).all()
    return render_template('consultants/index.html', consultants=consultants)


@consultants_bp.route('/create', methods=['GET', 'POST'])
@login_required
@permission_required('edit_employees')
def create():
    form = ConsultantForm()
    form.branch_id.choices = _branch_choices()
    if request.method == 'GET' and not form.start_date.data:
        form.start_date.data = date.today()
    if form.validate_on_submit():
        branch = db.session.get(Branch, form.branch_id.data)
        cid = require_company_id()
        if not branch or branch.company_id != cid:
            flash('Select a valid branch.', 'danger')
            return render_template('consultants/create.html', form=form)
        kra = (form.kra_pin.data or '').strip() or None
        if _kra_pin_taken(kra):
            flash('KRA PIN is already used by an employee or consultant.', 'danger')
            return render_template('consultants/create.html', form=form)
        c = Consultant(
            company_id=cid,
            branch_id=branch.id,
            consultant_number=(form.consultant_number.data or '').strip() or None,
            first_name=form.first_name.data.strip(),
            last_name=form.last_name.data.strip(),
            middle_name=(form.middle_name.data or '').strip() or None,
            email=(form.email.data or '').strip() or None,
            phone=(form.phone.data or '').strip() or None,
            national_id=(form.national_id.data or '').strip() or None,
            kra_pin=kra,
            bank_name=(form.bank_name.data or '').strip() or None,
            bank_branch=(form.bank_branch.data or '').strip() or None,
            bank_account_number=(form.bank_account_number.data or '').strip() or None,
            bank_code=(form.bank_code.data or '').strip() or None,
            status=form.status.data,
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            withholding_rate=form.withholding_rate.data,
            prorate_payroll=True,
            notes=(form.notes.data or '').strip() or None,
        )
        db.session.add(c)
        db.session.commit()
        flash('Consultant created.', 'success')
        return redirect(url_for('consultants.view', id=c.id))
    return render_template('consultants/create.html', form=form)


@consultants_bp.route('/<int:id>')
@login_required
@permission_required('view_employees')
def view(id):
    c = _load_consultant(id)
    compensation = (
        db.session.query(ConsultantCompensation)
        .filter(ConsultantCompensation.consultant_id == id)
        .order_by(ConsultantCompensation.effective_from.desc())
        .all()
    )
    currency_code = currency_for_branch(
        c.branch,
        app_default=current_app.config.get('DEFAULT_CURRENCY', 'KES'),
    )
    return render_template(
        'consultants/view.html',
        consultant=c,
        compensation_records=compensation,
        currency_code=currency_code,
    )


@consultants_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('edit_employees')
def edit(id):
    c = _load_consultant(id)
    form = ConsultantForm(obj=c)
    form.branch_id.choices = _branch_choices()
    if form.validate_on_submit():
        branch = db.session.get(Branch, form.branch_id.data)
        if not branch or branch.company_id != c.company_id:
            flash('Select a valid branch.', 'danger')
            return render_template('consultants/edit.html', form=form, consultant=c)
        kra = (form.kra_pin.data or '').strip() or None
        if _kra_pin_taken(kra, exclude_consultant_id=c.id):
            flash('KRA PIN is already used by an employee or consultant.', 'danger')
            return render_template('consultants/edit.html', form=form, consultant=c)
        c.consultant_number = (form.consultant_number.data or '').strip() or None
        c.first_name = form.first_name.data.strip()
        c.last_name = form.last_name.data.strip()
        c.middle_name = (form.middle_name.data or '').strip() or None
        c.email = (form.email.data or '').strip() or None
        c.phone = (form.phone.data or '').strip() or None
        c.national_id = (form.national_id.data or '').strip() or None
        c.kra_pin = kra
        c.bank_name = (form.bank_name.data or '').strip() or None
        c.bank_branch = (form.bank_branch.data or '').strip() or None
        c.bank_account_number = (form.bank_account_number.data or '').strip() or None
        c.bank_code = (form.bank_code.data or '').strip() or None
        c.branch_id = branch.id
        c.status = form.status.data
        c.start_date = form.start_date.data
        c.end_date = form.end_date.data
        c.withholding_rate = form.withholding_rate.data
        c.prorate_payroll = True
        c.notes = (form.notes.data or '').strip() or None
        db.session.commit()
        flash('Consultant updated.', 'success')
        return redirect(url_for('consultants.view', id=c.id))
    return render_template('consultants/edit.html', form=form, consultant=c)


@consultants_bp.route('/<int:id>/compensation', methods=['GET', 'POST'])
@login_required
@permission_required('edit_employees')
def compensation(id):
    c = _load_consultant(id)
    form = ConsultantCompensationForm()
    records = (
        db.session.query(ConsultantCompensation)
        .filter(ConsultantCompensation.consultant_id == id)
        .order_by(ConsultantCompensation.effective_from.desc())
        .all()
    )
    currency_code = currency_for_branch(
        c.branch,
        app_default=current_app.config.get('DEFAULT_CURRENCY', 'KES'),
    )
    if request.method == 'POST' and form.validate_on_submit():
        rec = ConsultantCompensation(
            consultant_id=id,
            effective_from=form.effective_from.data,
            effective_to=form.effective_to.data,
            monthly_fee=form.monthly_fee.data,
            other_allowances=form.other_allowances.data or Decimal('0'),
            notes=(form.notes.data or '').strip() or None,
        )
        db.session.add(rec)
        db.session.commit()
        flash('Compensation record added.', 'success')
        return redirect(url_for('consultants.compensation', id=id))
    return render_template(
        'consultants/compensation.html',
        consultant=c,
        form=form,
        records=records,
        currency_code=currency_code,
    )


@consultants_bp.route('/<int:id>/compensation/<int:comp_id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('edit_employees')
def compensation_edit(id, comp_id):
    c = _load_consultant(id)
    rec = db.session.query(ConsultantCompensation).filter(
        ConsultantCompensation.id == comp_id,
        ConsultantCompensation.consultant_id == id,
    ).first()
    if not rec:
        abort(404)
    form = ConsultantCompensationForm(obj=rec)
    currency_code = currency_for_branch(
        c.branch,
        app_default=current_app.config.get('DEFAULT_CURRENCY', 'KES'),
    )
    if form.validate_on_submit():
        rec.effective_from = form.effective_from.data
        rec.effective_to = form.effective_to.data
        rec.monthly_fee = form.monthly_fee.data
        rec.other_allowances = form.other_allowances.data or Decimal('0')
        rec.notes = (form.notes.data or '').strip() or None
        db.session.commit()
        flash('Compensation record updated.', 'success')
        return redirect(url_for('consultants.compensation', id=id))
    return render_template(
        'consultants/compensation_edit.html',
        consultant=c,
        compensation_record=rec,
        form=form,
        currency_code=currency_code,
    )


@consultants_bp.route('/<int:id>/compensation/<int:comp_id>/delete', methods=['POST'])
@login_required
@permission_required('edit_employees')
def compensation_delete(id, comp_id):
    _load_consultant(id)
    rec = db.session.query(ConsultantCompensation).filter(
        ConsultantCompensation.id == comp_id,
        ConsultantCompensation.consultant_id == id,
    ).first()
    if rec:
        db.session.delete(rec)
        db.session.commit()
        flash('Compensation record deleted.', 'success')
    return redirect(url_for('consultants.compensation', id=id))
