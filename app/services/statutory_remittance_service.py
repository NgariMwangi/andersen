"""
Record statutory amounts owed to institutions when payroll is approved.
"""
from decimal import Decimal

from app.extensions import db
from app.models.payroll import PayrollItem, PayrollStatutoryRemittance

# (code, institution display name, attribute on PayrollItem)
STATUTORY_LINES = (
    ('PAYE', 'Kenya Revenue Authority (PAYE)', 'paye'),
    ('NSSF_EMPLOYEE', 'National Social Security Fund (Employee contribution)', 'nssf_employee'),
    ('NSSF_EMPLOYER', 'National Social Security Fund (Employer contribution)', 'nssf_employer'),
    ('SHIF', 'Social Health Authority (SHIF)', 'shif'),
    ('HOUSING_LEVY', 'Affordable Housing Levy', 'housing_levy'),
)


def delete_statutory_remitances_for_run(payroll_run_id: int) -> int:
    """Remove all statutory remittance rows for a payroll run (e.g. on un-approve)."""
    return db.session.query(PayrollStatutoryRemittance).filter(
        PayrollStatutoryRemittance.payroll_run_id == payroll_run_id
    ).delete(synchronize_session=False)


def replace_statutory_remitances_for_run(payroll_run_id: int) -> int:
    """
    Delete existing remittance rows for this run and create fresh rows from payroll items.
    Only non-zero amounts are stored. Returns number of rows created.
    """
    db.session.query(PayrollStatutoryRemittance).filter(
        PayrollStatutoryRemittance.payroll_run_id == payroll_run_id
    ).delete(synchronize_session=False)
    items = (
        db.session.query(PayrollItem)
        .filter(PayrollItem.payroll_run_id == payroll_run_id)
        .all()
    )
    count = 0
    for item in items:
        for code, institution_name, attr in STATUTORY_LINES:
            raw = getattr(item, attr, None)
            amount = Decimal(str(raw or 0)).quantize(Decimal('0.01'))
            if amount <= 0:
                continue
            db.session.add(
                PayrollStatutoryRemittance(
                    payroll_run_id=payroll_run_id,
                    payroll_item_id=item.id,
                    employee_id=item.employee_id,
                    statutory_code=code,
                    institution_name=institution_name,
                    amount=amount,
                )
            )
            count += 1
    db.session.flush()
    return count


def institution_totals_for_run(payroll_run_id: int) -> list:
    """Aggregate amounts by statutory_code / institution for one payroll run."""
    from sqlalchemy import func

    rows = (
        db.session.query(
            PayrollStatutoryRemittance.statutory_code,
            PayrollStatutoryRemittance.institution_name,
            func.sum(PayrollStatutoryRemittance.amount).label('total'),
        )
        .filter(PayrollStatutoryRemittance.payroll_run_id == payroll_run_id)
        .group_by(
            PayrollStatutoryRemittance.statutory_code,
            PayrollStatutoryRemittance.institution_name,
        )
        .order_by(PayrollStatutoryRemittance.statutory_code)
        .all()
    )
    return [
        {'code': r.statutory_code, 'institution_name': r.institution_name, 'total': r.total}
        for r in rows
    ]
