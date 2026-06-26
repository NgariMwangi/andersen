"""
Default reference data for a new tenant (leave types, document categories, Kenya statutory for a country).
Called after creating a Company so the org can be used immediately.
"""
from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models.document import DocumentCategory
from app.models.leave import LeaveType
from app.models.statutory import StatutoryRate, PayeBracket, NssfTier


def bootstrap_company_defaults(company_id: int, country_code: str = 'KE') -> None:
    """Idempotent: only inserts rows missing for this company (+ country for statutory)."""
    cc = (country_code or 'KE').upper()[:2]

    leave_specs = [
        ('ANNUAL', 'Annual Leave', Decimal('24'), True, Decimal('2'), True, 'working', 0),
        ('SICK', 'Sick Leave', Decimal('14'), False, None, True, 'working', 0),
        ('MATERNITY', 'Maternity Leave', Decimal('90'), False, None, True, 'calendar', 0),
        ('PATERNITY', 'Paternity Leave', Decimal('14'), False, None, True, 'calendar', 0),
        ('COMPASSIONATE', 'Compassionate Leave', Decimal('5'), False, None, True, 'working', 0),
        ('UNPAID', 'Unpaid Leave', Decimal('0'), False, None, False, 'working', 0),
    ]
    for code, name, days_py, accrues, dpm, is_paid, basis, carry_max in leave_specs:
        if (
            db.session.query(LeaveType)
            .filter(LeaveType.company_id == company_id, LeaveType.code == code)
            .first()
        ):
            continue
        db.session.add(
            LeaveType(
                company_id=company_id,
                code=code,
                name=name,
                days_per_year=days_py,
                accrues_monthly=accrues,
                days_per_month=dpm,
                requires_approval=True,
                requires_document=False,
                days_count_basis=basis,
                is_paid=is_paid,
                min_days_request=None,
                carry_forward_max=carry_max,
                is_active=True,
            )
        )

    for code, name, track_expiry in [
        ('PERSONAL', 'Personal Documents', True),
        ('WORK', 'Work Related Documents', True),
        ('PERFORMANCE', 'Performance Management', False),
        ('EDUCATION', 'Education Documents', False),
        ('OTHER', 'Others', False),
    ]:
        if (
            db.session.query(DocumentCategory)
            .filter(DocumentCategory.company_id == company_id, DocumentCategory.code == code)
            .first()
        ):
            continue
        db.session.add(
            DocumentCategory(company_id=company_id, code=code, name=name, track_expiry=track_expiry)
        )

    if cc == 'KE':
        eff_from = date(2026, 1, 1)
        if not (
            db.session.query(StatutoryRate)
            .filter(
                StatutoryRate.company_id == company_id,
                StatutoryRate.country_code == cc,
                StatutoryRate.code == 'SHIF_PERCENT',
                StatutoryRate.effective_from == eff_from,
            )
            .first()
        ):
            for code, value, desc in [
                ('SHIF_PERCENT', 2.75, 'SHIF 2.75% of gross'),
                ('SHIF_MIN_AMOUNT', 300, 'SHIF minimum monthly deduction amount'),
                ('HOUSING_LEVY_PERCENT', 1.5, 'Housing Levy 1.5% employee'),
                ('PERSONAL_RELIEF', 2400, 'Monthly personal relief (KES)'),
            ]:
                db.session.add(
                    StatutoryRate(
                        company_id=company_id,
                        country_code=cc,
                        code=code,
                        effective_from=eff_from,
                        value=value,
                        description=desc,
                    )
                )

        if not (
            db.session.query(PayeBracket)
            .filter(
                PayeBracket.company_id == company_id,
                PayeBracket.country_code == cc,
                PayeBracket.effective_from == eff_from,
            )
            .first()
        ):
            for order, min_a, max_a, rate in [
                (1, 0, 24000, 10),
                (2, 24001, 32333, 25),
                (3, 32334, 500000, 30),
                (4, 500001, 800000, 32.5),
                (5, 800001, None, 35),
            ]:
                db.session.add(
                    PayeBracket(
                        company_id=company_id,
                        country_code=cc,
                        effective_from=eff_from,
                        bracket_order=order,
                        min_amount=min_a,
                        max_amount=max_a,
                        rate_percent=rate,
                    )
                )

        # NSSF tier bands: use an early effective_from so draft payroll for past months
        # still picks up tiers (strict as_at filtering is in statutory_service with fallback).
        nssf_from = date(2024, 1, 1)
        if not (
            db.session.query(NssfTier)
            .filter(
                NssfTier.company_id == company_id,
                NssfTier.country_code == cc,
                NssfTier.effective_from == nssf_from,
            )
            .first()
        ):
            db.session.add(
                NssfTier(
                    company_id=company_id,
                    country_code=cc,
                    effective_from=nssf_from,
                    tier_number=1,
                    pensionable_min=0,
                    pensionable_max=9000,
                    employee_percent=6,
                    employer_percent=6,
                    employee_max_amount=540,
                    employer_max_amount=540,
                )
            )
            db.session.add(
                NssfTier(
                    company_id=company_id,
                    country_code=cc,
                    effective_from=nssf_from,
                    tier_number=2,
                    pensionable_min=9001,
                    pensionable_max=108000,
                    employee_percent=6,
                    employer_percent=6,
                    employee_max_amount=5940,
                    employer_max_amount=5940,
                )
            )

    elif cc == 'UG':
        # Uganda: PAYE (URA 2026 monthly resident bands), NSSF 5% / 10% on gross. No SHIF / housing levy.
        # Use early effective_from so payroll for any month picks up the brackets.
        eff_from = date(2024, 1, 1)
        if not (
            db.session.query(StatutoryRate)
            .filter(
                StatutoryRate.company_id == company_id,
                StatutoryRate.country_code == cc,
                StatutoryRate.code == 'NSSF_EMPLOYEE_PERCENT',
                StatutoryRate.effective_from == eff_from,
            )
            .first()
        ):
            for code, value, desc in [
                ('NSSF_EMPLOYEE_PERCENT', 5, 'NSSF employee contribution (% of gross)'),
                ('NSSF_EMPLOYER_PERCENT', 10, 'NSSF employer contribution (% of gross)'),
                ('PERSONAL_RELIEF', 0, 'Uganda monthly PAYE has no personal relief (set 0)'),
            ]:
                db.session.add(
                    StatutoryRate(
                        company_id=company_id,
                        country_code=cc,
                        code=code,
                        effective_from=eff_from,
                        value=value,
                        description=desc,
                    )
                )

        if not (
            db.session.query(PayeBracket)
            .filter(
                PayeBracket.company_id == company_id,
                PayeBracket.country_code == cc,
                PayeBracket.effective_from == eff_from,
            )
            .first()
        ):
            for order, min_a, max_a, rate in [
                (1, 0, 335000, 0),
                (2, 335001, 410000, 10),
                (3, 410001, 10000000, 20),
                (4, 10000001, None, 30),
            ]:
                db.session.add(
                    PayeBracket(
                        company_id=company_id,
                        country_code=cc,
                        effective_from=eff_from,
                        bracket_order=order,
                        min_amount=min_a,
                        max_amount=max_a,
                        rate_percent=rate,
                    )
                )

    elif cc == 'TZ':
        # Tanzania Mainland: PAYE (TRA monthly bands), NSSF 10% / 10% on gross, SDL 3.5%, WCF 1% (employer).
        eff_from = date(2024, 1, 1)
        if not (
            db.session.query(StatutoryRate)
            .filter(
                StatutoryRate.company_id == company_id,
                StatutoryRate.country_code == cc,
                StatutoryRate.code == 'NSSF_EMPLOYEE_PERCENT',
                StatutoryRate.effective_from == eff_from,
            )
            .first()
        ):
            for code, value, desc in [
                ('NSSF_EMPLOYEE_PERCENT', 10, 'NSSF employee contribution (% of gross)'),
                ('NSSF_EMPLOYER_PERCENT', 10, 'NSSF employer contribution (% of gross)'),
                ('SDL_PERCENT', 3.5, 'Skills Development Levy — employer (% of gross)'),
                ('WCF_PERCENT', 1, 'Workers Compensation Fund — employer private sector (% of gross)'),
                ('SURTAX_PERCENT', 10, 'Surtax on monthly income above threshold (%)'),
                ('SURTAX_THRESHOLD', 10000000, 'Monthly income threshold for surtax (TZS)'),
                ('PERSONAL_RELIEF', 0, 'Tanzania monthly PAYE has no personal relief (set 0)'),
            ]:
                db.session.add(
                    StatutoryRate(
                        company_id=company_id,
                        country_code=cc,
                        code=code,
                        effective_from=eff_from,
                        value=value,
                        description=desc,
                    )
                )

        if not (
            db.session.query(PayeBracket)
            .filter(
                PayeBracket.company_id == company_id,
                PayeBracket.country_code == cc,
                PayeBracket.effective_from == eff_from,
            )
            .first()
        ):
            for order, min_a, max_a, rate in [
                (1, 0, 270000, 0),
                (2, 270001, 520000, 8),
                (3, 520001, 760000, 20),
                (4, 760001, 1000000, 25),
                (5, 1000001, None, 30),
            ]:
                db.session.add(
                    PayeBracket(
                        company_id=company_id,
                        country_code=cc,
                        effective_from=eff_from,
                        bracket_order=order,
                        min_amount=min_a,
                        max_amount=max_a,
                        rate_percent=rate,
                    )
                )

    sync_leave_carry_forward_policy(company_id, commit=False)
    sync_leave_min_request_policy(company_id, commit=False)

    db.session.commit()


def sync_leave_min_request_policy(company_id: int | None = None, *, commit: bool = True) -> int:
    """Clear legacy default minimum (0.5 day) so quarter-day requests are allowed."""
    q = db.session.query(LeaveType).filter(LeaveType.min_days_request == Decimal('0.5'))
    if company_id is not None:
        q = q.filter(LeaveType.company_id == company_id)
    count = q.update({LeaveType.min_days_request: None}, synchronize_session='fetch')
    if commit and count:
        db.session.commit()
    return count


def sync_leave_carry_forward_policy(company_id: int | None = None, *, commit: bool = True) -> int:
    """
    Enforce no year-end leave carry when LEAVE_ALLOW_CARRY_FORWARD is false.
    Returns number of leave types updated.
    """
    from flask import current_app

    if current_app.config.get('LEAVE_ALLOW_CARRY_FORWARD', False):
        return 0
    q = db.session.query(LeaveType).filter(LeaveType.carry_forward_max != 0)
    if company_id is not None:
        q = q.filter(LeaveType.company_id == company_id)
    count = q.update({LeaveType.carry_forward_max: 0}, synchronize_session='fetch')
    if commit and count:
        db.session.commit()
    return count
