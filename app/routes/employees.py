"""Employee CRUD and management."""
import calendar
from datetime import date, timedelta
import os
import mimetypes
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, abort, send_file, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy.orm import joinedload
from app.extensions import db
from app.models.employee import Employee
from app.models.employee_assignment_history import EmployeeAssignmentHistory
from app.models.company import Branch
from app.models.department import Department
from app.models.job_title import JobTitle
from app.models.payroll import EmployeeSalary, EmployeeAllowance, Allowance, EmployeeDeduction
from app.models.user import User, Role, UserRole
from app.models.document import EmployeeDocument
from app.models.benefit import EmployeeBenefit
from app.forms.employee_forms import EmployeeForm, EmployeeSalaryForm, EmployeeSelfContactForm
from app.decorators.permissions import permission_required
from app.decorators.features import require_payroll
from app.utils.tenant import require_company_id
from app.utils.currency import currency_for_branch
from app.utils.validators import normalize_phone
from app.services.audit_service import log_create, log_update, log_delete, model_to_audit_dict
from app.services.employee_history_service import (
    assignment_snapshot,
    backfill_assignment_history_if_missing,
    record_initial_assignment,
    sync_assignment_history_after_edit,
)
from app.services.employee_relations_service import (
    employee_supervisor_ids,
    sync_employee_next_of_kin,
    sync_employee_supervisors,
)
from app.services.employee_document_service import (
    delete_employee_document,
    document_download_filename,
    documents_grouped_by_category,
    ensure_standard_document_categories,
    get_category_by_code,
    resolve_document_full_path,
    save_employee_document,
)

try:
    import cloudinary
    import cloudinary.uploader
    from cloudinary.utils import cloudinary_url
except Exception:  # pragma: no cover
    cloudinary = None
    cloudinary_url = None

employees_bp = Blueprint('employees', __name__)


def _next_birthday_for_year(year: int, month: int, day: int):
    """Build birthday date in a given year with leap-year fallback."""
    try:
        return date(year, month, day)
    except ValueError:
        # Treat Feb 29 birthdays as Mar 1 on non-leap years.
        return date(year, 3, 1)


def _clean_employee_number(raw_value: str | None):
    if raw_value is None:
        return None
    value = raw_value.strip()
    return value or None


def _company_branches(cid):
    return (
        db.session.query(Branch)
        .filter(Branch.company_id == cid)
        .order_by(Branch.name)
        .all()
    )


def _default_branch_id(cid):
    """When branch UI is hidden, assign the company's primary branch."""
    if current_app.config.get('ENABLE_BRANCHES', False):
        return None
    branches = _company_branches(cid)
    return branches[0].id if branches else None


def _apply_default_branch_to_form(form, cid):
    default_id = _default_branch_id(cid)
    if default_id and not form.branch_id.data:
        form.branch_id.data = default_id


def _parse_form_date(field_name: str, *, required: bool = False) -> date | None:
    raw = (request.form.get(field_name) or '').strip()
    if not raw:
        if required:
            raise ValueError(f'{field_name} is required')
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f'Invalid date for {field_name}') from exc


def _get_employee_for_status_action(employee_id: int) -> Employee:
    cid = require_company_id()
    emp = db.session.get(Employee, employee_id)
    if not emp or emp.company_id != cid:
        abort(404)
    return emp


def _populate_supervisor_choices(form, cid, exclude_employee_id=None):
    q = (
        db.session.query(Employee)
        .filter(Employee.company_id == cid, Employee.status == 'active')
        .order_by(Employee.first_name, Employee.last_name)
    )
    if exclude_employee_id:
        q = q.filter(Employee.id != exclude_employee_id)
    choices = [(e.id, e.full_name) for e in q.all()]
    form.supervisor_ids.choices = choices
    if hasattr(form, 'manager_id'):
        form.manager_id.choices = [('', '--')] + choices


def _employee_with_relations(employee_id: int) -> Employee | None:
    """Load employee with org relationships for profile/detail views."""
    from app.models.employee_relations import EmployeeSupervisor

    return (
        db.session.query(Employee)
        .options(
            joinedload(Employee.branch),
            joinedload(Employee.department),
            joinedload(Employee.job_title),
            joinedload(Employee.manager),
            joinedload(Employee.next_of_kin),
            joinedload(Employee.supervisor_links).joinedload(EmployeeSupervisor.supervisor),
        )
        .filter(Employee.id == employee_id)
        .first()
    )


def _can_view_employee(emp: Employee) -> bool:
    if emp.company_id != require_company_id():
        return False
    if (current_user.employee_id or 0) == emp.id:
        return True
    return current_user.has_permission('view_employees')


@employees_bp.route('/')
@login_required
@permission_required('view_employees')
def list():
    cid = require_company_id()
    director_title_ids = {
        jt.id
        for jt in db.session.query(JobTitle)
        .filter(
            JobTitle.company_id == cid,
            db.or_(
                JobTitle.name.ilike('%director%'),
                JobTitle.code.ilike('%director%'),
            ),
        )
        .all()
    }
    q = (
        db.session.query(Employee)
        .options(joinedload(Employee.branch))
        .filter(Employee.company_id == cid)
    )
    department_id = request.args.get('department_id', type=int)
    branch_id = request.args.get('branch_id', type=int)
    job_title_id = request.args.get('job_title_id', type=int)
    status = request.args.get('status')
    directors_only = request.args.get('directors_only') == '1'
    search = request.args.get('q', '').strip()
    if department_id:
        q = q.filter(Employee.department_id == department_id)
    if branch_id:
        q = q.filter(Employee.branch_id == branch_id)
    if job_title_id:
        q = q.filter(Employee.job_title_id == job_title_id)
    if status:
        q = q.filter(Employee.status == status)
    if directors_only:
        if director_title_ids:
            q = q.filter(Employee.job_title_id.in_(director_title_ids))
        else:
            q = q.filter(db.text('1=0'))
    if search:
        # Token-based "free" search: each token must appear in at least one key field.
        # This supports queries like "john mwangi", employee number fragments, emails, phones, IDs.
        terms = [t for t in search.split() if t]
        if terms:
            full_name_expr = (
                db.func.coalesce(Employee.first_name, '')
                + ' '
                + db.func.coalesce(Employee.middle_name, '')
                + ' '
                + db.func.coalesce(Employee.last_name, '')
            )
            reverse_name_expr = (
                db.func.coalesce(Employee.last_name, '')
                + ' '
                + db.func.coalesce(Employee.first_name, '')
                + ' '
                + db.func.coalesce(Employee.middle_name, '')
            )
            for term in terms:
                like = f'%{term}%'
                q = q.filter(
                    db.or_(
                        Employee.first_name.ilike(like),
                        Employee.middle_name.ilike(like),
                        Employee.last_name.ilike(like),
                        full_name_expr.ilike(like),
                        reverse_name_expr.ilike(like),
                        Employee.employee_number.ilike(like),
                        Employee.email.ilike(like),
                        Employee.phone.ilike(like),
                        Employee.national_id.ilike(like),
                        Employee.passport_number.ilike(like),
                        Employee.kra_pin.ilike(like),
                    )
                )
    employees = q.order_by(Employee.employee_number).all()
    departments = (
        db.session.query(Department).filter(Department.company_id == cid).order_by(Department.name).all()
    )
    branches = (
        db.session.query(Branch).filter(Branch.company_id == cid).order_by(Branch.name).all()
    )
    return render_template(
        'employees/list.html',
        employees=employees,
        departments=departments,
        branches=branches,
        director_title_ids=director_title_ids,
    )


@employees_bp.route('/birthdays')
@login_required
@permission_required('view_employees')
def birthdays():
    cid = require_company_id()
    today = date.today()
    selected_year = request.args.get('year', type=int) or date.today().year
    rows = (
        db.session.query(Employee)
        .filter(
            Employee.company_id == cid,
            Employee.status == 'active',
            Employee.date_of_birth.isnot(None),
        )
        .all()
    )
    month_groups = {month: [] for month in range(1, 13)}
    this_month_birthdays = 0
    this_week_birthdays = 0
    week_start = today
    week_end = today
    if selected_year == today.year:
        week_start = today
        week_end = today + timedelta(days=6)
    for emp in rows:
        dob = emp.date_of_birth
        birthday_this_year = _next_birthday_for_year(selected_year, dob.month, dob.day)
        if selected_year == today.year and birthday_this_year.month == today.month:
            this_month_birthdays += 1
        if selected_year == today.year and week_start <= birthday_this_year <= week_end:
            this_week_birthdays += 1
        days_until = (birthday_this_year - today).days if selected_year == today.year else None
        month_groups[birthday_this_year.month].append(
            {
                'employee': emp,
                'birthday': birthday_this_year,
                'turning_age': selected_year - dob.year,
                'weekday': birthday_this_year.strftime('%A'),
                'days_until': days_until,
                'coming_weekday_label': (
                    f"This coming {birthday_this_year.strftime('%A')}"
                    if selected_year == today.year and days_until is not None and 2 <= days_until <= 6
                    else None
                ),
                'status': (
                    'happy_birthday'
                    if selected_year == today.year and birthday_this_year == today
                    else 'past'
                    if selected_year == today.year and birthday_this_year < today
                    else 'upcoming'
                ),
            }
        )
    for month in month_groups:
        month_groups[month].sort(key=lambda item: (item['birthday'].day, item['employee'].full_name.lower()))
    year_choices = [selected_year - 1, selected_year, selected_year + 1]
    month_names = {month: calendar.month_name[month] for month in range(1, 13)}
    return render_template(
        'employees/birthdays.html',
        selected_year=selected_year,
        current_year=today.year,
        this_month_birthdays=this_month_birthdays,
        this_week_birthdays=this_week_birthdays,
        month_groups=month_groups,
        year_choices=year_choices,
        month_names=month_names,
    )


@employees_bp.route('/benefits')
@login_required
@permission_required('view_employees')
@require_payroll
def benefits_index():
    """Organization-wide employee benefits listing."""
    cid = require_company_id()
    search = (request.args.get('q') or '').strip()

    q = (
        db.session.query(EmployeeBenefit)
        .join(Employee, Employee.id == EmployeeBenefit.employee_id)
        .options(joinedload(EmployeeBenefit.employee))
        .filter(Employee.company_id == cid)
    )
    if search:
        q = q.filter(
            db.or_(
                EmployeeBenefit.title.ilike(f'%{search}%'),
                Employee.first_name.ilike(f'%{search}%'),
                Employee.last_name.ilike(f'%{search}%'),
                Employee.employee_number.ilike(f'%{search}%'),
            )
        )
    rows = q.order_by(EmployeeBenefit.created_at.desc()).all()
    return render_template('employees/benefits_index.html', rows=rows)


@employees_bp.route('/deductions')
@login_required
@permission_required('view_employees')
@require_payroll
def deductions_index():
    """Organization-wide employee deductions listing."""
    cid = require_company_id()
    search = (request.args.get('q') or '').strip()

    q = (
        db.session.query(EmployeeDeduction)
        .join(Employee, Employee.id == EmployeeDeduction.employee_id)
        .options(joinedload(EmployeeDeduction.employee))
        .filter(Employee.company_id == cid)
    )
    if search:
        q = q.filter(
            db.or_(
                EmployeeDeduction.title.ilike(f'%{search}%'),
                Employee.first_name.ilike(f'%{search}%'),
                Employee.last_name.ilike(f'%{search}%'),
                Employee.employee_number.ilike(f'%{search}%'),
            )
        )
    rows = q.order_by(EmployeeDeduction.created_at.desc()).all()
    return render_template('employees/deductions_index.html', rows=rows)


@employees_bp.route('/probation-dates')
@login_required
@permission_required('view_employees')
def probation_dates():
    """Probation end dates grouped by month for quick HR follow-up."""
    cid = require_company_id()
    today = date.today()
    selected_year = request.args.get('year', type=int) or today.year
    rows = (
        db.session.query(Employee)
        .filter(
            Employee.company_id == cid,
            Employee.status == 'active',
            Employee.probation_end_date.isnot(None),
        )
        .all()
    )
    month_groups = {month: [] for month in range(1, 13)}
    this_month_probation = 0
    this_week_probation = 0
    week_start = today
    week_end = today + timedelta(days=6)
    for emp in rows:
        end_date = emp.probation_end_date
        if end_date.year != selected_year:
            continue
        if selected_year == today.year and end_date.month == today.month:
            this_month_probation += 1
        if selected_year == today.year and week_start <= end_date <= week_end:
            this_week_probation += 1
        days_until = (end_date - today).days if selected_year == today.year else None
        month_groups[end_date.month].append(
            {
                'employee': emp,
                'probation_end_date': end_date,
                'weekday': end_date.strftime('%A'),
                'days_until': days_until,
                'coming_weekday_label': (
                    f"This coming {end_date.strftime('%A')}"
                    if selected_year == today.year and days_until is not None and 2 <= days_until <= 6
                    else None
                ),
                'status': (
                    'arrived'
                    if selected_year == today.year and end_date == today
                    else 'past'
                    if selected_year == today.year and end_date < today
                    else 'upcoming'
                ),
            }
        )
    for month in month_groups:
        month_groups[month].sort(key=lambda item: (item['probation_end_date'].day, item['employee'].full_name.lower()))
    year_choices = [selected_year - 1, selected_year, selected_year + 1]
    month_names = {month: calendar.month_name[month] for month in range(1, 13)}
    return render_template(
        'employees/probation_dates.html',
        selected_year=selected_year,
        current_year=today.year,
        this_month_probation=this_month_probation,
        this_week_probation=this_week_probation,
        month_groups=month_groups,
        year_choices=year_choices,
        month_names=month_names,
    )


@employees_bp.route('/contract-dates')
@login_required
@permission_required('view_employees')
def contract_dates():
    """Contract end dates grouped by month for quick HR follow-up."""
    cid = require_company_id()
    today = date.today()
    selected_year = request.args.get('year', type=int) or today.year
    rows = (
        db.session.query(Employee)
        .filter(
            Employee.company_id == cid,
            Employee.status == 'active',
            Employee.employment_type == 'contract',
            Employee.contract_end_date.isnot(None),
        )
        .all()
    )
    month_groups = {month: [] for month in range(1, 13)}
    this_month_contract = 0
    this_week_contract = 0
    week_start = today
    week_end = today + timedelta(days=6)
    for emp in rows:
        end_date = emp.contract_end_date
        if end_date.year != selected_year:
            continue
        if selected_year == today.year and end_date.month == today.month:
            this_month_contract += 1
        if selected_year == today.year and week_start <= end_date <= week_end:
            this_week_contract += 1
        days_until = (end_date - today).days if selected_year == today.year else None
        month_groups[end_date.month].append(
            {
                'employee': emp,
                'contract_end_date': end_date,
                'weekday': end_date.strftime('%A'),
                'days_until': days_until,
                'coming_weekday_label': (
                    f"This coming {end_date.strftime('%A')}"
                    if selected_year == today.year and days_until is not None and 2 <= days_until <= 6
                    else None
                ),
                'status': (
                    'arrived'
                    if selected_year == today.year and end_date == today
                    else 'past'
                    if selected_year == today.year and end_date < today
                    else 'upcoming'
                ),
            }
        )
    for month in month_groups:
        month_groups[month].sort(key=lambda item: (item['contract_end_date'].day, item['employee'].full_name.lower()))
    year_choices = [selected_year - 1, selected_year, selected_year + 1]
    month_names = {month: calendar.month_name[month] for month in range(1, 13)}
    return render_template(
        'employees/contract_dates.html',
        selected_year=selected_year,
        current_year=today.year,
        this_month_contract=this_month_contract,
        this_week_contract=this_week_contract,
        month_groups=month_groups,
        year_choices=year_choices,
        month_names=month_names,
    )


@employees_bp.route('/create', methods=['GET', 'POST'])
@login_required
@permission_required('create_employees')
def create():
    cid = require_company_id()
    form = EmployeeForm()
    form.department_id.choices = [('', '--')] + [
        (d.id, d.name) for d in db.session.query(Department).filter(Department.company_id == cid).order_by(Department.name).all()
    ]
    form.job_title_id.choices = [('', '--')] + [
        (j.id, j.name) for j in db.session.query(JobTitle).filter(JobTitle.company_id == cid).order_by(JobTitle.name).all()
    ]
    form.branch_id.choices = [
        (
            b.id,
            f'{b.name} ({b.country_code} · {currency_for_branch(b, app_default=current_app.config.get("DEFAULT_CURRENCY", "KES"))})',
        )
        for b in db.session.query(Branch).filter(Branch.company_id == cid).order_by(Branch.name).all()
    ]
    _populate_supervisor_choices(form, cid)
    _apply_default_branch_to_form(form, cid)
    if form.validate_on_submit():
        try:
            branch = db.session.get(Branch, form.branch_id.data) if form.branch_id.data else None
            if not branch or branch.company_id != cid:
                flash('Select a valid branch for this company.', 'danger')
                return render_template('employees/create.html', form=form)
            employee_number = _clean_employee_number(form.employee_number.data)
            if employee_number:
                existing_emp = (
                    db.session.query(Employee)
                    .filter(
                        Employee.company_id == cid,
                        Employee.branch_id == branch.id,
                        Employee.employee_number == employee_number,
                    )
                    .first()
                )
                if existing_emp:
                    flash('Employee number already exists in this branch. Use a different number.', 'danger')
                    return render_template('employees/create.html', form=form)
            emp = Employee(
                company_id=cid,
                branch_id=branch.id,
                employee_number=employee_number,
                first_name=form.first_name.data,
                last_name=form.last_name.data,
                middle_name=form.middle_name.data or None,
                date_of_birth=form.date_of_birth.data,
                gender=form.gender.data or None,
                marital_status=form.marital_status.data or None,
                nationality=form.nationality.data or None,
                national_id=form.national_id.data or None,
                passport_number=form.passport_number.data or None,
                kra_pin=form.kra_pin.data or None,
                nssf_number=form.nssf_number.data or None,
                nhif_number=form.nhif_number.data or None,
                email=form.email.data or None,
                secondary_email=form.secondary_email.data or None,
                phone=normalize_phone(form.phone.data, branch.country_code) if form.phone.data else None,
                secondary_phone=normalize_phone(form.secondary_phone.data, branch.country_code) if form.secondary_phone.data else None,
                phone_alt=normalize_phone(form.secondary_phone.data, branch.country_code) if form.secondary_phone.data else None,
                address=form.address.data or None,
                postal_address=form.postal_address.data or None,
                emergency_contact_name=form.emergency_contact_name.data or None,
                emergency_contact_phone=form.emergency_contact_phone.data or None,
                department_id=form.department_id.data or None,
                job_title_id=form.job_title_id.data or None,
                manager_id=None,
                status=form.status.data,
                employment_type=form.employment_type.data or None,
                hire_date=form.hire_date.data,
                probation_start_date=(
                    form.probation_start_date.data if form.employment_type.data == 'probation' else None
                ),
                probation_end_date=(
                    form.probation_end_date.data if form.employment_type.data == 'probation' else None
                ),
                confirmation_date=form.confirmation_date.data,
                contract_start_date=(
                    form.contract_start_date.data if form.employment_type.data == 'contract' else None
                ),
                contract_end_date=(
                    form.contract_end_date.data if form.employment_type.data == 'contract' else None
                ),
                prorate_payroll=True,
                bank_name=form.bank_name.data or None,
                bank_branch=form.bank_branch.data or None,
                bank_account_number=form.bank_account_number.data or None,
                bank_code=form.bank_code.data or None,
                swift_code=form.swift_code.data or None,
            )
            db.session.add(emp)
            db.session.flush()
            sync_employee_supervisors(emp, form.supervisor_ids.data, cid)
            sync_employee_next_of_kin(emp, request, branch.country_code)
            record_initial_assignment(emp, created_by_id=current_user.id)
            photo = request.files.get('photo')
            if photo and photo.filename:
                emp.photo_url = _save_employee_photo(photo, emp.id)
            db.session.commit()
            log_create('Employee', emp.id, model_to_audit_dict(emp), user_id=current_user.id, description='Employee created')
            flash('Employee created successfully.', 'success')
            return redirect(url_for('employees.view', id=emp.id))
        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Could not save employee: {str(e)}', 'danger')
    if request.method == 'POST' and form.errors:
        flash('Please fix the errors below.', 'danger')
    return render_template('employees/create.html', form=form)


@employees_bp.route('/<int:id>/history')
@login_required
def history(id):
    """Career history: assignment segments, salary, benefits — separate sections in UI."""
    emp = db.session.get(Employee, id)
    if not emp or emp.company_id != require_company_id():
        abort(404)
    if (current_user.employee_id or 0) != emp.id and not current_user.has_permission('view_employees'):
        abort(403)
    if backfill_assignment_history_if_missing(emp):
        db.session.commit()

    segments = (
        db.session.query(EmployeeAssignmentHistory)
        .options(
            joinedload(EmployeeAssignmentHistory.branch),
            joinedload(EmployeeAssignmentHistory.department),
            joinedload(EmployeeAssignmentHistory.job_title),
            joinedload(EmployeeAssignmentHistory.manager),
        )
        .filter(EmployeeAssignmentHistory.employee_id == id)
        .order_by(EmployeeAssignmentHistory.effective_from.desc(), EmployeeAssignmentHistory.id.desc())
        .all()
    )
    salary_records = (
        db.session.query(EmployeeSalary)
        .filter(EmployeeSalary.employee_id == id)
        .order_by(EmployeeSalary.effective_from.desc(), EmployeeSalary.id.desc())
        .all()
    )
    benefits = (
        db.session.query(EmployeeBenefit)
        .filter(EmployeeBenefit.employee_id == id)
        .order_by(
            EmployeeBenefit.payroll_year.desc().nullslast(),
            EmployeeBenefit.payroll_month.desc().nullslast(),
            EmployeeBenefit.id.desc(),
        )
        .all()
    )

    currency_code = currency_for_branch(
        emp.branch,
        app_default=current_app.config.get('DEFAULT_CURRENCY', 'KES'),
    ) if emp.branch else current_app.config.get('DEFAULT_CURRENCY', 'KES')

    return render_template(
        'employees/history.html',
        employee=emp,
        segments=segments,
        salary_records=salary_records,
        benefits=benefits,
        currency_code=currency_code,
    )


def _save_employee_self_contact(emp: Employee, user: User, form: EmployeeSelfContactForm) -> bool:
    """Apply validated self-service contact form to employee and user login email."""
    old = model_to_audit_dict(emp)
    user.email = (form.login_email.data or '').strip().lower()
    emp.email = (form.email.data or '').strip() or None
    emp.secondary_email = (form.secondary_email.data or '').strip() or None
    cc = emp.branch.country_code if emp.branch else None
    phone = normalize_phone(form.phone.data, cc) if form.phone.data else None
    secondary_phone = normalize_phone(form.secondary_phone.data, cc) if form.secondary_phone.data else None
    emp.phone = phone
    emp.secondary_phone = secondary_phone
    emp.phone_alt = secondary_phone
    emp.address = (form.address.data or '').strip() or None
    emp.postal_address = (form.postal_address.data or '').strip() or None
    emp.emergency_contact_name = (form.emergency_contact_name.data or '').strip() or None
    emp.emergency_contact_phone = (
        normalize_phone(form.emergency_contact_phone.data, cc)
        if form.emergency_contact_phone.data
        else None
    )
    try:
        db.session.commit()
        log_update(
            'Employee',
            emp.id,
            old,
            model_to_audit_dict(emp),
            user_id=current_user.id,
            description='Employee updated own contact details',
        )
        flash('Contact details and sign-in email saved.', 'success')
        return True
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('Profile contact update failed')
        flash(f'Could not save contact details: {exc}', 'danger')
        return False


@employees_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """Self-service profile for the logged-in user's linked employee record."""
    if not current_user.employee_id:
        flash('Your account is not linked to an employee record. Contact HR.', 'warning')
        from app.utils.navigation import redirect_to_user_home
        return redirect_to_user_home()
    emp = _employee_with_relations(current_user.employee_id)
    if not emp or not _can_view_employee(emp):
        abort(404)

    user = db.session.get(User, current_user.id)
    contact_form = EmployeeSelfContactForm(obj=emp, user_id=current_user.id)
    contact_form.login_email.data = (user.email if user else current_user.email) or ''
    open_contact_modal = False
    if request.method == 'POST' and request.form.get('form_name') == 'contact':
        contact_form = EmployeeSelfContactForm(user_id=current_user.id)
        if contact_form.validate_on_submit():
            if user and _save_employee_self_contact(emp, user, contact_form):
                return redirect(url_for('employees.profile', _anchor='contact'))
        open_contact_modal = True
        if contact_form.errors:
            for field, errors in contact_form.errors.items():
                for err in errors:
                    label = getattr(contact_form, field).label.text if hasattr(contact_form, field) else field
                    flash(f'{label}: {err}', 'danger')

    return render_template(
        'employees/profile.html',
        employee=emp,
        contact_form=contact_form,
        open_contact_modal=open_contact_modal,
    )


@employees_bp.route('/profile/photo', methods=['POST'])
@login_required
def profile_photo_upload():
    """Upload or replace profile/passport photo on own profile (stored in photo_url)."""
    if not current_user.employee_id:
        abort(403)
    emp = db.session.get(Employee, current_user.employee_id)
    if not emp or emp.company_id != require_company_id():
        abort(404)
    return _handle_employee_photo_upload(emp, redirect_url=url_for('employees.profile'))


@employees_bp.route('/<int:id>')
@login_required
def view(id):
    if (current_user.employee_id or 0) == id and not current_user.has_permission('view_employees'):
        return redirect(url_for('employees.profile'))
    emp = _employee_with_relations(id)
    if not emp or not _can_view_employee(emp):
        abort(404)
    employee_assets = []
    show_employee_assets = False
    if current_user.has_permission('view_assets'):
        from app.services.asset_service import employee_asset_rows, user_can_view_employee_assets
        cid = require_company_id()
        if user_can_view_employee_assets(current_user, emp, cid):
            show_employee_assets = True
            employee_assets = employee_asset_rows(emp.id, include_history=False)
    current_salary = None
    if current_user.has_permission('edit_employees') or current_user.has_permission('view_employees'):
        current_salary = (
            db.session.query(EmployeeSalary)
            .filter(EmployeeSalary.employee_id == emp.id)
            .order_by(EmployeeSalary.effective_from.desc(), EmployeeSalary.id.desc())
            .first()
        )
    currency_code = currency_for_branch(
        emp.branch,
        app_default=current_app.config.get('DEFAULT_CURRENCY', 'KES'),
    ) if emp.branch else current_app.config.get('DEFAULT_CURRENCY', 'KES')
    return render_template(
        'employees/view.html',
        employee=emp,
        today=date.today(),
        show_employee_assets=show_employee_assets,
        employee_assets=employee_assets,
        current_salary=current_salary,
        currency_code=currency_code,
    )


@employees_bp.route('/<int:id>/suspend', methods=['POST'])
@login_required
@permission_required('edit_employees')
def suspend_employee(id):
    emp = _get_employee_for_status_action(id)
    try:
        suspension_from = _parse_form_date('suspension_from', required=True)
        suspension_to = _parse_form_date('suspension_to')
        if suspension_to and suspension_to < suspension_from:
            flash('Suspension end date cannot be before the start date.', 'danger')
            return redirect(url_for('employees.view', id=id))
        old = model_to_audit_dict(emp)
        emp.status = 'suspended'
        emp.suspension_from_date = suspension_from
        emp.suspension_to_date = suspension_to
        emp.termination_date = None
        emp.termination_reason = None
        db.session.commit()
        log_update(
            'Employee',
            emp.id,
            old,
            model_to_audit_dict(emp),
            user_id=current_user.id,
            description='Employee suspended',
        )
        flash('Employee suspended.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    except Exception as exc:
        db.session.rollback()
        flash(f'Could not suspend employee: {exc}', 'danger')
    return redirect(url_for('employees.view', id=id))


@employees_bp.route('/<int:id>/terminate', methods=['POST'])
@login_required
@permission_required('edit_employees')
def terminate_employee(id):
    emp = _get_employee_for_status_action(id)
    try:
        termination_date = _parse_form_date('termination_date', required=True)
        termination_reason = (request.form.get('termination_reason') or '').strip() or None
        old = model_to_audit_dict(emp)
        emp.status = 'terminated'
        emp.termination_date = termination_date
        emp.termination_reason = termination_reason
        emp.suspension_from_date = None
        emp.suspension_to_date = None
        db.session.commit()
        log_update(
            'Employee',
            emp.id,
            old,
            model_to_audit_dict(emp),
            user_id=current_user.id,
            description='Employee terminated',
        )
        flash('Employee terminated.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    except Exception as exc:
        db.session.rollback()
        flash(f'Could not terminate employee: {exc}', 'danger')
    return redirect(url_for('employees.view', id=id))


@employees_bp.route('/<int:id>/reactivate', methods=['POST'])
@login_required
@permission_required('edit_employees')
def reactivate_employee(id):
    emp = _get_employee_for_status_action(id)
    if emp.status == 'active':
        flash('Employee is already active.', 'info')
        return redirect(url_for('employees.view', id=id))
    try:
        old = model_to_audit_dict(emp)
        emp.status = 'active'
        emp.suspension_from_date = None
        emp.suspension_to_date = None
        emp.termination_date = None
        emp.termination_reason = None
        db.session.commit()
        log_update(
            'Employee',
            emp.id,
            old,
            model_to_audit_dict(emp),
            user_id=current_user.id,
            description='Employee reactivated',
        )
        flash('Employee set back to active.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Could not reactivate employee: {exc}', 'danger')
    return redirect(url_for('employees.view', id=id))


@employees_bp.route('/<int:id>/photo')
@login_required
def photo(id):
    """Open employee photo from storage."""
    emp = db.session.get(Employee, id)
    if not emp or emp.company_id != require_company_id():
        abort(404)
    if not _can_view_employee(emp):
        abort(403)
    return _serve_employee_stored_image(emp.photo_url)


@employees_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('edit_employees')
def edit(id):
    cid = require_company_id()
    emp = db.session.get(Employee, id)
    if not emp or emp.company_id != cid:
        from flask import abort
        abort(404)
    form = EmployeeForm(obj=emp, employee_id=emp.id)
    form.branch_id.choices = [
        (
            b.id,
            f'{b.name} ({b.country_code} · {currency_for_branch(b, app_default=current_app.config.get("DEFAULT_CURRENCY", "KES"))})',
        )
        for b in db.session.query(Branch).filter(Branch.company_id == cid).order_by(Branch.name).all()
    ]
    form.department_id.choices = [('', '--')] + [
        (d.id, d.name) for d in db.session.query(Department).filter(Department.company_id == cid).order_by(Department.name).all()
    ]
    form.job_title_id.choices = [('', '--')] + [
        (j.id, j.name) for j in db.session.query(JobTitle).filter(JobTitle.company_id == cid).order_by(JobTitle.name).all()
    ]
    _populate_supervisor_choices(form, cid, exclude_employee_id=emp.id)
    if request.method == 'GET':
        form.supervisor_ids.data = employee_supervisor_ids(emp)
    _apply_default_branch_to_form(form, cid)
    if form.validate_on_submit():
        try:
            branch = db.session.get(Branch, form.branch_id.data)
            if not branch or branch.company_id != cid:
                flash('Select a valid branch for this company.', 'danger')
                return render_template('employees/edit.html', form=form, employee=emp, next_of_kin=emp.next_of_kin)
            before_assign = assignment_snapshot(emp)
            backfill_assignment_history_if_missing(emp)
            old = model_to_audit_dict(emp)
            employee_number = _clean_employee_number(form.employee_number.data)
            if employee_number:
                existing_emp = (
                    db.session.query(Employee)
                    .filter(
                        Employee.company_id == cid,
                        Employee.branch_id == branch.id,
                        Employee.employee_number == employee_number,
                        Employee.id != emp.id,
                    )
                    .first()
                )
                if existing_emp:
                    flash('Employee number already exists in this branch. Use a different number.', 'danger')
                    return render_template('employees/edit.html', form=form, employee=emp, next_of_kin=emp.next_of_kin)
            emp.employee_number = employee_number
            emp.branch_id = branch.id
            emp.first_name = form.first_name.data
            emp.last_name = form.last_name.data
            emp.middle_name = form.middle_name.data or None
            emp.date_of_birth = form.date_of_birth.data
            emp.gender = form.gender.data or None
            emp.marital_status = form.marital_status.data or None
            emp.nationality = form.nationality.data or None
            emp.national_id = form.national_id.data or None
            emp.passport_number = form.passport_number.data or None
            emp.kra_pin = form.kra_pin.data or None
            emp.nssf_number = form.nssf_number.data or None
            emp.nhif_number = form.nhif_number.data or None
            emp.email = form.email.data or None
            emp.secondary_email = form.secondary_email.data or None
            emp.phone = normalize_phone(form.phone.data, branch.country_code) if form.phone.data else None
            emp.secondary_phone = normalize_phone(form.secondary_phone.data, branch.country_code) if form.secondary_phone.data else None
            emp.phone_alt = normalize_phone(form.secondary_phone.data, branch.country_code) if form.secondary_phone.data else None
            emp.address = form.address.data or None
            emp.postal_address = form.postal_address.data or None
            emp.emergency_contact_name = form.emergency_contact_name.data or None
            emp.emergency_contact_phone = form.emergency_contact_phone.data or None
            emp.department_id = form.department_id.data or None
            emp.job_title_id = form.job_title_id.data or None
            sync_employee_supervisors(emp, form.supervisor_ids.data, cid)
            sync_employee_next_of_kin(emp, request, branch.country_code)
            emp.status = form.status.data
            emp.employment_type = form.employment_type.data or None
            emp.hire_date = form.hire_date.data
            if form.employment_type.data == 'probation':
                emp.probation_start_date = form.probation_start_date.data
                emp.probation_end_date = form.probation_end_date.data
            else:
                emp.probation_start_date = None
                emp.probation_end_date = None
            emp.confirmation_date = form.confirmation_date.data
            if form.employment_type.data == 'contract':
                emp.contract_start_date = form.contract_start_date.data
                emp.contract_end_date = form.contract_end_date.data
            else:
                emp.contract_start_date = None
                emp.contract_end_date = None
            emp.prorate_payroll = True
            emp.bank_name = form.bank_name.data or None
            emp.bank_branch = form.bank_branch.data or None
            emp.bank_account_number = form.bank_account_number.data or None
            emp.bank_code = form.bank_code.data or None
            emp.swift_code = form.swift_code.data or None
            photo = request.files.get('photo')
            if photo and photo.filename:
                emp.photo_url = _save_employee_photo(photo, emp.id, old_photo_path=emp.photo_url)
            assign_note = (request.form.get('assignment_change_reason') or '').strip() or None
            sync_assignment_history_after_edit(
                emp,
                before_assign,
                change_reason=assign_note,
                created_by_id=current_user.id,
            )
            db.session.commit()
            log_update('Employee', emp.id, old, model_to_audit_dict(emp), user_id=current_user.id, description='Employee updated')
            flash('Employee updated.', 'success')
            return redirect(url_for('employees.view', id=emp.id))
        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Could not update employee: {str(e)}', 'danger')
    return render_template(
        'employees/edit.html',
        form=form,
        employee=emp,
        next_of_kin=emp.next_of_kin,
    )


@employees_bp.route('/<int:id>/salary', methods=['GET', 'POST'])
@login_required
@permission_required('edit_employees')
def salary(id):
    from datetime import date
    emp = db.session.get(Employee, id)
    if not emp or emp.company_id != require_company_id():
        from flask import abort
        abort(404)
    form = EmployeeSalaryForm()
    salary_records = db.session.query(EmployeeSalary).filter(EmployeeSalary.employee_id == id).order_by(
        EmployeeSalary.effective_from.desc()).all()
    allowances = (
        db.session.query(Allowance).filter(Allowance.company_id == emp.company_id).order_by(Allowance.name).all()
    )
    employee_allowances = db.session.query(EmployeeAllowance).filter(EmployeeAllowance.employee_id == id).order_by(
        EmployeeAllowance.effective_from.desc()).all()
    branch_cc = (emp.branch.country_code if emp.branch else 'KE') or 'KE'
    currency_code = currency_for_branch(
        emp.branch,
        app_default=current_app.config.get('DEFAULT_CURRENCY', 'KES'),
    ) if emp.branch else current_app.config.get('DEFAULT_CURRENCY', 'KES')

    if request.method == 'POST':
        action = request.form.get('action', 'add_salary')
        payroll_on = bool(current_app.config.get('ENABLE_PAYROLL', False))
        if action == 'add_salary' and form.validate_on_submit():
            rec = EmployeeSalary(
                employee_id=id,
                effective_from=form.effective_from.data,
                basic_salary=form.basic_salary.data,
                house_allowance=0,
                transport_allowance=0,
                meal_allowance=0,
                other_allowances=0,
                pension_employee_percent=(form.pension_employee_percent.data or None) if payroll_on else None,
                pension_employee_fixed_amount=(form.pension_employee_fixed_amount.data or None) if payroll_on else None,
                pension_employer_percent=(form.pension_employer_percent.data or None) if payroll_on else None,
                notes=form.notes.data or None,
            )
            db.session.add(rec)
            db.session.commit()
            flash('Salary record added.', 'success')
            return redirect(url_for('employees.salary', id=id))
        if not payroll_on and action != 'add_salary':
            flash('Allowances and pension are available when payroll is enabled.', 'info')
            return redirect(url_for('employees.salary', id=id))
        if action == 'add_allowance':
            allowance_id = request.form.get('allowance_id', type=int)
            amount = request.form.get('amount', type=float)
            eff_from = request.form.get('effective_from')
            if allowance_id and amount is not None and amount >= 0 and eff_from:
                try:
                    from datetime import datetime
                    eff_date = datetime.strptime(eff_from, '%Y-%m-%d').date()
                except (ValueError, TypeError):
                    flash('Invalid effective date.', 'danger')
                else:
                    a = db.session.get(Allowance, allowance_id)
                    if a:
                        ea = EmployeeAllowance(
                            employee_id=id,
                            allowance_id=allowance_id,
                            amount=amount,
                            effective_from=eff_date,
                        )
                        db.session.add(ea)
                        db.session.commit()
                        flash(f'{a.name} allowance added.', 'success')
                    else:
                        flash('Allowance not found.', 'danger')
            else:
                flash('Select an allowance, amount and effective date.', 'danger')
            return redirect(url_for('employees.salary', id=id))
        if action == 'end_allowance':
            ea_id = request.form.get('employee_allowance_id', type=int)
            if ea_id:
                ea = db.session.query(EmployeeAllowance).filter(
                    EmployeeAllowance.id == ea_id,
                    EmployeeAllowance.employee_id == id,
                ).first()
                if ea and ea.effective_to is None:
                    ea.effective_to = date.today()
                    db.session.commit()
                    flash('Allowance ended.', 'success')
            return redirect(url_for('employees.salary', id=id))
        if action == 'delete_allowance':
            ea_id = request.form.get('employee_allowance_id', type=int)
            if ea_id:
                ea = db.session.query(EmployeeAllowance).filter(
                    EmployeeAllowance.id == ea_id,
                    EmployeeAllowance.employee_id == id,
                ).first()
                if ea:
                    db.session.delete(ea)
                    db.session.commit()
                    flash('Allowance deleted.', 'success')
            return redirect(url_for('employees.salary', id=id))

    return render_template(
        'employees/salary.html',
        employee=emp,
        branch_country_code=branch_cc.upper()[:2],
        currency_code=currency_code,
        form=form,
        salary_records=salary_records,
        allowances=allowances,
        employee_allowances=employee_allowances,
    )


@employees_bp.route('/<int:id>/salary/<int:salary_id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('edit_employees')
def salary_edit(id, salary_id):
    """Edit one salary history row for an employee."""
    emp = db.session.get(Employee, id)
    if not emp or emp.company_id != require_company_id():
        abort(404)
    rec = db.session.query(EmployeeSalary).filter(
        EmployeeSalary.id == salary_id,
        EmployeeSalary.employee_id == id,
    ).first()
    if not rec:
        abort(404)
    form = EmployeeSalaryForm(obj=rec)
    if form.validate_on_submit():
        rec.basic_salary = form.basic_salary.data
        rec.effective_from = form.effective_from.data
        if current_app.config.get('ENABLE_PAYROLL', False):
            rec.pension_employee_percent = form.pension_employee_percent.data or None
            rec.pension_employee_fixed_amount = form.pension_employee_fixed_amount.data or None
            rec.pension_employer_percent = form.pension_employer_percent.data or None
        rec.notes = form.notes.data or None
        db.session.commit()
        flash('Salary record updated.', 'success')
        return redirect(url_for('employees.salary', id=id))
    return render_template('employees/salary_edit.html', employee=emp, salary_record=rec, form=form)


@employees_bp.route('/<int:id>/salary/<int:salary_id>/delete', methods=['POST'])
@login_required
@permission_required('edit_employees')
def salary_delete(id, salary_id):
    """Delete one salary history row for an employee."""
    emp = db.session.get(Employee, id)
    if not emp or emp.company_id != require_company_id():
        abort(404)
    rec = db.session.query(EmployeeSalary).filter(
        EmployeeSalary.id == salary_id,
        EmployeeSalary.employee_id == id,
    ).first()
    if not rec:
        abort(404)
    db.session.delete(rec)
    db.session.commit()
    flash('Salary record deleted.', 'success')
    return redirect(url_for('employees.salary', id=id))


@employees_bp.route('/<int:id>/deductions', methods=['GET', 'POST'])
@login_required
@permission_required('edit_employees')
@require_payroll
def employee_deductions(id):
    """Recurring / loan-style deductions for payroll (applied every month while active)."""
    from datetime import datetime
    from decimal import Decimal as Dec

    emp = db.session.get(Employee, id)
    if not emp or emp.company_id != require_company_id():
        from flask import abort
        abort(404)
    assignments = (
        db.session.query(EmployeeDeduction)
        .filter(EmployeeDeduction.employee_id == id)
        .order_by(EmployeeDeduction.created_at.desc())
        .all()
    )
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            title = (request.form.get('title') or '').strip()
            mode = (request.form.get('calculation_mode') or 'fixed').strip()
            eff_from_s = request.form.get('effective_from')
            eff_to_s = (request.form.get('effective_to') or '').strip() or None
            amount = request.form.get('amount', type=float)
            rate = request.form.get('rate_percent', type=float)
            bal_s = (request.form.get('remaining_balance') or '').strip() or None
            notes = (request.form.get('notes') or '').strip() or None
            if title and eff_from_s:
                try:
                    eff_from = datetime.strptime(eff_from_s, '%Y-%m-%d').date()
                except ValueError:
                    flash('Invalid effective from date.', 'danger')
                    return redirect(url_for('employees.employee_deductions', id=id))
                eff_to = None
                if eff_to_s:
                    try:
                        eff_to = datetime.strptime(eff_to_s, '%Y-%m-%d').date()
                    except ValueError:
                        flash('Invalid effective to date.', 'danger')
                        return redirect(url_for('employees.employee_deductions', id=id))
                db.session.add(
                    EmployeeDeduction(
                        employee_id=id,
                        deduction_id=None,
                        title=title[:200],
                        calculation_mode=mode,
                        amount=Dec(str(amount or 0)),
                        rate_percent=Dec(str(rate)) if rate is not None else None,
                        effective_from=eff_from,
                        effective_to=eff_to,
                        remaining_balance=Dec(str(bal_s)) if bal_s else None,
                        notes=notes,
                        is_active=True,
                    )
                )
                db.session.commit()
                flash('Deduction added.', 'success')
            else:
                flash('Enter a title / description and effective from date.', 'danger')
        elif action == 'delete':
            aid = request.form.get('assignment_id', type=int)
            if aid:
                row = (
                    db.session.query(EmployeeDeduction)
                    .filter(EmployeeDeduction.id == aid, EmployeeDeduction.employee_id == id)
                    .first()
                )
                if row:
                    db.session.delete(row)
                    db.session.commit()
                    flash('Deduction removed.', 'success')
        elif action == 'stop':
            from calendar import monthrange
            aid = request.form.get('assignment_id', type=int)
            last_year = request.form.get('last_payroll_year', type=int)
            last_month = request.form.get('last_payroll_month', type=int)
            if not aid:
                flash('Deduction not found.', 'danger')
                return redirect(url_for('employees.employee_deductions', id=id))
            row = (
                db.session.query(EmployeeDeduction)
                .filter(EmployeeDeduction.id == aid, EmployeeDeduction.employee_id == id)
                .first()
            )
            if not row:
                flash('Deduction not found.', 'danger')
            elif not last_year or not (2000 <= last_year <= 2100) or not last_month or not (1 <= last_month <= 12):
                flash('Enter a valid last payroll month and year.', 'danger')
            else:
                last_day = monthrange(last_year, last_month)[1]
                end_date = date(last_year, last_month, last_day)
                if row.effective_from and end_date < row.effective_from:
                    flash('Last payroll month cannot be before deduction effective-from date.', 'danger')
                else:
                    row.effective_to = end_date
                    db.session.commit()
                    flash(f'Deduction will stop after payroll {last_year}-{last_month:02d}.', 'success')
        return redirect(url_for('employees.employee_deductions', id=id))
    from app.utils.currency import currency_for_employee

    return render_template(
        'employees/deductions.html',
        employee=emp,
        assignments=assignments,
        currency_code=currency_for_employee(emp),
    )


@employees_bp.route('/deductions/welfare-bulk', methods=['GET', 'POST'])
@login_required
@permission_required('edit_employees')
@require_payroll
def welfare_bulk():
    """Bulk set welfare-kit recurring deduction amounts for many employees at once."""
    from datetime import datetime
    from decimal import Decimal as Dec

    cid = require_company_id()
    employees = (
        db.session.query(Employee)
        .filter(Employee.company_id == cid, Employee.status == 'active')
        .order_by(Employee.last_name, Employee.first_name)
        .all()
    )
    emp_ids = [e.id for e in employees]
    existing_rows = []
    if emp_ids:
        existing_rows = (
            db.session.query(EmployeeDeduction)
            .filter(
                EmployeeDeduction.employee_id.in_(emp_ids),
                EmployeeDeduction.is_active.is_(True),
                EmployeeDeduction.effective_to.is_(None),
                EmployeeDeduction.title == 'Welfare Kit',
            )
            .order_by(EmployeeDeduction.effective_from.desc(), EmployeeDeduction.id.desc())
            .all()
        )
    current_by_emp = {}
    for r in existing_rows:
        current_by_emp.setdefault(r.employee_id, r)

    if request.method == 'POST':
        effective_from_s = (request.form.get('effective_from') or '').strip()
        if not effective_from_s:
            flash('Effective from date is required.', 'danger')
            return redirect(url_for('employees.welfare_bulk'))
        try:
            effective_from = datetime.strptime(effective_from_s, '%Y-%m-%d').date()
        except ValueError:
            flash('Invalid effective from date.', 'danger')
            return redirect(url_for('employees.welfare_bulk'))

        updated = 0
        for emp in employees:
            amt_raw = (request.form.get(f'amount_{emp.id}') or '').strip()
            try:
                amount = Dec(str(amt_raw or '0'))
            except Exception:
                continue
            current = current_by_emp.get(emp.id)
            if amount <= 0:
                if current:
                    current.is_active = False
                    current.effective_to = effective_from - timedelta(days=1)
                    updated += 1
                continue

            if current and current.effective_from == effective_from:
                current.amount = amount
                current.calculation_mode = 'fixed'
                current.notes = 'Bulk welfare kit setup'
                updated += 1
            else:
                if current:
                    current.effective_to = effective_from - timedelta(days=1)
                db.session.add(
                    EmployeeDeduction(
                        employee_id=emp.id,
                        deduction_id=None,
                        title='Welfare Kit',
                        calculation_mode='fixed',
                        amount=amount,
                        rate_percent=None,
                        effective_from=effective_from,
                        effective_to=None,
                        remaining_balance=None,
                        notes='Bulk welfare kit setup',
                        is_active=True,
                    )
                )
                updated += 1

        db.session.commit()
        flash(f'Welfare kit amounts saved for {updated} employee(s).', 'success')
        return redirect(url_for('employees.welfare_bulk'))

    return render_template(
        'employees/welfare_bulk.html',
        employees=employees,
        current_by_emp=current_by_emp,
        today=date.today(),
    )


def _benefit_form_bool(field_name: str, *, default: bool = True) -> bool:
    return request.form.get(field_name, '1' if default else '0') in {'1', 'true', 'on', 'yes'}


@employees_bp.route('/<int:id>/benefits', methods=['GET', 'POST'])
@login_required
@permission_required('edit_employees')
@require_payroll
def employee_benefits(id):
    """Simple benefits that post directly into a selected payroll month."""
    from decimal import Decimal as Dec

    emp = db.session.get(Employee, id)
    if not emp or emp.company_id != require_company_id():
        abort(404)
    assignments = (
        db.session.query(EmployeeBenefit)
        .filter(EmployeeBenefit.employee_id == id)
        .order_by(EmployeeBenefit.created_at.desc())
        .all()
    )

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            title = (request.form.get('title') or '').strip()
            amount = request.form.get('amount', type=float)
            payroll_year = request.form.get('payroll_year', type=int)
            payroll_month = request.form.get('payroll_month', type=int)
            frequency = (request.form.get('frequency') or 'one_off').strip().lower()
            notes = (request.form.get('notes') or '').strip() or None
            if frequency not in {'one_off', 'monthly'}:
                frequency = 'one_off'
            if (
                title
                and amount is not None
                and payroll_year and 2000 <= payroll_year <= 2100
                and payroll_month and 1 <= payroll_month <= 12
            ):
                is_taxable = _benefit_form_bool('is_taxable', default=True)
                is_pensionable = _benefit_form_bool('is_pensionable', default=True) if is_taxable else False
                db.session.add(
                    EmployeeBenefit(
                        employee_id=id,
                        title=title[:200],
                        amount=Dec(str(amount)),
                        frequency=frequency,
                        effective_date=date(payroll_year, payroll_month, 1),
                        payroll_year=payroll_year,
                        payroll_month=payroll_month,
                        notes=notes,
                        is_taxable=is_taxable,
                        is_pensionable=is_pensionable,
                        is_active=True,
                    )
                )
                db.session.commit()
                if frequency == 'monthly':
                    flash('Recurring benefit added. It will be included every month from the selected payroll period.', 'success')
                else:
                    flash('One-off benefit added for the selected payroll month.', 'success')
            else:
                flash('Enter title, amount and a valid payroll month/year.', 'danger')
        elif action == 'edit':
            aid = request.form.get('assignment_id', type=int)
            title = (request.form.get('title') or '').strip()
            amount = request.form.get('amount', type=float)
            payroll_year = request.form.get('payroll_year', type=int)
            payroll_month = request.form.get('payroll_month', type=int)
            frequency = (request.form.get('frequency') or 'one_off').strip().lower()
            notes = (request.form.get('notes') or '').strip() or None
            if frequency not in {'one_off', 'monthly'}:
                frequency = 'one_off'
            row = None
            if aid:
                row = (
                    db.session.query(EmployeeBenefit)
                    .filter(EmployeeBenefit.id == aid, EmployeeBenefit.employee_id == id)
                    .first()
                )
            if not row:
                flash('Benefit not found.', 'danger')
            elif not (
                title
                and amount is not None
                and payroll_year and 2000 <= payroll_year <= 2100
                and payroll_month and 1 <= payroll_month <= 12
            ):
                flash('Enter title, amount and a valid payroll month/year.', 'danger')
            else:
                is_taxable = _benefit_form_bool('is_taxable', default=bool(getattr(row, 'is_taxable', True)))
                is_pensionable = (
                    _benefit_form_bool('is_pensionable', default=bool(getattr(row, 'is_pensionable', True)))
                    if is_taxable
                    else False
                )
                row.title = title[:200]
                row.amount = Dec(str(amount))
                row.frequency = frequency
                row.payroll_year = payroll_year
                row.payroll_month = payroll_month
                row.effective_date = date(payroll_year, payroll_month, 1)
                row.notes = notes
                row.is_taxable = is_taxable
                row.is_pensionable = is_pensionable
                db.session.commit()
                flash('Benefit updated.', 'success')
        elif action == 'delete':
            aid = request.form.get('assignment_id', type=int)
            if aid:
                row = (
                    db.session.query(EmployeeBenefit)
                    .filter(EmployeeBenefit.id == aid, EmployeeBenefit.employee_id == id)
                    .first()
                )
                if row:
                    db.session.delete(row)
                    db.session.commit()
                    flash('Benefit removed.', 'success')
        return redirect(url_for('employees.employee_benefits', id=id))
    from app.utils.currency import currency_for_employee

    return render_template(
        'employees/benefits.html',
        employee=emp,
        assignments=assignments,
        today=date.today(),
        currency_code=currency_for_employee(emp),
    )


@employees_bp.route('/<int:id>/link-user', methods=['GET', 'POST'])
@login_required
@permission_required('edit_employees')
def link_user(id):
    emp = db.session.get(Employee, id)
    if not emp or emp.company_id != require_company_id():
        from flask import abort
        abort(404)
    if emp.user:
        flash('This employee already has a linked login account.', 'info')
        return redirect(url_for('employees.view', id=id))
    employee_role = db.session.query(Role).filter_by(code='EMPLOYEE').first()
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        if not email:
            flash('Email is required.', 'danger')
            return render_template('employees/link_user.html', employee=emp)
        if not password or len(password) < current_app.config.get('PASSWORD_MIN_LENGTH', 8):
            flash(f'Password must be at least {current_app.config.get("PASSWORD_MIN_LENGTH", 8)} characters.', 'danger')
            return render_template('employees/link_user.html', employee=emp)
        if db.session.query(User).filter_by(email=email).first():
            flash('A user with this email already exists.', 'danger')
            return render_template('employees/link_user.html', employee=emp)
        must_change = request.form.get('must_change_password', '1') == '1'
        user = User(
            email=email,
            employee_id=emp.id,
            company_id=emp.company_id,
            is_active=True,
            must_change_password=must_change,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        if employee_role:
            db.session.add(UserRole(user_id=user.id, role_id=employee_role.id))
        db.session.commit()
        from app.services.employee_welcome_email_service import send_employee_welcome_email

        if send_employee_welcome_email(user, emp, password, must_change_password=must_change):
            flash('Login account created and linked. A welcome email with sign-in details was sent.', 'success')
        else:
            flash(
                'Login account created and linked. Welcome email could not be sent — check Brevo configuration.',
                'warning',
            )
        return redirect(url_for('employees.view', id=id))
    return render_template('employees/link_user.html', employee=emp)


@employees_bp.route('/provision-login-accounts', methods=['GET', 'POST'])
@login_required
@permission_required('edit_employees')
def provision_login_accounts():
    """Bulk-create login accounts for employees without one (shared initial password)."""
    from app.services.employee_account_service import (
        bulk_provision_employee_logins,
        preview_bulk_provision,
        send_bulk_welcome_emails,
    )
    from app.services.audit_service import log_audit

    cid = require_company_id()
    min_len = current_app.config.get('PASSWORD_MIN_LENGTH', 8)
    default_password = 'nexgen2026'
    statuses = ('active',)
    preview = preview_bulk_provision(cid, statuses=statuses)

    if request.method == 'POST':
        password = (request.form.get('password') or '').strip()
        confirm = (request.form.get('confirm_password') or '').strip()
        if not password or len(password) < min_len:
            flash(f'Password must be at least {min_len} characters.', 'danger')
            return render_template(
                'employees/provision_login_accounts.html',
                preview=preview,
                default_password=default_password,
                min_len=min_len,
            )
        if password != confirm:
            flash('Password and confirmation do not match.', 'danger')
            return render_template(
                'employees/provision_login_accounts.html',
                preview=preview,
                default_password=default_password,
                min_len=min_len,
            )
        must_change = request.form.get('must_change_password', '1') == '1'
        result = bulk_provision_employee_logins(
            cid,
            password,
            statuses=statuses,
            must_change_password=must_change,
        )
        emails_sent = 0
        if result.created:
            db.session.commit()
            emails_sent = send_bulk_welcome_emails(result)
            log_audit(
                'CREATE',
                record_type='User',
                record_id=None,
                user_id=current_user.id,
                description=f'Bulk provisioned {result.created} employee login account(s)',
                new_values={'created': result.created, 'must_change_password': must_change},
            )
        else:
            db.session.rollback()
        msg = f'Created {result.created} login account(s).'
        if result.created:
            msg += f' Welcome emails sent to {emails_sent}.'
            if emails_sent < result.created:
                flash(
                    'Some welcome emails could not be sent — verify Brevo is configured.',
                    'warning',
                )
        if result.skipped_has_account:
            msg += f' Skipped {result.skipped_has_account} already linked.'
        if result.errors:
            msg += f' {len(result.errors)} error(s).'
            for err in result.errors[:5]:
                flash(err, 'warning')
        flash(msg, 'success' if result.created else 'info')
        return redirect(url_for('employees.list'))

    return render_template(
        'employees/provision_login_accounts.html',
        preview=preview,
        default_password=default_password,
        min_len=min_len,
    )


def _allowed_file(filename):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return ext in current_app.config.get('ALLOWED_EXTENSIONS', {'pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png'})


def _allowed_image_file(filename):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return ext in {'jpg', 'jpeg', 'png'}


def _serve_employee_stored_image(rel_path: str | None):
    """Stream or redirect to a stored employee image (photo, passport scan, etc.)."""
    ref = (rel_path or '').replace('\\', '/').lstrip('/').strip()
    if not ref:
        abort(404)
    if ref.startswith('cld::'):
        parts = ref.split('::', 2)
        if len(parts) != 3 or not cloudinary_url:
            abort(404)
        _prefix, resource_type, public_id = parts
        file_url, _ = cloudinary_url(
            public_id,
            resource_type=resource_type or 'image',
            secure=True,
        )
        return redirect(file_url)
    upload_root = os.path.abspath(current_app.config['UPLOAD_FOLDER'])
    full_path = os.path.abspath(os.path.join(upload_root, ref))
    if not full_path.startswith(upload_root + os.sep):
        abort(403)
    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        abort(404)
    mime, _ = mimetypes.guess_type(full_path)
    return send_file(
        full_path,
        mimetype=mime or 'application/octet-stream',
        as_attachment=False,
        download_name=os.path.basename(full_path),
    )


def _handle_employee_photo_upload(emp: Employee, redirect_url: str):
    """Save uploaded image to employee.photo_url (profile photo or passport scan)."""
    photo_file = request.files.get('photo')
    if not photo_file or not photo_file.filename:
        flash('Please choose an image (JPG or PNG).', 'danger')
        return redirect(redirect_url)
    try:
        emp.photo_url = _save_employee_photo(photo_file, emp.id, old_photo_path=emp.photo_url)
        db.session.commit()
        flash('Photo saved.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('Employee photo upload failed')
        flash(f'Could not save photo: {exc}', 'danger')
    return redirect(redirect_url)


def _cloudinary_upload_employee_image(
    file_storage,
    employee_id: int,
    *,
    folder_config_key: str,
    default_folder: str,
    public_id_prefix: str,
) -> str:
    """Upload employee image to Cloudinary and return cld reference."""
    _configure_cloudinary()
    original = secure_filename(file_storage.filename or 'image')
    upload_res = cloudinary.uploader.upload(
        file_storage,
        resource_type='image',
        folder=current_app.config.get(folder_config_key, default_folder),
        public_id=f"{public_id_prefix}_{employee_id}_{os.urandom(4).hex()}_{os.path.splitext(original)[0]}",
        overwrite=False,
        use_filename=False,
    )
    public_id = upload_res.get('public_id')
    if not public_id:
        raise ValueError('Cloudinary upload did not return a public_id.')
    return f"cld::image::{public_id}"


def _cloudinary_upload_employee_photo(file_storage, employee_id: int) -> str:
    return _cloudinary_upload_employee_image(
        file_storage,
        employee_id,
        folder_config_key='CLOUDINARY_PHOTOS_FOLDER',
        default_folder='hrms/employee_photos',
        public_id_prefix='employee',
    )


def _delete_employee_stored_image(stored_path: str | None):
    """Delete stored employee image from Cloudinary or local storage."""
    if not stored_path:
        return
    ref = stored_path.replace('\\', '/').lstrip('/').strip()
    if not ref:
        return
    if ref.startswith('cld::'):
        parts = ref.split('::', 2)
        if len(parts) == 3 and cloudinary:
            _prefix, resource_type, public_id = parts
            try:
                _configure_cloudinary()
                cloudinary.uploader.destroy(public_id, resource_type=resource_type or 'image', invalidate=True)
            except Exception:
                current_app.logger.warning('Could not delete old cloud employee image: %s', public_id)
        return
    upload_root = os.path.abspath(current_app.config['UPLOAD_FOLDER'])
    old_full = os.path.abspath(os.path.join(upload_root, ref))
    if old_full.startswith(upload_root + os.sep) and os.path.exists(old_full) and os.path.isfile(old_full):
        try:
            os.remove(old_full)
        except OSError:
            current_app.logger.warning('Could not delete old employee image: %s', old_full)


def _delete_employee_photo(stored_path: str | None):
    _delete_employee_stored_image(stored_path)


def _save_employee_image(
    file_storage,
    employee_id: int,
    *,
    local_subdir: str,
    cloud_upload_fn,
    old_image_path: str | None = None,
    invalid_type_message: str = 'Image type not allowed. Use JPG or PNG.',
) -> str:
    """Store employee image and return Cloudinary ref or relative local path."""
    if not file_storage or not file_storage.filename:
        return old_image_path or ''
    if not _allowed_image_file(file_storage.filename):
        raise ValueError(invalid_type_message)
    stored_path = ''
    if _cloudinary_enabled():
        try:
            stored_path = cloud_upload_fn(file_storage, employee_id)
        except Exception:
            current_app.logger.exception('Cloudinary image upload failed; falling back to local storage.')
            try:
                file_storage.stream.seek(0)
            except Exception:
                pass
    if not stored_path:
        upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], local_subdir, str(employee_id))
        os.makedirs(upload_dir, exist_ok=True)
        filename = secure_filename(file_storage.filename)
        base, ext = os.path.splitext(filename)
        unique = f"{base}_{os.urandom(4).hex()}{ext.lower()}"
        stored_path = os.path.join(local_subdir, str(employee_id), unique).replace('\\', '/')
        full_path = os.path.join(current_app.config['UPLOAD_FOLDER'], stored_path)
        file_storage.save(full_path)

    if old_image_path and old_image_path != stored_path:
        _delete_employee_stored_image(old_image_path)
    return stored_path


def _save_employee_photo(file_storage, employee_id: int, old_photo_path: str | None = None) -> str:
    return _save_employee_image(
        file_storage,
        employee_id,
        local_subdir='employee_photos',
        cloud_upload_fn=_cloudinary_upload_employee_photo,
        old_image_path=old_photo_path,
        invalid_type_message='Photo type not allowed. Use JPG or PNG.',
    )


def _can_access_employee_documents(employee_id: int) -> bool:
    """HR can access any docs; employees can access their own."""
    if current_user.has_permission('edit_employees'):
        return True
    return bool(current_user.employee_id and int(current_user.employee_id) == int(employee_id))


def _cloudinary_enabled() -> bool:
    return bool(
        cloudinary
        and current_app.config.get('CLOUDINARY_CLOUD_NAME')
        and current_app.config.get('CLOUDINARY_API_KEY')
        and current_app.config.get('CLOUDINARY_API_SECRET')
    )


def _configure_cloudinary():
    if not _cloudinary_enabled():
        return
    cloudinary.config(
        cloud_name=current_app.config.get('CLOUDINARY_CLOUD_NAME'),
        api_key=current_app.config.get('CLOUDINARY_API_KEY'),
        api_secret=current_app.config.get('CLOUDINARY_API_SECRET'),
        secure=True,
    )


def _cloudinary_upload_employee_doc(file_storage, employee_id: int) -> tuple[str, int]:
    """
    Upload document to Cloudinary and return (stored_reference, size_bytes).
    stored_reference format: cld::<resource_type>::<public_id>
    """
    _configure_cloudinary()
    original = secure_filename(file_storage.filename or 'document')
    upload_res = cloudinary.uploader.upload(
        file_storage,
        resource_type='auto',
        folder=current_app.config.get('CLOUDINARY_DOCS_FOLDER', 'hrms/employee_docs'),
        public_id=f"employee_{employee_id}_{os.urandom(4).hex()}_{os.path.splitext(original)[0]}",
        overwrite=False,
        use_filename=False,
    )
    public_id = upload_res.get('public_id')
    resource_type = upload_res.get('resource_type', 'raw')
    size_bytes = int(upload_res.get('bytes') or 0)
    if not public_id:
        raise ValueError('Cloudinary upload did not return a public_id.')
    return f"cld::{resource_type}::{public_id}", size_bytes


@employees_bp.route('/<int:id>/documents', methods=['GET'])
@login_required
def documents(id):
    emp = db.session.get(Employee, id)
    if not emp or emp.company_id != require_company_id():
        abort(404)
    if not _can_access_employee_documents(id):
        abort(403)
    categories = ensure_standard_document_categories(emp.company_id)
    grouped = documents_grouped_by_category(id, categories)
    max_mb = max(1, int(current_app.config.get('EMPLOYEE_DOCUMENT_MAX_BYTES', 25 * 1024 * 1024)) // (1024 * 1024))
    return render_template(
        'employees/documents.html',
        employee=emp,
        categories=categories,
        grouped_documents=grouped,
        max_upload_mb=max_mb,
    )


@employees_bp.route('/<int:id>/documents/upload', methods=['POST'])
@login_required
def document_upload(id):
    emp = db.session.get(Employee, id)
    if not emp or emp.company_id != require_company_id():
        return jsonify(status='error', message='Employee not found.'), 404
    if not current_user.has_permission('edit_employees'):
        return jsonify(status='error', message='Permission denied.'), 403

    category_code = (request.form.get('category_code') or '').strip().upper()
    category = get_category_by_code(emp.company_id, category_code)
    if not category:
        return jsonify(status='error', message='Invalid document category.'), 400

    f = request.files.get('file')
    notes = (request.form.get('notes') or '').strip() or None
    name = (request.form.get('name') or '').strip() or None
    original_name = f.filename if f and f.filename else 'file'

    try:
        doc = save_employee_document(emp, category, f, name=name, notes=notes)
        log_create(
            'EmployeeDocument',
            doc.id,
            model_to_audit_dict(doc),
            user_id=current_user.id,
            description=f'Document uploaded for employee {emp.id}',
        )
        return jsonify(
            status='ok',
            message='Uploaded.',
            document={
                'id': doc.id,
                'name': doc.display_filename,
                'original_filename': doc.original_filename or doc.display_filename,
                'extension': doc.file_extension,
                'file_size': doc.file_size,
                'created_at': doc.created_at.strftime('%d %b %Y') if doc.created_at else '',
                'open_url': url_for('employees.document_open', id=id, doc_id=doc.id),
                'download_url': url_for('employees.document_open', id=id, doc_id=doc.id, download=1),
            },
        )
    except ValueError as e:
        return jsonify(status='error', message=str(e), filename=original_name), 400
    except PermissionError as e:
        current_app.logger.exception('Document upload permission error for employee %s', id)
        return jsonify(
            status='error',
            message=str(e) or 'Storage folder is not writable. Contact your administrator.',
            filename=original_name,
        ), 500
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Document upload failed for employee %s', id)
        return jsonify(status='error', message=f'Upload failed: {e}', filename=original_name), 500


@employees_bp.route('/<int:id>/documents/<int:doc_id>/delete', methods=['POST'])
@login_required
@permission_required('edit_employees')
def document_delete(id, doc_id):
    emp = db.session.get(Employee, id)
    if not emp or emp.company_id != require_company_id():
        abort(404)
    doc = db.session.get(EmployeeDocument, doc_id)
    if not doc or doc.employee_id != id:
        abort(404)
    old = model_to_audit_dict(doc)
    delete_employee_document(doc)
    log_delete(
        'EmployeeDocument',
        doc_id,
        old,
        user_id=current_user.id,
        description=f'Document deleted for employee {id}',
    )
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(status='ok', message='Document deleted.')
    flash('Document deleted.', 'success')
    return redirect(url_for('employees.documents', id=id))


@employees_bp.route('/<int:id>/documents/<int:doc_id>/open')
@login_required
def document_open(id, doc_id):
    """Open/download employee document."""
    emp = db.session.get(Employee, id)
    if not emp or emp.company_id != require_company_id():
        abort(404)
    if not _can_access_employee_documents(id):
        abort(403)
    doc = db.session.get(EmployeeDocument, doc_id)
    if not doc or doc.employee_id != id:
        abort(404)
    rel_path = (doc.file_path or '').replace('\\', '/').lstrip('/').strip()
    if not rel_path:
        abort(404)
    # Cloudinary-backed reference (legacy)
    if rel_path.startswith('cld::'):
        parts = rel_path.split('::', 2)
        if len(parts) != 3 or not cloudinary_url:
            abort(404)
        _prefix, resource_type, public_id = parts
        flags = 'attachment' if request.args.get('download') in {'1', 'true', 'yes'} else None
        file_url, _ = cloudinary_url(
            public_id,
            resource_type=resource_type or 'raw',
            secure=True,
            flags=flags,
        )
        return redirect(file_url)
    if rel_path.startswith('http://') or rel_path.startswith('https://'):
        return redirect(rel_path)

    full_path = resolve_document_full_path(doc)
    if not full_path:
        flash('Document file is missing from storage.', 'danger')
        return redirect(url_for('employees.documents', id=id))

    download = request.args.get('download') in {'1', 'true', 'yes'}
    mime, _ = mimetypes.guess_type(full_path)
    return send_file(
        full_path,
        mimetype=mime or 'application/octet-stream',
        as_attachment=download,
        download_name=document_download_filename(doc),
    )
