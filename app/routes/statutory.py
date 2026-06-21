"""Statutory rate configuration — per company, scoped by country (one UI section per ISO2 country)."""
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required
from sqlalchemy import distinct

from app.extensions import db
from app.models.statutory import StatutoryRate, PayeBracket, NssfTier
from app.models.company import Branch
from app.forms.settings_forms import StatutoryRateForm, PayeBracketForm, NssfTierForm
from app.decorators.permissions import permission_required
from app.utils.tenant import require_company_id
from app.utils.currency import currency_for_country

statutory_bp = Blueprint('statutory', __name__)


def _cc(raw) -> str:
    return (raw or 'KE').strip().upper()[:2]


def _parse_country_segment(value: str | None) -> str | None:
    if not value or len(value) != 2:
        return None
    s = value.strip().upper()
    if len(s) != 2 or not s.isalpha():
        return None
    return s


def _country_codes_for_company(cid: int) -> list[str]:
    """Countries that appear on branches or in any statutory table for this tenant."""
    codes: set[str] = set()
    for (cc,) in db.session.query(distinct(Branch.country_code)).filter(Branch.company_id == cid).all():
        if cc:
            codes.add(str(cc).strip().upper()[:2])
    for model in (StatutoryRate, PayeBracket, NssfTier):
        for (cc,) in db.session.query(distinct(model.country_code)).filter(model.company_id == cid).all():
            if cc:
                codes.add(str(cc).strip().upper()[:2])
    return sorted(codes)


@statutory_bp.route('/')
@login_required
@permission_required('manage_statutory')
def index():
    """Pick a country to manage statutory rates for that jurisdiction."""
    cid = require_company_id()
    countries = _country_codes_for_company(cid)
    if not countries:
        countries = ['KE']
    rows = []
    for cc in countries:
        rows.append(
            {
                'code': cc,
                'currency': currency_for_country(cc),
                'rates': db.session.query(StatutoryRate)
                .filter(StatutoryRate.company_id == cid, StatutoryRate.country_code == cc)
                .count(),
                'brackets': db.session.query(PayeBracket)
                .filter(PayeBracket.company_id == cid, PayeBracket.country_code == cc)
                .count(),
                'tiers': db.session.query(NssfTier)
                .filter(NssfTier.company_id == cid, NssfTier.country_code == cc)
                .count(),
            }
        )
    return render_template('statutory/hub.html', rows=rows)


@statutory_bp.route('/country/<country_code>/')
@login_required
@permission_required('manage_statutory')
def country_index(country_code):
    cc = _parse_country_segment(country_code)
    if not cc:
        abort(404)
    cid = require_company_id()
    currency = currency_for_country(cc)
    rates = (
        db.session.query(StatutoryRate)
        .filter(StatutoryRate.company_id == cid, StatutoryRate.country_code == cc)
        .order_by(StatutoryRate.code, StatutoryRate.effective_from.desc())
        .all()
    )
    brackets = (
        db.session.query(PayeBracket)
        .filter(PayeBracket.company_id == cid, PayeBracket.country_code == cc)
        .order_by(PayeBracket.effective_from.desc(), PayeBracket.bracket_order)
        .all()
    )
    tiers = (
        db.session.query(NssfTier)
        .filter(NssfTier.company_id == cid, NssfTier.country_code == cc)
        .order_by(NssfTier.effective_from.desc(), NssfTier.tier_number)
        .all()
    )
    countries_nav = _country_codes_for_company(cid) or [cc]
    return render_template(
        'statutory/index.html',
        country_code=cc,
        currency_code=currency,
        rates=rates,
        brackets=brackets,
        tiers=tiers,
        countries_nav=countries_nav,
    )


@statutory_bp.route('/country/<country_code>/rate/add', methods=['GET', 'POST'])
@login_required
@permission_required('manage_statutory')
def rate_add(country_code):
    cc = _parse_country_segment(country_code)
    if not cc:
        abort(404)
    form = StatutoryRateForm()
    if request.method == 'GET':
        form.country_code.data = cc
    if form.validate_on_submit():
        cid = require_company_id()
        r = StatutoryRate(
            company_id=cid,
            country_code=_cc(form.country_code.data),
            code=form.code.data,
            effective_from=form.effective_from.data,
            effective_to=form.effective_to.data,
            value=form.value.data,
            description=form.description.data,
        )
        db.session.add(r)
        db.session.commit()
        flash('Rate added.', 'success')
        return redirect(url_for('statutory.country_index', country_code=r.country_code))
    return render_template('statutory/rate_form.html', form=form, rate=None, country_code=cc, currency_code=currency_for_country(cc))


@statutory_bp.route('/rate/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('manage_statutory')
def rate_edit(id):
    r = db.session.get(StatutoryRate, id)
    cid = require_company_id()
    if not r or r.company_id != cid:
        flash('Rate not found.', 'danger')
        return redirect(url_for('statutory.index'))
    form = StatutoryRateForm()
    if form.validate_on_submit():
        r.code = form.code.data
        r.country_code = _cc(form.country_code.data)
        r.effective_from = form.effective_from.data
        r.effective_to = form.effective_to.data
        r.value = form.value.data
        r.description = form.description.data
        db.session.commit()
        flash('Rate updated.', 'success')
        return redirect(url_for('statutory.country_index', country_code=r.country_code))
    if request.method == 'GET':
        form.code.data = r.code
        form.country_code.data = r.country_code or 'KE'
        form.effective_from.data = r.effective_from
        form.effective_to.data = r.effective_to
        form.value.data = float(r.value) if r.value is not None else None
        form.description.data = r.description or ''
    return render_template(
        'statutory/rate_form.html',
        form=form,
        rate=r,
        country_code=r.country_code,
        currency_code=currency_for_country(r.country_code),
    )


@statutory_bp.route('/rate/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('manage_statutory')
def rate_delete(id):
    r = db.session.get(StatutoryRate, id)
    if not r or r.company_id != require_company_id():
        flash('Rate not found.', 'danger')
        return redirect(url_for('statutory.index'))
    cc = r.country_code
    db.session.delete(r)
    db.session.commit()
    flash('Rate deleted.', 'success')
    return redirect(url_for('statutory.country_index', country_code=cc))


@statutory_bp.route('/country/<country_code>/paye/add', methods=['GET', 'POST'])
@login_required
@permission_required('manage_statutory')
def paye_add(country_code):
    cc = _parse_country_segment(country_code)
    if not cc:
        abort(404)
    form = PayeBracketForm()
    if request.method == 'GET':
        form.country_code.data = cc
    if form.validate_on_submit():
        cid = require_company_id()
        b = PayeBracket(
            company_id=cid,
            country_code=_cc(form.country_code.data),
            effective_from=form.effective_from.data,
            effective_to=form.effective_to.data,
            bracket_order=form.bracket_order.data,
            min_amount=form.min_amount.data,
            max_amount=form.max_amount.data,
            rate_percent=form.rate_percent.data,
        )
        db.session.add(b)
        db.session.commit()
        flash('PAYE bracket added.', 'success')
        return redirect(url_for('statutory.country_index', country_code=b.country_code))
    if request.method == 'POST' and form.errors:
        flash('Please fix the highlighted PAYE form errors.', 'danger')
    return render_template(
        'statutory/paye_form.html',
        form=form,
        bracket=None,
        country_code=cc,
        currency_code=currency_for_country(cc),
    )


@statutory_bp.route('/paye/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('manage_statutory')
def paye_edit(id):
    b = db.session.get(PayeBracket, id)
    if not b or b.company_id != require_company_id():
        flash('PAYE bracket not found.', 'danger')
        return redirect(url_for('statutory.index'))
    form = PayeBracketForm()
    if form.validate_on_submit():
        b.country_code = _cc(form.country_code.data)
        b.effective_from = form.effective_from.data
        b.effective_to = form.effective_to.data
        b.bracket_order = form.bracket_order.data
        b.min_amount = form.min_amount.data
        b.max_amount = form.max_amount.data
        b.rate_percent = form.rate_percent.data
        db.session.commit()
        flash('PAYE bracket updated.', 'success')
        return redirect(url_for('statutory.country_index', country_code=b.country_code))
    if request.method == 'POST' and form.errors:
        flash('Please fix the highlighted PAYE form errors.', 'danger')
    if request.method == 'GET':
        form.country_code.data = b.country_code or 'KE'
        form.effective_from.data = b.effective_from
        form.effective_to.data = b.effective_to
        form.bracket_order.data = b.bracket_order
        form.min_amount.data = float(b.min_amount) if b.min_amount is not None else None
        form.max_amount.data = float(b.max_amount) if b.max_amount is not None else None
        form.rate_percent.data = float(b.rate_percent) if b.rate_percent is not None else None
    return render_template(
        'statutory/paye_form.html',
        form=form,
        bracket=b,
        country_code=b.country_code,
        currency_code=currency_for_country(b.country_code),
    )


@statutory_bp.route('/paye/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('manage_statutory')
def paye_delete(id):
    b = db.session.get(PayeBracket, id)
    if not b or b.company_id != require_company_id():
        flash('PAYE bracket not found.', 'danger')
        return redirect(url_for('statutory.index'))
    cc = b.country_code
    db.session.delete(b)
    db.session.commit()
    flash('PAYE bracket deleted.', 'success')
    return redirect(url_for('statutory.country_index', country_code=cc))


@statutory_bp.route('/country/<country_code>/tier/add', methods=['GET', 'POST'])
@login_required
@permission_required('manage_statutory')
def nssf_tier_add(country_code):
    cc = _parse_country_segment(country_code)
    if not cc:
        abort(404)
    form = NssfTierForm()
    if request.method == 'GET':
        form.country_code.data = cc
    if form.validate_on_submit():
        cid = require_company_id()
        t = NssfTier(
            company_id=cid,
            country_code=_cc(form.country_code.data),
            effective_from=form.effective_from.data,
            effective_to=form.effective_to.data,
            tier_number=form.tier_number.data,
            pensionable_min=form.pensionable_min.data,
            pensionable_max=form.pensionable_max.data,
            employee_percent=form.employee_percent.data,
            employer_percent=form.employer_percent.data,
            employee_max_amount=form.employee_max_amount.data,
            employer_max_amount=form.employer_max_amount.data,
        )
        db.session.add(t)
        db.session.commit()
        flash('NSSF tier added.', 'success')
        return redirect(url_for('statutory.country_index', country_code=t.country_code))
    if request.method == 'POST' and form.errors:
        flash('Please fix the highlighted NSSF tier form errors.', 'danger')
    return render_template(
        'statutory/nssf_form.html',
        form=form,
        tier=None,
        country_code=cc,
        currency_code=currency_for_country(cc),
    )


@statutory_bp.route('/tier/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('manage_statutory')
def nssf_tier_edit(id):
    t = db.session.get(NssfTier, id)
    if not t or t.company_id != require_company_id():
        flash('NSSF tier not found.', 'danger')
        return redirect(url_for('statutory.index'))
    form = NssfTierForm()
    if form.validate_on_submit():
        t.country_code = _cc(form.country_code.data)
        t.effective_from = form.effective_from.data
        t.effective_to = form.effective_to.data
        t.tier_number = form.tier_number.data
        t.pensionable_min = form.pensionable_min.data
        t.pensionable_max = form.pensionable_max.data
        t.employee_percent = form.employee_percent.data
        t.employer_percent = form.employer_percent.data
        t.employee_max_amount = form.employee_max_amount.data
        t.employer_max_amount = form.employer_max_amount.data
        db.session.commit()
        flash('NSSF tier updated.', 'success')
        return redirect(url_for('statutory.country_index', country_code=t.country_code))
    if request.method == 'POST' and form.errors:
        flash('Please fix the highlighted NSSF tier form errors.', 'danger')
    if request.method == 'GET':
        form.country_code.data = t.country_code or 'KE'
        form.effective_from.data = t.effective_from
        form.effective_to.data = t.effective_to
        form.tier_number.data = t.tier_number
        form.pensionable_min.data = float(t.pensionable_min) if t.pensionable_min is not None else None
        form.pensionable_max.data = float(t.pensionable_max) if t.pensionable_max is not None else None
        form.employee_percent.data = float(t.employee_percent) if t.employee_percent is not None else None
        form.employer_percent.data = float(t.employer_percent) if t.employer_percent is not None else None
        form.employee_max_amount.data = float(t.employee_max_amount) if t.employee_max_amount is not None else None
        form.employer_max_amount.data = float(t.employer_max_amount) if t.employer_max_amount is not None else None
    return render_template(
        'statutory/nssf_form.html',
        form=form,
        tier=t,
        country_code=t.country_code,
        currency_code=currency_for_country(t.country_code),
    )


@statutory_bp.route('/tier/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('manage_statutory')
def nssf_tier_delete(id):
    t = db.session.get(NssfTier, id)
    if not t or t.company_id != require_company_id():
        flash('NSSF tier not found.', 'danger')
        return redirect(url_for('statutory.index'))
    cc = t.country_code
    db.session.delete(t)
    db.session.commit()
    flash('NSSF tier deleted.', 'success')
    return redirect(url_for('statutory.country_index', country_code=cc))
