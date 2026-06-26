"""
Leave balance ledger: monthly accrual, manual opening/carry, year-end rollover (capped).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func

from app.extensions import db
from app.models.employee import Employee
from app.models.leave import LeaveBalance, LeaveRequest, LeaveType


def _d(x) -> Decimal:
    return Decimal(str(x or 0)).quantize(Decimal("0.01"))


FIXED_ANNUAL_ENTITLEMENT_CODES = frozenset({'SICK'})


def is_fixed_annual_entitlement_leave(lt: LeaveType) -> bool:
    """Leave types granted in full at year start (e.g. 14 sick days), not monthly accrual."""
    return (lt.code or '').upper() in FIXED_ANNUAL_ENTITLEMENT_CODES


def leave_type_uses_balance_ledger(lt: LeaveType) -> bool:
    """True when balances are tracked (monthly accrual and/or carry-forward rules)."""
    if not lt or not lt.is_active:
        return False
    if is_fixed_annual_entitlement_leave(lt):
        return False
    if lt.accrues_monthly:
        return True
    cap = lt.carry_forward_max
    return cap is not None and int(cap) > 0


def _used_days_approved_in_year(employee_id: int, leave_type_id: int, year: int) -> Decimal:
    y0 = date(year, 1, 1)
    y1 = date(year, 12, 31)
    total = (
        db.session.query(func.coalesce(func.sum(LeaveRequest.days_requested), 0))
        .filter(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.leave_type_id == leave_type_id,
            LeaveRequest.status == "approved",
            LeaveRequest.start_date <= y1,
            LeaveRequest.end_date >= y0,
        )
        .scalar()
    )
    return _d(total)


def accrual_months_in_year(emp: Employee, year: int, as_of: date) -> int:
    """Months in `year` for which accrual applies (from hire month through `as_of`)."""
    if not emp.hire_date:
        return 12 if as_of.year > year else (as_of.month if as_of.year == year else 0)
    if emp.hire_date.year > year:
        return 0
    start_m = 1 if emp.hire_date.year < year else emp.hire_date.month
    if as_of.year < year:
        return 0
    if as_of.year > year:
        end_m = 12
    else:
        end_m = as_of.month
    if end_m < start_m:
        return 0
    return end_m - start_m + 1


def compute_accrued_for_year(lt: LeaveType, emp: Employee, year: int, as_of: date) -> Decimal:
    """Earned days YTD from monthly accrual, capped by days_per_year when set."""
    if is_fixed_annual_entitlement_leave(lt) and lt.days_per_year is not None:
        return _d(lt.days_per_year)
    if not lt.accrues_monthly or lt.days_per_month is None:
        return Decimal("0")
    dpm = _d(lt.days_per_month)
    months = accrual_months_in_year(emp, year, as_of)
    raw = dpm * Decimal(months)
    cap = lt.days_per_year
    if cap is not None:
        raw = min(raw, _d(cap))
    return raw.quantize(Decimal("0.01"))


def compute_balance_snapshot(
    employee_id: int, leave_type_id: int, year: int, as_of: date | None = None
) -> dict | None:
    """
    In-memory balance for stats and validation (does not insert rows).
    opening_balance includes manual carry from prior years and HR adjustments at year start.
    """
    as_of = as_of or date.today()
    lt = db.session.get(LeaveType, leave_type_id)
    emp = db.session.get(Employee, employee_id)
    if not lt or not emp or lt.company_id != emp.company_id or not leave_type_uses_balance_ledger(lt):
        return None
    row = (
        db.session.query(LeaveBalance)
        .filter(
            LeaveBalance.employee_id == employee_id,
            LeaveBalance.leave_type_id == leave_type_id,
            LeaveBalance.year == year,
        )
        .first()
    )
    opening = _d(row.opening_balance) if row else Decimal("0")
    adjusted = _d(row.adjusted) if row else Decimal("0")
    used = _used_days_approved_in_year(employee_id, leave_type_id, year)
    accrued = compute_accrued_for_year(lt, emp, year, as_of) if lt.accrues_monthly else Decimal("0")
    closing = opening + accrued + adjusted - used
    return {
        "opening_balance": opening,
        "accrued": accrued,
        "adjusted": adjusted,
        "used": used,
        "closing_balance": closing,
        "has_persisted_row": row is not None,
    }


def balance_row_for_hr_page(
    employee_id: int, lt: LeaveType, year: int, as_of: date | None = None
) -> dict | None:
    """One leave type row for the HR balances screen (ledger and simple entitlement types)."""
    as_of = as_of or date.today()
    emp = db.session.get(Employee, employee_id)
    if not emp or not lt or lt.company_id != emp.company_id or not lt.is_active:
        return None

    if leave_type_uses_balance_ledger(lt):
        snap = compute_balance_snapshot(employee_id, lt.id, year, as_of=as_of)
        if snap is None:
            return None
        return {
            "leave_type": lt,
            "uses_ledger": True,
            "snapshot": snap,
            "opening_field": snap["opening_balance"],
            "adjusted_field": snap["adjusted"],
            "closing": snap["closing_balance"],
        }

    used = _used_days_approved_in_year(employee_id, lt.id, year)
    entitled = _d(lt.days_per_year) if lt.days_per_year is not None else None
    earned = entitled if is_fixed_annual_entitlement_leave(lt) and entitled is not None else None
    if entitled is not None:
        closing = max(Decimal("0"), entitled - used)
    else:
        closing = None
    snap = {
        "opening_balance": Decimal("0"),
        "accrued": earned,
        "adjusted": Decimal("0"),
        "used": used,
        "closing_balance": closing,
        "has_persisted_row": False,
    }
    return {
        "leave_type": lt,
        "uses_ledger": False,
        "snapshot": snap,
        "opening_field": Decimal("0"),
        "adjusted_field": Decimal("0"),
        "closing": closing,
    }


def ensure_balance(employee_id: int, leave_type_id: int, year: int) -> LeaveBalance | None:
    """Return existing or new LeaveBalance row for accrual/carry types; None if type inactive."""
    lt = db.session.get(LeaveType, leave_type_id)
    emp = db.session.get(Employee, employee_id)
    if not lt or not emp or lt.company_id != emp.company_id or not leave_type_uses_balance_ledger(lt):
        return None
    row = (
        db.session.query(LeaveBalance)
        .filter(
            LeaveBalance.employee_id == employee_id,
            LeaveBalance.leave_type_id == leave_type_id,
            LeaveBalance.year == year,
        )
        .first()
    )
    if row:
        return row
    row = LeaveBalance(
        employee_id=employee_id,
        leave_type_id=leave_type_id,
        year=year,
        opening_balance=Decimal("0"),
        accrued=Decimal("0"),
        used=Decimal("0"),
        adjusted=Decimal("0"),
        closing_balance=Decimal("0"),
    )
    db.session.add(row)
    db.session.flush()
    return row


def recalculate_balance(row: LeaveBalance, as_of: date | None = None) -> LeaveBalance:
    """Sync used from approved requests; set accrued from leave type rules; refresh closing."""
    as_of = as_of or date.today()
    lt = row.leave_type or db.session.get(LeaveType, row.leave_type_id)
    emp = row.employee or db.session.get(Employee, row.employee_id)
    if not lt or not emp or lt.company_id != emp.company_id:
        return row

    row.used = _used_days_approved_in_year(row.employee_id, row.leave_type_id, row.year)
    if lt.accrues_monthly:
        row.accrued = compute_accrued_for_year(lt, emp, row.year, as_of)
    else:
        row.accrued = Decimal("0")

    row.closing_balance = _d(row.opening_balance) + _d(row.accrued) + _d(row.adjusted) - _d(row.used)
    return row


def get_available_days(employee_id: int, leave_type_id: int, year: int, as_of: date | None = None) -> Decimal | None:
    """Remaining book balance for capped leave; None if not using ledger (read-only, no insert)."""
    snap = compute_balance_snapshot(employee_id, leave_type_id, year, as_of=as_of)
    if snap is None:
        return None
    return max(Decimal("0"), _d(snap["closing_balance"]))


def _decimal_display(d: Decimal) -> str:
    q = _d(d)
    s = format(q, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def preview_leave_balance_for_apply(employee_id: int, leave_type_id: int, year: int) -> dict:
    """
    JSON-friendly summary when applying for leave: accrued (ledger), available, or yearly remaining (simple types).
    """
    lt = db.session.get(LeaveType, leave_type_id)
    if not lt or not lt.is_active:
        return {"error": "invalid_leave_type"}
    emp = db.session.get(Employee, employee_id)
    if not emp:
        return {"error": "invalid_employee"}
    if lt.company_id != emp.company_id:
        return {"error": "invalid_leave_type"}

    today = date.today()
    if year < today.year:
        as_of = date(year, 12, 31)
    elif year > today.year:
        as_of = date(year, 1, 1)
    else:
        as_of = today

    if leave_type_uses_balance_ledger(lt):
        snap = compute_balance_snapshot(employee_id, leave_type_id, year, as_of=as_of)
        if snap is None:
            return {"error": "internal"}
        avail = _d(snap["closing_balance"])
        out: dict = {
            "mode": "ledger",
            "year": year,
            "leave_type_name": lt.name,
            "show_earned_this_year": bool(lt.accrues_monthly),
            "opening_balance": _decimal_display(snap["opening_balance"]),
            "accrued": _decimal_display(snap["accrued"]),
            "adjusted": _decimal_display(snap["adjusted"]),
            "used_approved": _decimal_display(snap["used"]),
            "available": _decimal_display(avail),
            "remaining": _decimal_display(max(Decimal("0"), avail)),
        }
        if lt.days_per_year is not None:
            out["entitled_per_year"] = _decimal_display(_d(lt.days_per_year))
            out["days_per_year_cap"] = _decimal_display(_d(lt.days_per_year))
        return out

    used = _used_days_approved_in_year(employee_id, leave_type_id, year)
    if lt.days_per_year is not None:
        ent = _d(lt.days_per_year)
        avail = max(Decimal("0"), ent - used)
        return {
            "mode": "simple",
            "year": year,
            "leave_type_name": lt.name,
            "show_earned_this_year": False,
            "entitled_per_year": _decimal_display(ent),
            "entitlement": _decimal_display(ent),
            "used_approved": _decimal_display(used),
            "available": _decimal_display(avail),
            "remaining": _decimal_display(avail),
        }
    return {
        "mode": "unlimited",
        "year": year,
        "leave_type_name": lt.name,
    }


def refresh_leave_balance_after_request_change(employee_id: int, leave_type_id: int, year: int) -> None:
    """Persist ledger row and sync used/accrued after leave request status changes."""
    lt = db.session.get(LeaveType, leave_type_id)
    if not lt or not leave_type_uses_balance_ledger(lt):
        return
    row = ensure_balance(employee_id, leave_type_id, year)
    if row:
        recalculate_balance(row, as_of=date.today())


def rollover_opening_for_next_year(
    from_year: int,
    to_year: int,
    company_id: int,
    as_of: date | None = None,
) -> tuple[int, list[str]]:
    """
    Create next-year balance rows with opening_balance = min(prior closing, carry_forward_max).
    Returns (number of rows created/updated, log messages for flash/UI).
    """
    as_of = as_of or date.today()
    if to_year != from_year + 1:
        raise ValueError("to_year must be from_year + 1")

    messages: list[str] = []
    count = 0
    types_list = [
        lt
        for lt in db.session.query(LeaveType)
        .filter(LeaveType.company_id == company_id, LeaveType.is_active.is_(True))
        .all()
        if leave_type_uses_balance_ledger(lt)
    ]

    employees = (
        db.session.query(Employee)
        .filter(Employee.company_id == company_id, Employee.status == "active")
        .all()
    )

    for emp in employees:
        for lt in types_list:
            cap = int(lt.carry_forward_max or 0)
            prev = (
                db.session.query(LeaveBalance)
                .filter(
                    LeaveBalance.employee_id == emp.id,
                    LeaveBalance.leave_type_id == lt.id,
                    LeaveBalance.year == from_year,
                )
                .first()
            )
            if prev:
                recalculate_balance(prev, as_of=date(from_year, 12, 31))
            else:
                prev = ensure_balance(emp.id, lt.id, from_year)
                if prev:
                    recalculate_balance(prev, as_of=date(from_year, 12, 31))

            closing = _d(prev.closing_balance) if prev else Decimal("0")
            carry = min(max(Decimal("0"), closing), Decimal(cap)) if cap > 0 else Decimal("0")

            nxt = (
                db.session.query(LeaveBalance)
                .filter(
                    LeaveBalance.employee_id == emp.id,
                    LeaveBalance.leave_type_id == lt.id,
                    LeaveBalance.year == to_year,
                )
                .first()
            )
            if not nxt:
                nxt = LeaveBalance(
                    employee_id=emp.id,
                    leave_type_id=lt.id,
                    year=to_year,
                    opening_balance=carry,
                    accrued=Decimal("0"),
                    used=Decimal("0"),
                    adjusted=Decimal("0"),
                    closing_balance=Decimal("0"),
                )
                db.session.add(nxt)
            else:
                nxt.opening_balance = carry
            as_of_next = as_of if as_of.year == to_year else date(to_year, 1, 1)
            recalculate_balance(nxt, as_of=as_of_next)
            count += 1
    messages.append(
        f"Rolled {from_year} → {to_year}: updated {count} employee leave balance row(s). "
        f"Opening balances capped by each leave type's max carry-forward."
    )
    return count, messages
