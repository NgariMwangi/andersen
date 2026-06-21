"""Job title management."""
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from app.extensions import db
from app.models.job_title import JobTitle
from app.forms.job_title_forms import JobTitleForm
from app.decorators.permissions import permission_required
from app.utils.tenant import require_company_id

job_titles_bp = Blueprint('job_titles', __name__)


@job_titles_bp.route('/')
@login_required
@permission_required('view_departments')
def index():
    job_titles = (
        db.session.query(JobTitle)
        .filter(JobTitle.company_id == require_company_id())
        .order_by(JobTitle.name)
        .all()
    )
    return render_template('job_titles/index.html', job_titles=job_titles)


@job_titles_bp.route('/create', methods=['GET', 'POST'])
@login_required
@permission_required('manage_departments')
def create():
    form = JobTitleForm()
    if form.validate_on_submit():
        cid = require_company_id()
        jt = JobTitle(
            company_id=cid,
            code=None,
            name=form.name.data.strip(),
            description=form.description.data.strip() or None,
            grade=None,
        )
        db.session.add(jt)
        db.session.commit()
        flash('Job title created.', 'success')
        return redirect(url_for('job_titles.index'))
    return render_template('job_titles/create.html', form=form)


@job_titles_bp.route('/<int:id>')
@login_required
@permission_required('view_departments')
def view(id):
    jt = db.session.get(JobTitle, id)
    if jt is None or jt.company_id != require_company_id():
        flash('Job title not found.', 'danger')
        return redirect(url_for('job_titles.index'))
    employee_count = len(jt.employees) if jt.employees else 0
    return render_template('job_titles/view.html', job_title=jt, employee_count=employee_count)


@job_titles_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('manage_departments')
def edit(id):
    jt = db.session.get(JobTitle, id)
    if jt is None or jt.company_id != require_company_id():
        flash('Job title not found.', 'danger')
        return redirect(url_for('job_titles.index'))
    form = JobTitleForm()
    if form.validate_on_submit():
        code_raw = (form.code.data or '').strip()
        code = code_raw.upper() if code_raw else None
        if code:
            existing = (
                db.session.query(JobTitle)
                .filter(
                    JobTitle.company_id == jt.company_id,
                    JobTitle.code == code,
                    JobTitle.id != id,
                )
                .first()
            )
            if existing:
                flash('A job title with this code already exists.', 'danger')
                return render_template('job_titles/edit.html', form=form, job_title=jt)
        jt.code = code
        jt.name = form.name.data.strip()
        jt.description = form.description.data.strip() or None
        jt.grade = form.grade.data.strip() or None
        db.session.commit()
        flash('Job title updated.', 'success')
        return redirect(url_for('job_titles.view', id=jt.id))
    if request.method == 'GET':
        form.code.data = jt.code
        form.name.data = jt.name
        form.description.data = jt.description or ''
        form.grade.data = jt.grade or ''
    return render_template('job_titles/edit.html', form=form, job_title=jt)


@job_titles_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('manage_departments')
def delete(id):
    jt = db.session.get(JobTitle, id)
    if jt is None or jt.company_id != require_company_id():
        flash('Job title not found.', 'danger')
        return redirect(url_for('job_titles.index'))
    employee_count = len(jt.employees) if jt.employees else 0
    if employee_count > 0:
        flash(f'Cannot delete: {employee_count} employee(s) have this job title. Reassign them first.', 'danger')
        return redirect(url_for('job_titles.view', id=id))
    db.session.delete(jt)
    db.session.commit()
    flash('Job title deleted.', 'success')
    return redirect(url_for('job_titles.index'))
