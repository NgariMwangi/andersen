"""
Recompute an employee's gross for a payroll month from DB inputs only (no payroll_items.gross_pay).

Usage (set DATABASE_URL first):
  set DATABASE_URL=postgresql://user:pass@host:5432/dbname
  python scripts/compute_gross_from_sources.py --first Ashley --last Mbithe --month 3 --year 2026
"""
from __future__ import annotations

import argparse
from calendar import monthrange
from datetime import date
from decimal import Decimal

from sqlalchemy import extract, or_


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--first", default="Ashley")
    p.add_argument("--last", default="Mbithe")
    p.add_argument("--month", type=int, default=3)
    p.add_argument("--year", type=int, default=2026)
    args = p.parse_args()

    from app import create_app
    from app.extensions import db
    from app.models.company import Branch
    from app.models.employee import Employee
    from app.models.benefit import EmployeeBenefit
    from app.models.overtime import OvertimeRequest
    from app.models.payroll import (
        EmployeeAllowance,
        EmployeeSalary,
        PayrollRun,
        PayrollRunManualDeduction,
    )
    from app.routes.payroll import _cc  # noqa: PLC0415 — small helper
    from app.services.deduction_service import get_manual_deduction_line_items_for_run
    from app.services.payroll_engine import (
        calculate_employee_payroll,
        pro_rata_calendar_days_or_none,
        pro_rata_factor,
    )

    app = create_app()
    with app.app_context():
        emp = (
            db.session.query(Employee)
            .filter(
                Employee.first_name.ilike(args.first),
                Employee.last_name.ilike(args.last),
            )
            .first()
        )
        if not emp:
            raise SystemExit(f"No employee matching first={args.first!r} last={args.last!r}")

        branch = db.session.get(Branch, emp.branch_id)
        run_cc = _cc(branch.country_code if branch else "KE")
        run = (
            db.session.query(PayrollRun)
            .filter(
                PayrollRun.company_id == emp.company_id,
                PayrollRun.pay_month == args.month,
                PayrollRun.pay_year == args.year,
                PayrollRun.country_code == run_cc,
            )
            .order_by(PayrollRun.id.desc())
            .first()
        )
        if not run:
            raise SystemExit(
                f"No payroll run for company_id={emp.company_id} {run_cc} {args.month}/{args.year}"
            )

        pay_month, pay_year = args.month, args.year
        _, month_last_day = monthrange(pay_year, pay_month)
        period_start = date(pay_year, pay_month, 1)
        period_end = date(pay_year, pay_month, month_last_day)
        pay_date = date(pay_year, pay_month, 1)

        salary = (
            db.session.query(EmployeeSalary)
            .filter(
                EmployeeSalary.employee_id == emp.id,
                EmployeeSalary.effective_from <= period_end,
                (EmployeeSalary.effective_to.is_(None)) | (EmployeeSalary.effective_to >= period_start),
            )
            .order_by(EmployeeSalary.effective_from.desc(), EmployeeSalary.id.desc())
            .first()
        )
        if not salary:
            raise SystemExit("No EmployeeSalary row overlapping this pay period.")

        hire_or_start = emp.hire_date
        if salary.effective_from and (not hire_or_start or salary.effective_from > hire_or_start):
            hire_or_start = salary.effective_from
        end_or_termination = emp.termination_date
        if salary.effective_to and (not end_or_termination or salary.effective_to < end_or_termination):
            end_or_termination = salary.effective_to

        factor = pro_rata_factor(hire_or_start, end_or_termination, pay_month, pay_year)
        cal_days = pro_rata_calendar_days_or_none(
            hire_or_start, end_or_termination, pay_month, pay_year
        )

        emp_allowances = (
            db.session.query(EmployeeAllowance)
            .filter(
                EmployeeAllowance.employee_id == emp.id,
                EmployeeAllowance.effective_from <= pay_date,
                (EmployeeAllowance.effective_to.is_(None)) | (EmployeeAllowance.effective_to >= pay_date),
            )
            .all()
        )
        emp_benefits = (
            db.session.query(EmployeeBenefit)
            .filter(
                EmployeeBenefit.employee_id == emp.id,
                EmployeeBenefit.is_active.is_(True),
                db.or_(
                    db.and_(
                        EmployeeBenefit.frequency == "one_off",
                        EmployeeBenefit.payroll_year == pay_year,
                        EmployeeBenefit.payroll_month == pay_month,
                    ),
                    db.and_(
                        EmployeeBenefit.frequency == "monthly",
                        EmployeeBenefit.payroll_year.isnot(None),
                        EmployeeBenefit.payroll_month.isnot(None),
                        db.or_(
                            EmployeeBenefit.payroll_year < pay_year,
                            db.and_(
                                EmployeeBenefit.payroll_year == pay_year,
                                EmployeeBenefit.payroll_month <= pay_month,
                            ),
                        ),
                    ),
                    db.and_(
                        db.or_(EmployeeBenefit.frequency.is_(None), EmployeeBenefit.frequency == ""),
                        EmployeeBenefit.payroll_year.is_(None),
                        EmployeeBenefit.payroll_month.is_(None),
                        EmployeeBenefit.effective_date.isnot(None),
                        extract("year", EmployeeBenefit.effective_date) == pay_year,
                        extract("month", EmployeeBenefit.effective_date) == pay_month,
                    ),
                ),
            )
            .all()
        )

        manual_rows = (
            db.session.query(PayrollRunManualDeduction)
            .filter(
                PayrollRunManualDeduction.payroll_run_id == run.id,
                PayrollRunManualDeduction.employee_id == emp.id,
            )
            .all()
        )
        manual_lines = get_manual_deduction_line_items_for_run(run.id, emp.id)

        ot_q = db.session.query(OvertimeRequest).filter(
            OvertimeRequest.company_id == emp.company_id,
            OvertimeRequest.employee_id == emp.id,
            OvertimeRequest.for_pay_month == pay_month,
            OvertimeRequest.for_pay_year == pay_year,
            OvertimeRequest.status == "approved",
            or_(
                OvertimeRequest.applied_to_payroll_run_id.is_(None),
                OvertimeRequest.applied_to_payroll_run_id == run.id,
            ),
        )
        ot_rows = ot_q.all()
        overtime_days = sum((Decimal(str(r.days)) for r in ot_rows), start=Decimal("0"))

        inputs = {
            "employee_id": emp.id,
            "employee_number": emp.employee_number,
            "full_name": emp.full_name,
            "payroll_run_id": run.id,
            "run_status": run.status,
            "country_code": run_cc,
            "period": f"{pay_month}/{pay_year}",
            "hire_or_start": str(hire_or_start),
            "termination_or_salary_end": str(end_or_termination) if end_or_termination else None,
            "prorate_payroll": getattr(emp, "prorate_payroll", True),
            "pro_rata_factor": str(factor),
            "pro_rata_calendar_days": cal_days,
            "salary_basic": str(salary.basic_salary),
            "salary_house": str(salary.house_allowance),
            "salary_transport": str(salary.transport_allowance),
            "salary_meal": str(salary.meal_allowance),
            "salary_other_allow": str(salary.other_allowances),
            "employee_allowance_rows": len(emp_allowances),
            "benefit_rows": len(emp_benefits),
            "manual_deduction_rows_db": len(manual_rows),
            "overtime_days": str(overtime_days),
            "overtime_request_ids": [r.id for r in ot_rows],
        }

        if emp_allowances or emp_benefits:
            allowance_breakdown = []
            if emp_allowances:
                allowance_breakdown.extend(
                    [
                        {
                            "amount": ea.amount,
                            "is_taxable": ea.allowance.is_taxable,
                            "is_pensionable": ea.allowance.is_pensionable,
                            "prorate": True,
                            "code": ea.allowance.code,
                            "name": ea.allowance.name,
                        }
                        for ea in emp_allowances
                    ]
                )
            else:
                allowance_breakdown.extend(
                    [
                        {
                            "amount": salary.house_allowance,
                            "is_taxable": True,
                            "is_pensionable": True,
                            "prorate": True,
                            "code": "HOUSE",
                            "name": "House Allowance",
                        },
                        {
                            "amount": salary.transport_allowance,
                            "is_taxable": True,
                            "is_pensionable": False,
                            "prorate": True,
                            "code": "TRANSPORT",
                            "name": "Transport Allowance",
                        },
                        {
                            "amount": salary.meal_allowance,
                            "is_taxable": True,
                            "is_pensionable": False,
                            "prorate": True,
                            "code": "MEAL",
                            "name": "Meal Allowance",
                        },
                        {
                            "amount": salary.other_allowances,
                            "is_taxable": True,
                            "is_pensionable": False,
                            "prorate": True,
                            "code": "OTHER_ALLOW",
                            "name": "Other Allowances",
                        },
                    ]
                )
            allowance_breakdown.extend(
                {
                    "amount": b.amount,
                    "is_taxable": bool(getattr(b, "is_taxable", True)),
                    "is_pensionable": bool(getattr(b, "is_pensionable", True)),
                    "prorate": False,
                    "code": f"BEN-{b.id}",
                    "name": b.title or "Benefit",
                }
                for b in emp_benefits
            )
            calc = calculate_employee_payroll(
                basic_salary=salary.basic_salary,
                pension_employee_percent=salary.pension_employee_percent,
                pension_employee_fixed_amount=salary.pension_employee_fixed_amount,
                pay_date=pay_date,
                pro_rata_factor=factor,
                pro_rata_calendar_days=cal_days,
                allowance_breakdown=allowance_breakdown,
                employee_id=emp.id,
                manual_deduction_lines=manual_lines,
                statutory_company_id=emp.company_id,
                statutory_country_code=run_cc,
                overtime_days=overtime_days,
            )
        else:
            calc = calculate_employee_payroll(
                basic_salary=salary.basic_salary,
                house_allowance=salary.house_allowance,
                transport_allowance=salary.transport_allowance,
                meal_allowance=salary.meal_allowance,
                other_allowances=salary.other_allowances,
                pension_employee_percent=salary.pension_employee_percent,
                pension_employee_fixed_amount=salary.pension_employee_fixed_amount,
                pay_date=pay_date,
                pro_rata_factor=factor,
                pro_rata_calendar_days=cal_days,
                employee_id=emp.id,
                manual_deduction_lines=manual_lines,
                statutory_company_id=emp.company_id,
                statutory_country_code=run_cc,
                overtime_days=overtime_days,
            )

        gross = calc["gross_pay"]
        print("=== inputs (sources, not payroll_items) ===")
        for k, v in sorted(inputs.items()):
            print(f"  {k}: {v}")
        print("=== earnings_breakdown (computed) ===")
        for line in calc.get("earnings_breakdown") or []:
            print(f"  {line}")
        print("=== result ===")
        print(f"  recomputed_gross_pay: {gross}")
        print("(manual recurring deductions do not change gross; included in engine for consistency.)")


if __name__ == "__main__":
    main()
