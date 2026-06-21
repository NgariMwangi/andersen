"""Consultant lines on shared monthly payroll runs."""
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.company import Branch
from app.models.consultant import (
    Consultant,
    ConsultantCompensation,
    ConsultantPayrollItem,
    ConsultantPayrollRunExclusion,
)
from app.models.payroll import PayrollRun
from app.services.consultant_payroll_engine import calculate_consultant_payroll
from app.services.payroll_engine import pro_rata_calendar_days_or_none, pro_rata_factor


def _cc(country_code: str | None) -> str:
    return (country_code or 'KE').upper()[:2]


def active_consultants_for_run(run: PayrollRun) -> list[Consultant]:
    run_cc = _cc(run.country_code)
    return (
        db.session.query(Consultant)
        .options(joinedload(Consultant.branch))
        .join(Branch, Consultant.branch_id == Branch.id)
        .filter(
            Consultant.company_id == run.company_id,
            Consultant.status == 'active',
            Branch.country_code == run_cc,
        )
        .order_by(Consultant.first_name, Consultant.last_name)
        .all()
    )


def compensation_for_period(consultant_id: int, period_start: date, period_end: date) -> ConsultantCompensation | None:
    return (
        db.session.query(ConsultantCompensation)
        .filter(
            ConsultantCompensation.consultant_id == consultant_id,
            ConsultantCompensation.effective_from <= period_end,
            db.or_(
                ConsultantCompensation.effective_to.is_(None),
                ConsultantCompensation.effective_to >= period_start,
            ),
        )
        .order_by(ConsultantCompensation.effective_from.desc(), ConsultantCompensation.id.desc())
        .first()
    )


def excluded_consultant_ids(run_id: int) -> set[int]:
    rows = (
        db.session.query(ConsultantPayrollRunExclusion.consultant_id)
        .filter(ConsultantPayrollRunExclusion.payroll_run_id == run_id)
        .all()
    )
    return {r[0] for r in rows}


def consultant_eligibility_for_run(run: PayrollRun, period_start: date, period_end: date):
    """Return (consultants, eligible_ids, missing_compensation, excluded_ids)."""
    consultants = active_consultants_for_run(run)
    eligible_ids = set()
    missing = []
    for c in consultants:
        comp = compensation_for_period(c.id, period_start, period_end)
        if comp:
            eligible_ids.add(c.id)
        else:
            missing.append(c)
    excluded = excluded_consultant_ids(run.id)
    return consultants, eligible_ids, missing, excluded


def _pro_rata_for_consultant(consultant: Consultant, comp: ConsultantCompensation, run: PayrollRun):
    start = consultant.start_date
    if comp.effective_from and (not start or comp.effective_from > start):
        start = comp.effective_from
    end = consultant.end_date
    if comp.effective_to and (not end or comp.effective_to < end):
        end = comp.effective_to
    factor = pro_rata_factor(start, end, run.pay_month, run.pay_year)
    cal_days = pro_rata_calendar_days_or_none(start, end, run.pay_month, run.pay_year)
    return factor, cal_days


def build_consultant_calc(consultant: Consultant, comp: ConsultantCompensation, run: PayrollRun) -> dict:
    factor, cal_days = _pro_rata_for_consultant(consultant, comp, run)
    return calculate_consultant_payroll(
        monthly_fee=comp.monthly_fee,
        other_allowances=comp.other_allowances or 0,
        withholding_rate=consultant.withholding_rate,
        pro_rata_factor=factor,
        pro_rata_calendar_days=cal_days,
    )


def upsert_consultant_payroll_item(run_id: int, consultant: Consultant, calc: dict) -> ConsultantPayrollItem:
    existing = (
        db.session.query(ConsultantPayrollItem)
        .filter(
            ConsultantPayrollItem.payroll_run_id == run_id,
            ConsultantPayrollItem.consultant_id == consultant.id,
        )
        .first()
    )
    if existing:
        existing.gross_pay = calc['gross_pay']
        existing.withholding_tax = calc['withholding_tax']
        existing.net_pay = calc['net_pay']
        existing.earnings_breakdown = calc['earnings_breakdown']
        existing.deductions_breakdown = calc['deductions_breakdown']
        existing.is_pro_rata = calc['is_pro_rata']
        return existing
    item = ConsultantPayrollItem(
        payroll_run_id=run_id,
        consultant_id=consultant.id,
        gross_pay=calc['gross_pay'],
        withholding_tax=calc['withholding_tax'],
        net_pay=calc['net_pay'],
        earnings_breakdown=calc['earnings_breakdown'],
        deductions_breakdown=calc['deductions_breakdown'],
        is_pro_rata=calc['is_pro_rata'],
    )
    db.session.add(item)
    return item


def recalculate_single_consultant(run: PayrollRun, consultant_id: int, period_start: date, period_end: date):
    """Returns (ok, error_message, calc_dict)."""
    consultant = db.session.get(Consultant, consultant_id)
    if not consultant or consultant.company_id != run.company_id:
        return False, 'Consultant not found in this company.', None
    comp = compensation_for_period(consultant_id, period_start, period_end)
    if not comp:
        return False, 'Consultant has no compensation set for this period.', None
    db.session.query(ConsultantPayrollItem).filter(
        ConsultantPayrollItem.payroll_run_id == run.id,
        ConsultantPayrollItem.consultant_id == consultant_id,
    ).delete()
    db.session.flush()
    calc = build_consultant_calc(consultant, comp, run)
    upsert_consultant_payroll_item(run.id, consultant, calc)
    return True, None, calc


def calculate_all_consultants_for_run(run: PayrollRun, period_start: date, period_end: date) -> int:
    excluded = excluded_consultant_ids(run.id)
    consultants, eligible_ids, _, _ = consultant_eligibility_for_run(run, period_start, period_end)
    db.session.query(ConsultantPayrollItem).filter(ConsultantPayrollItem.payroll_run_id == run.id).delete()
    db.session.flush()
    count = 0
    for c in consultants:
        if c.id not in eligible_ids or c.id in excluded:
            continue
        comp = compensation_for_period(c.id, period_start, period_end)
        if not comp:
            continue
        calc = build_consultant_calc(c, comp, run)
        upsert_consultant_payroll_item(run.id, c, calc)
        count += 1
    return count


def save_consultant_exclusions(
    run_id: int,
    eligible_ids: set[int],
    selected_excluded: set[int],
    table_scope: set[int] | None = None,
    previous_excluded: set[int] | None = None,
) -> int:
    if table_scope is not None and previous_excluded is not None:
        new_excluded = set()
        for cid in eligible_ids:
            if cid in table_scope:
                if cid in selected_excluded:
                    new_excluded.add(cid)
            elif cid in previous_excluded:
                new_excluded.add(cid)
    else:
        new_excluded = {cid for cid in selected_excluded if cid in eligible_ids}
    db.session.query(ConsultantPayrollRunExclusion).filter(
        ConsultantPayrollRunExclusion.payroll_run_id == run_id
    ).delete()
    for cid in sorted(new_excluded):
        db.session.add(ConsultantPayrollRunExclusion(payroll_run_id=run_id, consultant_id=cid))
    return len(new_excluded)
