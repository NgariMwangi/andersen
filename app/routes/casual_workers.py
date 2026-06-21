"""Casual workers: separate from payroll employees."""
from datetime import date
from decimal import Decimal

from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, current_app
from flask_login import login_required
from sqlalchemy.orm import joinedload

from app.decorators.permissions import permission_required
from app.extensions import db
from app.models.company import Branch
from app.models.casual_worker import CasualWorker, CasualPayment
from app.services.casual_payment_engine import calc_casual_payment
from app.utils.tenant import require_company_id


casual_workers_bp = Blueprint('casual_workers', __name__)
VALID_RATE_UNITS = {'hourly', 'daily', 'weekly', 'monthly'}


def _dec_from_form(name: str, default: str = '0') -> Decimal:
    raw = (request.form.get(name) or '').strip()
    try:
        return Decimal(raw or default)
    except Exception:
        return Decimal(default)


@casual_workers_bp.route('/')
@login_required
@permission_required('view_employees')
def index():
    cid = require_company_id()
    status = (request.args.get('status') or '').strip().lower()
    search = (request.args.get('q') or '').strip()

    q = (
        db.session.query(CasualWorker)
        .options(joinedload(CasualWorker.branch))
        .filter(CasualWorker.company_id == cid)
    )
    if status in {'active', 'inactive'}:
        q = q.filter(CasualWorker.status == status)
    if search:
        q = q.filter(
            db.or_(
                CasualWorker.first_name.ilike(f'%{search}%'),
                CasualWorker.last_name.ilike(f'%{search}%'),
                CasualWorker.worker_number.ilike(f'%{search}%'),
                CasualWorker.phone.ilike(f'%{search}%'),
                CasualWorker.national_id.ilike(f'%{search}%'),
            )
        )
    workers = q.order_by(CasualWorker.first_name, CasualWorker.last_name).all()
    return render_template('casual_workers/index.html', workers=workers)


@casual_workers_bp.route('/create', methods=['GET', 'POST'])
@login_required
@permission_required('edit_employees')
def create():
    cid = require_company_id()
    branches = db.session.query(Branch).filter(Branch.company_id == cid).order_by(Branch.name).all()
    if request.method == 'POST':
        first_name = (request.form.get('first_name') or '').strip()
        last_name = (request.form.get('last_name') or '').strip()
        worker_number = (request.form.get('worker_number') or '').strip() or None
        phone = (request.form.get('phone') or '').strip() or None
        national_id = (request.form.get('national_id') or '').strip() or None
        rate_unit = (request.form.get('rate_unit') or 'daily').strip().lower()
        status = (request.form.get('status') or 'active').strip().lower()
        notes = (request.form.get('notes') or '').strip() or None
        branch_id = request.form.get('branch_id', type=int)
        start_date = request.form.get('start_date', type=lambda v: date.fromisoformat(v))
        end_date = request.form.get('end_date', type=lambda v: date.fromisoformat(v) if v else None)
        daily_rate = _dec_from_form('daily_rate')

        branch = db.session.get(Branch, branch_id) if branch_id else None
        if not first_name or not last_name or not start_date or not branch or branch.company_id != cid:
            flash('First name, last name, branch and start date are required.', 'danger')
            return render_template('casual_workers/create.html', branches=branches)
        if status not in {'active', 'inactive'}:
            status = 'active'
        if rate_unit not in VALID_RATE_UNITS:
            rate_unit = 'daily'

        worker = CasualWorker(
            company_id=cid,
            branch_id=branch.id,
            worker_number=worker_number,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            national_id=national_id,
            daily_rate=max(daily_rate, Decimal('0')),
            rate_unit=rate_unit,
            status=status,
            start_date=start_date,
            end_date=end_date,
            notes=notes,
        )
        db.session.add(worker)
        db.session.commit()
        flash('Casual worker created.', 'success')
        return redirect(url_for('casual_workers.view', id=worker.id))
    return render_template('casual_workers/create.html', branches=branches)


@casual_workers_bp.route('/<int:id>')
@login_required
@permission_required('view_employees')
def view(id):
    cid = require_company_id()
    worker = db.session.get(CasualWorker, id)
    if not worker or worker.company_id != cid:
        abort(404)
    payments = (
        db.session.query(CasualPayment)
        .filter(CasualPayment.worker_id == id)
        .order_by(CasualPayment.period_year.desc(), CasualPayment.period_month.desc(), CasualPayment.id.desc())
        .all()
    )
    return render_template('casual_workers/view.html', worker=worker, payments=payments, today=date.today())


@casual_workers_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('edit_employees')
def edit(id):
    cid = require_company_id()
    worker = db.session.get(CasualWorker, id)
    if not worker or worker.company_id != cid:
        abort(404)
    branches = db.session.query(Branch).filter(Branch.company_id == cid).order_by(Branch.name).all()
    if request.method == 'POST':
        first_name = (request.form.get('first_name') or '').strip()
        last_name = (request.form.get('last_name') or '').strip()
        worker_number = (request.form.get('worker_number') or '').strip() or None
        phone = (request.form.get('phone') or '').strip() or None
        national_id = (request.form.get('national_id') or '').strip() or None
        rate_unit = (request.form.get('rate_unit') or 'daily').strip().lower()
        status = (request.form.get('status') or 'active').strip().lower()
        notes = (request.form.get('notes') or '').strip() or None
        branch_id = request.form.get('branch_id', type=int)
        start_date = request.form.get('start_date', type=lambda v: date.fromisoformat(v))
        end_date = request.form.get('end_date', type=lambda v: date.fromisoformat(v) if v else None)
        daily_rate = _dec_from_form('daily_rate')

        branch = db.session.get(Branch, branch_id) if branch_id else None
        if not first_name or not last_name or not start_date or not branch or branch.company_id != cid:
            flash('First name, last name, branch and start date are required.', 'danger')
            return render_template('casual_workers/edit.html', worker=worker, branches=branches)
        if status not in {'active', 'inactive'}:
            status = 'active'
        if rate_unit not in VALID_RATE_UNITS:
            rate_unit = 'daily'

        worker.first_name = first_name
        worker.last_name = last_name
        worker.worker_number = worker_number
        worker.phone = phone
        worker.national_id = national_id
        worker.status = status
        worker.rate_unit = rate_unit
        worker.branch_id = branch.id
        worker.start_date = start_date
        worker.end_date = end_date
        worker.daily_rate = max(daily_rate, Decimal('0'))
        worker.notes = notes
        db.session.commit()
        flash('Casual worker updated.', 'success')
        return redirect(url_for('casual_workers.view', id=worker.id))
    return render_template('casual_workers/edit.html', worker=worker, branches=branches)


@casual_workers_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('edit_employees')
def delete(id):
    cid = require_company_id()
    worker = db.session.get(CasualWorker, id)
    if not worker or worker.company_id != cid:
        abort(404)
    db.session.delete(worker)
    db.session.commit()
    flash('Casual worker deleted.', 'success')
    return redirect(url_for('casual_workers.index'))


@casual_workers_bp.route('/<int:id>/payments', methods=['POST'])
@login_required
@permission_required('edit_employees')
def upsert_payment(id):
    cid = require_company_id()
    worker = db.session.get(CasualWorker, id)
    if not worker or worker.company_id != cid:
        abort(404)

    period_year = request.form.get('period_year', type=int) or date.today().year
    period_month = request.form.get('period_month', type=int) or date.today().month
    units_worked = _dec_from_form('units_worked')
    rate_per_unit = _dec_from_form('rate_per_unit', default=str(worker.daily_rate or '0'))
    adjustments = _dec_from_form('adjustments')
    notes = (request.form.get('notes') or '').strip() or None

    if period_month < 1 or period_month > 12 or period_year < 2000 or period_year > 2100:
        flash('Invalid period selected.', 'danger')
        return redirect(url_for('casual_workers.view', id=id))

    totals = calc_casual_payment(days_worked=units_worked, rate_per_day=rate_per_unit, adjustments=adjustments)
    row = (
        db.session.query(CasualPayment)
        .filter(
            CasualPayment.company_id == cid,
            CasualPayment.worker_id == id,
            CasualPayment.period_year == period_year,
            CasualPayment.period_month == period_month,
        )
        .first()
    )
    if not row:
        row = CasualPayment(
            company_id=cid,
            worker_id=id,
            period_year=period_year,
            period_month=period_month,
            status='pending',
        )
        db.session.add(row)

    row.days_worked = max(units_worked, Decimal('0'))
    row.rate_per_day = max(rate_per_unit, Decimal('0'))
    row.adjustments = adjustments
    row.gross_amount = totals['gross_amount']
    row.net_amount = totals['net_amount']
    row.notes = notes
    db.session.commit()
    flash('Casual payment line saved.', 'success')
    return redirect(url_for('casual_workers.view', id=id))


@casual_workers_bp.route('/payments/<int:payment_id>/mark-paid', methods=['POST'])
@login_required
@permission_required('edit_employees')
def mark_paid(payment_id):
    cid = require_company_id()
    row = db.session.get(CasualPayment, payment_id)
    if not row or row.company_id != cid:
        abort(404)
    row.status = 'paid'
    row.paid_on = date.today()
    db.session.commit()
    flash('Payment marked as paid.', 'success')
    return redirect(url_for('casual_workers.view', id=row.worker_id))


@casual_workers_bp.route('/payments/<int:payment_id>/mark-pending', methods=['POST'])
@login_required
@permission_required('edit_employees')
def mark_pending(payment_id):
    cid = require_company_id()
    row = db.session.get(CasualPayment, payment_id)
    if not row or row.company_id != cid:
        abort(404)
    row.status = 'pending'
    row.paid_on = None
    db.session.commit()
    flash('Payment marked as pending.', 'success')
    return redirect(url_for('casual_workers.view', id=row.worker_id))


@casual_workers_bp.route('/report')
@login_required
@permission_required('view_reports')
def report():
    cid = require_company_id()
    today = date.today()
    year = request.args.get('year', type=int) or today.year
    month = request.args.get('month', type=int) or today.month

    if month < 1 or month > 12:
        month = today.month

    rows = (
        db.session.query(CasualPayment)
        .options(joinedload(CasualPayment.worker))
        .filter(
            CasualPayment.company_id == cid,
            CasualPayment.period_year == year,
            CasualPayment.period_month == month,
        )
        .order_by(CasualPayment.status.asc(), CasualPayment.net_amount.desc())
        .all()
    )
    total_gross = sum((r.gross_amount or 0) for r in rows)
    total_net = sum((r.net_amount or 0) for r in rows)
    total_pending = sum((r.net_amount or 0) for r in rows if r.status == 'pending')
    total_paid = sum((r.net_amount or 0) for r in rows if r.status == 'paid')

    return render_template(
        'casual_workers/report.html',
        rows=rows,
        year=year,
        month=month,
        total_gross=total_gross,
        total_net=total_net,
        total_pending=total_pending,
        total_paid=total_paid,
        months=list(range(1, 13)),
        years=list(range(today.year - 1, today.year + 2)),
        currency_code=current_app.config.get('DEFAULT_CURRENCY', 'KES'),
    )
