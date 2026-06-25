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
        # Permissions and roles (global catalogue)
        from app.services.rbac_bootstrap import ensure_rbac_defaults

        ensure_rbac_defaults()

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
