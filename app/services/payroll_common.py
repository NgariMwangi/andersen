"""Shared payroll helpers (earnings, proration) used by country-specific engines."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.services.statutory_service import get_pensionable_pay

PRORATA_STANDARD_MONTH_DAYS = 30


@dataclass(frozen=True)
class GrossEarningsResult:
    """Cash earnings split for statutory vs net-only (non-taxable) amounts."""

    gross_pay: Decimal
    taxable_gross: Decimal
    non_taxable_earnings: Decimal
    pensionable_pay: Decimal
    earnings_breakdown: list


def decimalize(value) -> Decimal:
    if value is None:
        return Decimal('0')
    return Decimal(str(value))


def employment_partial_month_days(
    hire_date: date | None,
    termination_date: date | None,
    pay_month: int,
    pay_year: int,
) -> tuple[int, bool]:
    from calendar import monthrange

    month_start = date(pay_year, pay_month, 1)
    _, last_day = monthrange(pay_year, pay_month)
    month_end = date(pay_year, pay_month, last_day)
    work_start = month_start
    work_end = month_end
    if hire_date and hire_date > month_start:
        work_start = hire_date
    if termination_date and termination_date < month_end:
        work_end = termination_date
    if work_start > work_end:
        return 0, True
    days_worked = (work_end - work_start).days + 1
    partial_month = (work_start > month_start) or (work_end < month_end)
    return days_worked, partial_month


def pro_rata_calendar_days_or_none(
    hire_date: date | None,
    termination_date: date | None,
    pay_month: int,
    pay_year: int,
) -> int | None:
    days_worked, partial = employment_partial_month_days(
        hire_date, termination_date, pay_month, pay_year
    )
    if not partial:
        return None
    return days_worked


def employee_worked_in_pay_period(
    hire_date: date | None,
    termination_date: date | None,
    period_start: date,
    period_end: date,
) -> bool:
    """True when employment overlaps the payroll month (incl. mid-month termination)."""
    if hire_date and hire_date > period_end:
        return False
    if termination_date and termination_date < period_start:
        return False
    return True


def pro_rata_factor(
    hire_date: date | None,
    termination_date: date | None,
    pay_month: int,
    pay_year: int,
) -> Decimal:
    days_worked, partial = employment_partial_month_days(
        hire_date, termination_date, pay_month, pay_year
    )
    if not partial:
        return Decimal('1')
    denom = Decimal(PRORATA_STANDARD_MONTH_DAYS)
    if denom <= 0:
        return Decimal('0')
    return Decimal(days_worked) / denom


def _earnings_line(code: str, name: str, amount: Decimal, *, is_taxable: bool) -> dict:
    return {
        'code': code,
        'name': name,
        'amount': float(amount),
        'is_taxable': is_taxable,
    }


def build_gross_earnings(
    *,
    basic_salary: Decimal,
    house_allowance: Decimal | None = None,
    transport_allowance: Decimal | None = None,
    meal_allowance: Decimal | None = None,
    other_allowances: Decimal | None = None,
    pro_rata_factor: Decimal | None = None,
    pro_rata_calendar_days: int | None = None,
    other_earnings: Decimal | None = None,
    allowance_breakdown: list | None = None,
    overtime_days: Decimal | None = None,
) -> GrossEarningsResult:
    """
    Returns gross earnings split into taxable and non-taxable cash.
    Statutory deductions use taxable_gross; non_taxable_earnings are added to net after deductions.
    """
    factor = decimalize(pro_rata_factor) if pro_rata_factor is not None else Decimal('1')
    pr_days = pro_rata_calendar_days
    denom = Decimal(PRORATA_STANDARD_MONTH_DAYS)

    def prorate_monthly(monthly_val: Decimal) -> Decimal:
        v = decimalize(monthly_val)
        if pr_days is not None:
            return (v / denom) * Decimal(pr_days)
        return v * factor

    other_earn = decimalize(other_earnings)
    basic_full = decimalize(basic_salary)
    basic = prorate_monthly(basic_salary)
    taxable_total = basic
    non_taxable_total = Decimal('0')
    pensionable_allowances = Decimal('0')
    # Overtime daily rate uses full-month basic + allowances only (not prorated).
    overtime_rate_base = basic_full

    if allowance_breakdown:
        earnings_breakdown = [_earnings_line('BASIC', 'Basic Salary', basic, is_taxable=True)]
        for a in allowance_breakdown:
            base_amt = decimalize(a.get('amount', 0))
            should_prorate_line = bool(a.get('prorate', False))
            amt = prorate_monthly(base_amt) if should_prorate_line else base_amt
            if should_prorate_line:
                overtime_rate_base += base_amt
            is_taxable = bool(a.get('is_taxable', True))
            if is_taxable:
                taxable_total += amt
            else:
                non_taxable_total += amt
            if a.get('is_pensionable'):
                pensionable_allowances += amt
            earnings_breakdown.append(
                _earnings_line(
                    a.get('code', 'ALLOW'),
                    a.get('name', 'Allowance'),
                    amt,
                    is_taxable=is_taxable,
                )
            )
        if other_earn > 0:
            taxable_total += other_earn
            earnings_breakdown.append(
                _earnings_line('OTHER_EARN', 'Other Earnings', other_earn, is_taxable=True)
            )
        pensionable = get_pensionable_pay(basic, pensionable_allowances, Decimal('0'))
    else:
        house_full = decimalize(house_allowance)
        transport_full = decimalize(transport_allowance)
        meal_full = decimalize(meal_allowance)
        other_allow_full = decimalize(other_allowances)
        house = prorate_monthly(house_full)
        transport = prorate_monthly(transport_full)
        meal = prorate_monthly(meal_full)
        other_allow = prorate_monthly(other_allow_full)
        taxable_total = (basic + house + transport + meal + other_allow + other_earn).quantize(
            Decimal('0.01')
        )
        overtime_rate_base = basic_full + house_full + transport_full + meal_full + other_allow_full
        pensionable = get_pensionable_pay(basic, house, Decimal('0'))
        earnings_breakdown = [
            _earnings_line('BASIC', 'Basic Salary', basic, is_taxable=True),
            _earnings_line('HOUSE', 'House Allowance', house, is_taxable=True),
            _earnings_line('TRANSPORT', 'Transport Allowance', transport, is_taxable=True),
            _earnings_line('MEAL', 'Meal Allowance', meal, is_taxable=True),
            _earnings_line('OTHER_ALLOW', 'Other Allowances', other_allow, is_taxable=True),
        ]
        if other_earn > 0:
            earnings_breakdown.append(
                _earnings_line('OTHER_EARN', 'Other Earnings', other_earn, is_taxable=True)
            )

    ot_days = decimalize(overtime_days) if overtime_days is not None else Decimal('0')
    if ot_days > 0:
        per_day = (overtime_rate_base * Decimal('12')) / Decimal('365')
        ot_amt = (per_day * ot_days).quantize(Decimal('0.01'))
        earnings_breakdown.append(
            _earnings_line('OVERTIME', 'Overtime compensation', ot_amt, is_taxable=True)
        )
        taxable_total = (taxable_total + ot_amt).quantize(Decimal('0.01'))
        pensionable = (pensionable + ot_amt).quantize(Decimal('0.01'))

    gross_pay = (taxable_total + non_taxable_total).quantize(Decimal('0.01'))
    return GrossEarningsResult(
        gross_pay=gross_pay,
        taxable_gross=taxable_total.quantize(Decimal('0.01')),
        non_taxable_earnings=non_taxable_total.quantize(Decimal('0.01')),
        pensionable_pay=pensionable,
        earnings_breakdown=earnings_breakdown,
    )
