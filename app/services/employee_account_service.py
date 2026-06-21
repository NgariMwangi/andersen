"""Create and bulk-provision login accounts linked to employees."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.extensions import db
from app.models.employee import Employee
from app.models.user import Role, User, UserRole


def _email_taken(email: str, *, exclude_user_id: int | None = None) -> bool:
    q = db.session.query(User.id).filter(db.func.lower(User.email) == email.lower())
    if exclude_user_id:
        q = q.filter(User.id != exclude_user_id)
    return q.first() is not None


def _sanitize_local_part(value: str) -> str:
    s = (value or '').strip().lower()
    s = re.sub(r'[^a-z0-9._-]+', '', s.replace(' ', '.'))
    return (s[:64] or 'user').strip('.')


def suggest_login_email(employee: Employee) -> str:
    """Pick a unique login email for an employee (work email or generated)."""
    existing_user_id = employee.user.id if getattr(employee, 'user', None) else None
    for raw in (employee.email, employee.secondary_email):
        if raw and '@' in raw:
            email = raw.strip().lower()
            if not _email_taken(email, exclude_user_id=existing_user_id):
                return email
    base = _sanitize_local_part(employee.employee_number) or f'emp{employee.id}'
    domain = f'company{employee.company_id}.hrms.local'
    candidate = f'{base}@{domain}'
    if not _email_taken(candidate, exclude_user_id=existing_user_id):
        return candidate
    n = 2
    while n < 10_000:
        alt = f'{base}{n}@{domain}'
        if not _email_taken(alt, exclude_user_id=existing_user_id):
            return alt
        n += 1
    return f'emp{employee.id}@{domain}'


def _employee_role() -> Role | None:
    return db.session.query(Role).filter_by(code='EMPLOYEE').first()


@dataclass
class ProvisionResult:
    created: int = 0
    skipped_has_account: int = 0
    skipped_no_email: int = 0
    errors: list[str] = field(default_factory=list)
    created_emails: list[str] = field(default_factory=list)


def _employee_has_user(employee: Employee) -> bool:
    if getattr(employee, 'user', None):
        return True
    return db.session.query(User.id).filter_by(employee_id=employee.id).first() is not None


def provision_employee_login(
    employee: Employee,
    password: str,
    *,
    role_code: str = 'EMPLOYEE',
    must_change_password: bool = True,
    email: str | None = None,
) -> User:
    """Create a user linked to employee, or raise ValueError."""
    if _employee_has_user(employee):
        raise ValueError(f'{employee.full_name} already has a login account.')
    login_email = (email or suggest_login_email(employee)).strip().lower()
    if not login_email or '@' not in login_email:
        raise ValueError(f'Could not determine login email for {employee.full_name}.')
    if _email_taken(login_email):
        raise ValueError(f'Email {login_email} is already in use.')

    user = User(
        email=login_email,
        employee_id=employee.id,
        company_id=employee.company_id,
        is_active=True,
        must_change_password=must_change_password,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.flush()

    role = db.session.query(Role).filter_by(code=role_code).first() or _employee_role()
    if role:
        db.session.add(UserRole(user_id=user.id, role_id=role.id))
    return user


@dataclass
class BulkProvisionPreview:
    eligible: int = 0
    already_linked: int = 0
    missing_work_email: int = 0
    sample_emails: list[str] = field(default_factory=list)


def preview_bulk_provision(company_id: int, *, statuses: tuple[str, ...] = ('active',)) -> BulkProvisionPreview:
    preview = BulkProvisionPreview()
    employees = (
        db.session.query(Employee)
        .filter(Employee.company_id == company_id)
        .order_by(Employee.first_name, Employee.last_name)
        .all()
    )
    for emp in employees:
        if statuses and emp.status not in statuses:
            continue
        if _employee_has_user(emp):
            preview.already_linked += 1
            continue
        preview.eligible += 1
        if not (emp.email and '@' in emp.email):
            preview.missing_work_email += 1
        if len(preview.sample_emails) < 5:
            preview.sample_emails.append(suggest_login_email(emp))
    return preview


def bulk_provision_employee_logins(
    company_id: int,
    password: str,
    *,
    statuses: tuple[str, ...] = ('active',),
    must_change_password: bool = True,
    role_code: str = 'EMPLOYEE',
) -> ProvisionResult:
    result = ProvisionResult()
    employees = (
        db.session.query(Employee)
        .filter(Employee.company_id == company_id)
        .order_by(Employee.id)
        .all()
    )
    for emp in employees:
        if statuses and emp.status not in statuses:
            continue
        if _employee_has_user(emp):
            result.skipped_has_account += 1
            continue
        try:
            user = provision_employee_login(
                emp,
                password,
                role_code=role_code,
                must_change_password=must_change_password,
            )
            result.created += 1
            result.created_emails.append(user.email)
        except ValueError as exc:
            result.errors.append(str(exc))
    return result
