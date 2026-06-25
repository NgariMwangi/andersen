"""Idempotent seed for permissions, roles, and role-permission mappings."""
from __future__ import annotations

from app.extensions import db
from app.models.user import Permission, Role, RolePermission

PERMISSIONS: tuple[tuple[str, str], ...] = (
    ('view_employees', 'View employees'),
    ('create_employees', 'Create employees'),
    ('edit_employees', 'Edit employees'),
    ('view_departments', 'View departments'),
    ('manage_departments', 'Manage departments'),
    ('view_payroll', 'View payroll'),
    ('process_payroll', 'Process payroll'),
    ('approve_payroll', 'Approve payroll'),
    ('review_payroll_finance', 'Finance review approved payroll'),
    ('mark_payroll_paid', 'Mark payroll as paid'),
    ('view_leave', 'View leave'),
    ('manage_leave_types', 'Manage leave types'),
    ('approve_leave', 'Approve leave (HR final step)'),
    ('view_attendance', 'View attendance'),
    ('view_reports', 'View reports'),
    ('manage_statutory', 'Manage statutory rates'),
    ('manage_settings', 'Manage settings'),
    ('view_audit_log', 'View audit log'),
    ('request_overtime', 'Request overtime compensation'),
    ('submit_overtime_same_dept', 'Submit overtime for employee (same department / team)'),
    ('approve_overtime', 'Approve any overtime request (HR)'),
    ('send_messages', 'Send internal messages'),
    ('send_broadcast_messages', 'Message whole organization'),
    ('view_assets', 'View company assets'),
    ('manage_assets', 'Manage company assets'),
    ('submit_tickets', 'Submit IT support tickets'),
    ('view_tickets', 'View IT ticket queue'),
    ('manage_tickets', 'Manage IT tickets'),
)

ROLES: tuple[tuple[str, str], ...] = (
    ('ADMIN', 'Administrator'),
    ('HR_MANAGER', 'HR Manager'),
    ('HR_STAFF', 'HR Staff'),
    ('MANAGER', 'Manager'),
    ('EMPLOYEE', 'Employee'),
    ('IT_SUPPORT', 'IT Support'),
    ('FINANCE_PAYROLL_APPROVER', 'Finance Payroll Approver'),
)

ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    'ADMIN': (
        'approve_leave',
        'approve_overtime',
        'approve_payroll',
        'review_payroll_finance',
        'mark_payroll_paid',
        'create_employees',
        'edit_employees',
        'manage_departments',
        'manage_settings',
        'manage_statutory',
        'process_payroll',
        'request_overtime',
        'submit_overtime_same_dept',
        'view_attendance',
        'view_audit_log',
        'view_departments',
        'view_employees',
        'view_leave',
        'view_payroll',
        'view_reports',
        'send_messages',
        'send_broadcast_messages',
        'view_assets',
        'manage_assets',
        'submit_tickets',
        'view_tickets',
        'manage_tickets',
    ),
    'HR_MANAGER': (
        'approve_leave',
        'approve_overtime',
        'approve_payroll',
        'create_employees',
        'edit_employees',
        'manage_departments',
        'manage_statutory',
        'process_payroll',
        'request_overtime',
        'submit_overtime_same_dept',
        'view_attendance',
        'view_audit_log',
        'view_departments',
        'view_employees',
        'view_leave',
        'view_payroll',
        'view_reports',
        'send_messages',
        'send_broadcast_messages',
        'view_assets',
        'manage_assets',
        'submit_tickets',
    ),
    'HR_STAFF': (
        'approve_leave',
        'approve_overtime',
        'create_employees',
        'edit_employees',
        'process_payroll',
        'request_overtime',
        'submit_overtime_same_dept',
        'view_attendance',
        'view_departments',
        'view_employees',
        'view_leave',
        'view_payroll',
        'view_reports',
        'send_messages',
        'send_broadcast_messages',
        'view_assets',
        'manage_assets',
        'submit_tickets',
    ),
    'MANAGER': (
        'request_overtime',
        'submit_overtime_same_dept',
        'view_departments',
        'view_employees',
        'view_leave',
        'view_reports',
        'send_messages',
        'view_assets',
        'submit_tickets',
    ),
    'EMPLOYEE': (
        'request_overtime',
        'view_leave',
        'send_messages',
        'submit_tickets',
    ),
    'IT_SUPPORT': (
        'submit_tickets',
        'view_tickets',
        'manage_tickets',
        'send_messages',
    ),
    'FINANCE_PAYROLL_APPROVER': (
        'view_payroll',
        'review_payroll_finance',
        'mark_payroll_paid',
        'view_reports',
    ),
}


def ensure_rbac_defaults() -> None:
    """Ensure permissions, roles, and mappings exist (safe to call repeatedly)."""
    for code, name in PERMISSIONS:
        if db.session.query(Permission).filter_by(code=code).first() is None:
            db.session.add(Permission(code=code, name=name))
    db.session.flush()

    perm_by_code = {
        row.code: row
        for row in db.session.query(Permission).all()
    }

    for code, name in ROLES:
        role = db.session.query(Role).filter_by(code=code).first()
        if role is None:
            role = Role(code=code, name=name)
            db.session.add(role)
            db.session.flush()
        for pcode in ROLE_PERMISSIONS.get(code, ()):
            perm = perm_by_code.get(pcode)
            if not perm:
                continue
            exists = db.session.query(RolePermission).filter_by(
                role_id=role.id,
                permission_id=perm.id,
            ).first()
            if not exists:
                db.session.add(RolePermission(role_id=role.id, permission_id=perm.id))

    manager_role = db.session.query(Role).filter_by(code='MANAGER').first()
    hr_leave_perm = perm_by_code.get('approve_leave')
    if manager_role and hr_leave_perm:
        legacy = db.session.query(RolePermission).filter_by(
            role_id=manager_role.id,
            permission_id=hr_leave_perm.id,
        ).first()
        if legacy:
            db.session.delete(legacy)

    db.session.commit()


def get_role_by_code(code: str) -> Role | None:
    ensure_rbac_defaults()
    return db.session.query(Role).filter_by(code=(code or '').strip().upper()).first()
