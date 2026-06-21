"""
Seed database with initial roles, permissions, a demo tenant (company + branch + employer),
and reference data scoped by company_id.

Run after creating tables (e.g. SQLAlchemy create_all):

  python -c "from scripts.seed_data import run; run()"

Or: flask shell, then: from scripts.seed_data import run; run()
"""
from datetime import date
from decimal import Decimal
from pathlib import Path

# Load .env from project root so DATABASE_URL is set (even when run from another dir)
_project_root = Path(__file__).resolve().parent.parent
_env = _project_root / ".env"
if _env.exists():
    from dotenv import load_dotenv

    load_dotenv(_env)

from app import create_app
from app.extensions import db
from app.models.user import Role, Permission, RolePermission
from app.models.company import Company, Branch
from app.models.employer import Employer
from app.models.department import Department
from app.models.job_title import JobTitle
from app.models.leave import PublicHoliday
from app.models.payroll import Allowance
from app.services.company_bootstrap import bootstrap_company_defaults


def run():
    app = create_app()
    with app.app_context():
        # Permissions (fixed catalogue)
        perms = [
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
        ]
        for code, name in perms:
            if db.session.query(Permission).filter_by(code=code).first() is None:
                db.session.add(Permission(code=code, name=name))
        db.session.commit()

        # Role → permission codes (must match production DB role_permissions)
        role_perms = {
            'ADMIN': [
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
            ],
            'HR_MANAGER': [
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
            ],
            'HR_STAFF': [
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
            ],
            'MANAGER': [
                'request_overtime',
                'submit_overtime_same_dept',
                'view_departments',
                'view_employees',
                'view_leave',
                'view_reports',
                'send_messages',
                'view_assets',
                'submit_tickets',
            ],
            'EMPLOYEE': ['request_overtime', 'view_leave', 'send_messages', 'submit_tickets'],
            'IT_SUPPORT': [
                'submit_tickets',
                'view_tickets',
                'manage_tickets',
                'send_messages',
            ],
            'FINANCE_PAYROLL_APPROVER': [
                'view_payroll',
                'review_payroll_finance',
                'mark_payroll_paid',
                'view_reports',
            ],
        }
        for code, name in [
            ('ADMIN', 'Administrator'),
            ('HR_MANAGER', 'HR Manager'),
            ('HR_STAFF', 'HR Staff'),
            ('MANAGER', 'Manager'),
            ('EMPLOYEE', 'Employee'),
            ('IT_SUPPORT', 'IT Support'),
            ('FINANCE_PAYROLL_APPROVER', 'Finance Payroll Approver'),
        ]:
            role = db.session.query(Role).filter_by(code=code).first()
            if role is None:
                role = Role(code=code, name=name)
                db.session.add(role)
                db.session.flush()
            for pcode in role_perms.get(code, []):
                perm = db.session.query(Permission).filter_by(code=pcode).first()
                if perm and not db.session.query(RolePermission).filter_by(
                    role_id=role.id, permission_id=perm.id
                ).first():
                    db.session.add(RolePermission(role_id=role.id, permission_id=perm.id))
        # Managers approve leave at supervisor step only (not HR final step).
        manager_role = db.session.query(Role).filter_by(code='MANAGER').first()
        hr_leave_perm = db.session.query(Permission).filter_by(code='approve_leave').first()
        if manager_role and hr_leave_perm:
            legacy = db.session.query(RolePermission).filter_by(
                role_id=manager_role.id, permission_id=hr_leave_perm.id
            ).first()
            if legacy:
                db.session.delete(legacy)
        db.session.commit()

        # Demo tenant (first-time DB or extra seed run)
        company = db.session.query(Company).order_by(Company.id).first()
        if company is None:
            company = Company(name='Demo Company', is_active=True)
            db.session.add(company)
            db.session.flush()
            db.session.add(Branch(company_id=company.id, name='Head Office', country_code='KE'))
            db.session.add(Employer(company_id=company.id, name='Demo Company'))
            db.session.commit()

        cid = company.id
        ke = 'KE'
        bootstrap_company_defaults(cid, ke)

        # Departments
        for code, name in [
            ('FIN', 'FINANCE'),
            ('GEN', 'General'),
            ('IT', 'IT'),
        ]:
            if db.session.query(Department).filter_by(company_id=cid, code=code).first() is None:
                db.session.add(Department(company_id=cid, code=code, name=name))
        db.session.commit()

        # Job titles
        for code, name in [
            ('STAFF', 'Staff'),
            ('SWE', 'Software Engineer'),
        ]:
            if db.session.query(JobTitle).filter_by(company_id=cid, code=code).first() is None:
                db.session.add(JobTitle(company_id=cid, code=code, name=name))
        db.session.commit()

        # Allowances (catalog for payroll)
        for code, name, is_taxable, is_pensionable in [
            ('*', 'House Allowance', True, True),
            ('HOUSE', 'House Allowance', True, True),
            ('MEAL', 'Meal Allowance', True, False),
            ('MEDICAL', 'Medical Allowance', True, False),
            ('OTHER', 'Other Allowance', True, False),
            ('P', 'Transport Allowance', True, True),
            ('TRANSPORT', 'Transport Allowance', True, False),
        ]:
            if db.session.query(Allowance).filter_by(company_id=cid, code=code).first() is None:
                db.session.add(
                    Allowance(
                        company_id=cid,
                        code=code,
                        name=name,
                        is_taxable=is_taxable,
                        is_pensionable=is_pensionable,
                    )
                )
        db.session.commit()

        # Kenya public holidays (recurring + sample one-offs) — tenant + country scoped
        for month, day, hol_name in [
            (1, 1, "New Year's Day"),
            (5, 1, 'Labour Day'),
            (6, 1, 'Madaraka Day'),
            (10, 10, 'Huduma Day'),
            (10, 20, 'Mashujaa Day'),
            (12, 12, 'Jamhuri Day'),
            (12, 25, 'Christmas Day'),
            (12, 26, 'Boxing Day'),
        ]:
            exists = (
                db.session.query(PublicHoliday)
                .filter(
                    PublicHoliday.company_id == cid,
                    PublicHoliday.country_code == ke,
                    PublicHoliday.kind == 'recurring',
                    PublicHoliday.recurring_month == month,
                    PublicHoliday.recurring_day == day,
                )
                .first()
            )
            if exists is None:
                db.session.add(
                    PublicHoliday(
                        company_id=cid,
                        country_code=ke,
                        kind='recurring',
                        name=hol_name,
                        recurring_month=month,
                        recurring_day=day,
                        date=None,
                    )
                )
        db.session.commit()

        for hol_date, hol_name in [
            (date(2026, 4, 3), 'Good Friday'),
            (date(2026, 4, 6), 'Easter Monday'),
            (date(2026, 3, 20), 'Eid al-Fitr'),
            (date(2026, 5, 27), 'Eid al-Adha'),
        ]:
            exists = (
                db.session.query(PublicHoliday)
                .filter(
                    PublicHoliday.company_id == cid,
                    PublicHoliday.country_code == ke,
                    PublicHoliday.kind == 'one_off',
                    PublicHoliday.date == hol_date,
                )
                .first()
            )
            if exists is None:
                db.session.add(
                    PublicHoliday(
                        company_id=cid,
                        country_code=ke,
                        kind='one_off',
                        name=hol_name,
                        date=hol_date,
                        recurring_month=None,
                        recurring_day=None,
                    )
                )
        db.session.commit()

        print(
            'Seed completed: permissions, roles, demo company + branch + employer, '
            'defaults (leave types, document categories, KE statutory), departments, job titles, '
            'allowances, public holidays.'
        )
