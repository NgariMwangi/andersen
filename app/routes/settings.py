"""System configuration, user management, and audit log viewer."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from app.extensions import db
from app.models.audit import AuditLog
from app.models.user import User, Role, UserRole
from app.models.employee import Employee
from app.models.employer import Employer
from app.models.company import Company, Branch
from app.forms.user_forms import UserForm
from app.forms.settings_forms import EmployerForm, CreateOrganizationForm
from app.decorators.permissions import permission_required
from app.utils.tenant import require_company_id
from app.services.company_bootstrap import bootstrap_company_defaults

settings_bp = Blueprint('settings', __name__)


@settings_bp.route('/')
@login_required
@permission_required('manage_settings')
def index():
    return render_template('settings/index.html')


@settings_bp.route('/users')
@login_required
@permission_required('manage_settings')
def users():
    cid = require_company_id()
    users_q = db.session.query(User).filter(User.company_id == cid).order_by(User.email).all()
    return render_template('settings/users.html', users=users_q)


def _populate_user_form_choices(form: UserForm, company_id: int):
    employees = (
        db.session.query(Employee)
        .filter(Employee.company_id == company_id)
        .order_by(Employee.first_name, Employee.last_name)
        .all()
    )
    # 0 means "no employee link"
    form.employee_id.choices = [(0, '-- None --')] + [(e.id, f"{e.employee_number} - {e.full_name}") for e in employees]
    roles = db.session.query(Role).order_by(Role.name).all()
    form.role_ids.choices = [(r.id, r.name) for r in roles]


@settings_bp.route('/users/create', methods=['GET', 'POST'])
@login_required
@permission_required('manage_settings')
def user_create():
    from flask import current_app

    cid = require_company_id()
    form = UserForm()
    _populate_user_form_choices(form, cid)
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if db.session.query(User).filter_by(email=email).first():
            flash('A user with that email already exists.', 'danger')
            return render_template('settings/user_form.html', form=form, user=None)
        if not form.password.data:
            flash('Password is required for new users.', 'danger')
            return render_template('settings/user_form.html', form=form, user=None)
        if len(form.password.data) < current_app.config.get('PASSWORD_MIN_LENGTH', 8):
            flash(f"Password must be at least {current_app.config.get('PASSWORD_MIN_LENGTH', 8)} characters.", 'danger')
            return render_template('settings/user_form.html', form=form, user=None)
        employee_id = form.employee_id.data or 0
        if employee_id:
            link_emp = db.session.get(Employee, employee_id)
            if not link_emp or link_emp.company_id != cid:
                flash('Invalid employee selected for this organization.', 'danger')
                return render_template('settings/user_form.html', form=form, user=None)
        user = User(
            email=email,
            company_id=cid,
            is_active=form.is_active.data,
            is_superuser=form.is_superuser.data,
        )
        user.set_password(form.password.data)
        user.employee_id = employee_id or None
        db.session.add(user)
        db.session.flush()
        # Assign roles
        selected_role_ids = form.role_ids.data or []
        for rid in selected_role_ids:
            role = db.session.get(Role, rid)
            if role:
                db.session.add(UserRole(user_id=user.id, role_id=role.id))
        db.session.commit()
        flash('User created.', 'success')
        return redirect(url_for('settings.users'))
    return render_template('settings/user_form.html', form=form, user=None)


@settings_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('manage_settings')
def user_edit(user_id):
    from flask import current_app

    cid = require_company_id()
    user = db.session.get(User, user_id)
    if not user or user.company_id != cid:
        flash('User not found.', 'danger')
        return redirect(url_for('settings.users'))
    form = UserForm()
    _populate_user_form_choices(form, cid)
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        existing = db.session.query(User).filter(User.email == email, User.id != user.id).first()
        if existing:
            flash('Another user with that email already exists.', 'danger')
            return render_template('settings/user_form.html', form=form, user=user)
        user.email = email
        user.is_active = form.is_active.data
        user.is_superuser = form.is_superuser.data
        employee_id = form.employee_id.data or 0
        if employee_id:
            link_emp = db.session.get(Employee, employee_id)
            if not link_emp or link_emp.company_id != cid:
                flash('Invalid employee selected for this organization.', 'danger')
                return render_template('settings/user_form.html', form=form, user=user)
        user.employee_id = employee_id or None
        if form.password.data:
            if len(form.password.data) < current_app.config.get('PASSWORD_MIN_LENGTH', 8):
                flash(f"Password must be at least {current_app.config.get('PASSWORD_MIN_LENGTH', 8)} characters.", 'danger')
                return render_template('settings/user_form.html', form=form, user=user)
            user.set_password(form.password.data)
        # Update roles
        selected_role_ids = set(form.role_ids.data or [])
        # Remove roles not selected
        db.session.query(UserRole).filter(UserRole.user_id == user.id, ~UserRole.role_id.in_(selected_role_ids)).delete(synchronize_session=False)
        # Add new ones
        existing_role_ids = {ur.role_id for ur in db.session.query(UserRole).filter(UserRole.user_id == user.id).all()}
        for rid in selected_role_ids:
            if rid not in existing_role_ids:
                role = db.session.get(Role, rid)
                if role:
                    db.session.add(UserRole(user_id=user.id, role_id=role.id))
        db.session.commit()
        flash('User updated.', 'success')
        return redirect(url_for('settings.users'))
    if request.method == 'GET':
        form.email.data = user.email
        form.is_active.data = user.is_active
        form.is_superuser.data = user.is_superuser
        form.employee_id.data = user.employee_id or 0
        form.role_ids.data = [r.id for r in user.roles]
    return render_template('settings/user_form.html', form=form, user=user)


@settings_bp.route('/users/<int:user_id>/toggle-active', methods=['POST'])
@login_required
@permission_required('manage_settings')
def user_toggle_active(user_id):
    cid = require_company_id()
    user = db.session.get(User, user_id)
    if not user or user.company_id != cid:
        flash('User not found.', 'danger')
        return redirect(url_for('settings.users'))
    user.is_active = not user.is_active
    db.session.commit()
    flash('User {}.'.format('activated' if user.is_active else 'deactivated'), 'success')
    return redirect(url_for('settings.users'))


@settings_bp.route('/audit')
@login_required
@permission_required('view_audit_log')
def audit_log():
    q = db.session.query(AuditLog).order_by(AuditLog.created_at.desc())
    record_type = request.args.get('record_type')
    user_id = request.args.get('user_id', type=int)
    if record_type:
        q = q.filter(AuditLog.record_type == record_type)
    if user_id:
        q = q.filter(AuditLog.user_id == user_id)
    logs = q.limit(500).all()
    return render_template('settings/audit_log.html', logs=logs)


@settings_bp.route('/employer', methods=['GET', 'POST'])
@login_required
@permission_required('manage_settings')
def employer():
    """Create/update employer (company using the system)."""
    cid = require_company_id()
    form = EmployerForm()
    emp = db.session.query(Employer).filter(Employer.company_id == cid).first()

    if form.validate_on_submit():
        if not emp:
            emp = Employer(company_id=cid, name='')
            db.session.add(emp)

        emp.name = (form.name.data or '').strip()
        emp.kra_pin = (form.kra_pin.data or '').strip() or None
        emp.email = (form.email.data or '').strip() or None
        emp.phone = (form.phone.data or '').strip() or None
        emp.physical_address = (form.physical_address.data or '').strip() or None
        emp.postal_address = (form.postal_address.data or '').strip() or None
        emp.registration_number = (form.registration_number.data or '').strip() or None
        emp.welfare_kit_deduction = form.welfare_kit_deduction.data or 0

        db.session.commit()
        flash('Employer details saved.', 'success')
        return redirect(url_for('settings.employer'))

    # Populate initial form data on GET (or when submission fails validation).
    if emp:
        form.name.data = emp.name or ''
        form.kra_pin.data = emp.kra_pin or ''
        form.email.data = emp.email or ''
        form.phone.data = emp.phone or ''
        form.physical_address.data = emp.physical_address or ''
        form.postal_address.data = emp.postal_address or ''
        form.registration_number.data = emp.registration_number or ''
        form.welfare_kit_deduction.data = float(emp.welfare_kit_deduction or 0)

    return render_template('settings/employer.html', form=form, employer=emp)


@settings_bp.route('/companies')
@login_required
def companies_list():
    """List all tenant companies (platform superuser only)."""
    if not current_user.is_superuser:
        abort(403)
    companies = db.session.query(Company).order_by(Company.id).all()
    return render_template('settings/companies.html', companies=companies)


@settings_bp.route('/companies/new', methods=['GET', 'POST'])
@login_required
def companies_new():
    """Create another company + default branch + employer + first admin (platform superuser only)."""
    from flask import current_app

    if not current_user.is_superuser:
        abort(403)
    form = CreateOrganizationForm()
    if form.validate_on_submit():
        email = form.admin_email.data.strip().lower()
        if db.session.query(User).filter_by(email=email).first():
            flash('A user with that email already exists.', 'danger')
            return render_template('settings/company_new.html', form=form)
        min_len = current_app.config.get('PASSWORD_MIN_LENGTH', 8)
        pwd = form.admin_password.data
        if len(pwd) < min_len:
            flash(f'Password must be at least {min_len} characters.', 'danger')
            return render_template('settings/company_new.html', form=form)
        name = (form.company_name.data or '').strip()
        br_name = (form.branch_name.data or '').strip() or 'Head Office'
        cc_raw = (form.country_code.data or 'KE').strip().upper()
        cc = cc_raw[:2] if len(cc_raw) >= 2 else 'KE'
        company = Company(name=name or 'Company', is_active=True)
        db.session.add(company)
        db.session.flush()
        db.session.add(Branch(company_id=company.id, name=br_name, country_code=cc))
        db.session.add(Employer(company_id=company.id, name=name or 'Company'))
        admin = User(
            email=email,
            company_id=company.id,
            is_superuser=True,
            is_active=True,
        )
        admin.set_password(pwd)
        db.session.add(admin)
        db.session.flush()
        from app.services.rbac_bootstrap import get_role_by_code

        admin_role = get_role_by_code('ADMIN')
        if admin_role:
            db.session.add(UserRole(user_id=admin.id, role_id=admin_role.id))
        db.session.commit()
        bootstrap_company_defaults(company.id, cc)
        flash(
            f'Company "{company.name}" was created. The administrator ({email}) is a superuser for that tenant '
            'and can sign in immediately.',
            'success',
        )
        return redirect(url_for('settings.companies_list'))
    return render_template('settings/company_new.html', form=form)

