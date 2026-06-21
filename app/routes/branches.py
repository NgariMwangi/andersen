"""Branch (office / site) management — drives statutory country and public holidays."""
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required
from app.extensions import db
from app.models.company import Branch
from app.models.employee import Employee
from app.forms.branch_forms import BranchForm
from app.decorators.permissions import permission_required
from app.utils.tenant import require_company_id
from app.utils.currency import currency_for_branch

branches_bp = Blueprint('branches', __name__)


def _cc(raw: str | None) -> str:
    return (raw or 'KE').strip().upper()[:2]


@branches_bp.route('/')
@login_required
@permission_required('view_departments')
def index():
    cid = require_company_id()
    branches = (
        db.session.query(Branch)
        .filter(Branch.company_id == cid)
        .order_by(Branch.name)
        .all()
    )
    app_def = current_app.config.get('DEFAULT_CURRENCY', 'KES')
    rows = [
        (
            b,
            db.session.query(Employee).filter(Employee.branch_id == b.id).count(),
            currency_for_branch(b, app_default=app_def),
        )
        for b in branches
    ]
    return render_template('branches/index.html', rows=rows)


@branches_bp.route('/create', methods=['GET', 'POST'])
@login_required
@permission_required('manage_departments')
def create():
    cid = require_company_id()
    form = BranchForm()
    if form.validate_on_submit():
        name = (form.name.data or '').strip()
        existing = db.session.query(Branch).filter(Branch.company_id == cid, Branch.name == name).first()
        if existing:
            flash('A branch with this name already exists for your company.', 'danger')
            return render_template('branches/form.html', form=form, branch=None)
        cur = (form.currency_code.data or '').strip().upper()[:3] or None
        b = Branch(
            company_id=cid,
            name=name,
            country_code=_cc(form.country_code.data),
            currency_code=cur,
            timezone=(form.timezone.data or '').strip() or None,
        )
        db.session.add(b)
        db.session.commit()
        flash('Branch created.', 'success')
        return redirect(url_for('branches.index'))
    return render_template('branches/form.html', form=form, branch=None)


@branches_bp.route('/<int:id>')
@login_required
@permission_required('view_departments')
def view(id):
    cid = require_company_id()
    b = db.session.get(Branch, id)
    if not b or b.company_id != cid:
        flash('Branch not found.', 'danger')
        return redirect(url_for('branches.index'))
    emp_count = db.session.query(Employee).filter(Employee.branch_id == b.id).count()
    curr = currency_for_branch(b, app_default=current_app.config.get('DEFAULT_CURRENCY', 'KES'))
    return render_template('branches/view.html', branch=b, employee_count=emp_count, payroll_currency=curr)


@branches_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('manage_departments')
def edit(id):
    cid = require_company_id()
    b = db.session.get(Branch, id)
    if not b or b.company_id != cid:
        flash('Branch not found.', 'danger')
        return redirect(url_for('branches.index'))
    form = BranchForm()
    if form.validate_on_submit():
        name = (form.name.data or '').strip()
        existing = (
            db.session.query(Branch)
            .filter(Branch.company_id == cid, Branch.name == name, Branch.id != b.id)
            .first()
        )
        if existing:
            flash('A branch with this name already exists for your company.', 'danger')
            return render_template('branches/form.html', form=form, branch=b)
        b.name = name
        b.country_code = _cc(form.country_code.data)
        cur = (form.currency_code.data or '').strip().upper()[:3] or None
        b.currency_code = cur
        b.timezone = (form.timezone.data or '').strip() or None
        db.session.commit()
        flash('Branch updated.', 'success')
        return redirect(url_for('branches.view', id=b.id))
    if request.method == 'GET':
        form.name.data = b.name
        form.country_code.data = b.country_code or 'KE'
        form.currency_code.data = b.currency_code or ''
        form.timezone.data = b.timezone or ''
    return render_template('branches/form.html', form=form, branch=b)


@branches_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('manage_departments')
def delete(id):
    cid = require_company_id()
    b = db.session.get(Branch, id)
    if not b or b.company_id != cid:
        flash('Branch not found.', 'danger')
        return redirect(url_for('branches.index'))
    n = db.session.query(Employee).filter(Employee.branch_id == b.id).count()
    if n:
        flash(f'Cannot delete: {n} employee(s) are assigned to this branch. Reassign them first.', 'danger')
        return redirect(url_for('branches.view', id=id))
    db.session.delete(b)
    db.session.commit()
    flash('Branch deleted.', 'success')
    return redirect(url_for('branches.index'))
