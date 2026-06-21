"""Company asset register under Organization."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from app.decorators.permissions import permission_required
from app.extensions import db
from app.forms.asset_forms import AssignAssetForm, AssetCategoryForm, CompanyAssetForm, ReturnAssetForm
from app.models.company_asset import (
    ASSET_STATUS_ASSIGNED,
    ASSET_STATUS_DISPOSED,
    ASSET_STATUS_LABELS,
    ASSET_STATUS_LOST,
    ASSET_STATUS_NOT_ASSIGNED,
    ASSET_STATUS_REPAIR,
    AssetCategory,
    CompanyAsset,
)
from app.models.employee import Employee
from app.services.asset_service import (
    active_employee_choices,
    assign_asset,
    assets_query,
    category_choices,
    employee_asset_rows,
    ensure_default_asset_categories,
    get_asset_for_company,
    return_asset,
    set_asset_status,
    user_can_manage_assets,
    user_can_view_asset,
    user_can_view_employee_assets,
    user_sees_all_assets,
)
from app.utils.tenant import require_company_id

company_assets_bp = Blueprint('company_assets', __name__)


def _status_choices(*, include_assigned: bool = True) -> list[tuple[str, str]]:
    choices = [
        (ASSET_STATUS_NOT_ASSIGNED, ASSET_STATUS_LABELS[ASSET_STATUS_NOT_ASSIGNED]),
        (ASSET_STATUS_REPAIR, ASSET_STATUS_LABELS[ASSET_STATUS_REPAIR]),
        (ASSET_STATUS_LOST, ASSET_STATUS_LABELS[ASSET_STATUS_LOST]),
        (ASSET_STATUS_DISPOSED, ASSET_STATUS_LABELS[ASSET_STATUS_DISPOSED]),
    ]
    if include_assigned:
        choices.insert(1, (ASSET_STATUS_ASSIGNED, ASSET_STATUS_LABELS[ASSET_STATUS_ASSIGNED]))
    return choices


def _populate_asset_form(form: CompanyAssetForm, company_id: int, asset: CompanyAsset | None = None) -> None:
    form.category_id.choices = category_choices(company_id)
    form.status.choices = _status_choices(include_assigned=bool(asset and asset.active_assignment))


@company_assets_bp.route('/')
@login_required
@permission_required('view_assets')
def index():
    cid = require_company_id()
    ensure_default_asset_categories(cid)
    status_filter = (request.args.get('status') or '').strip()
    category_filter = request.args.get('category', type=int)

    q = assets_query(cid, current_user)
    if status_filter and status_filter in ASSET_STATUS_LABELS:
        q = q.filter(CompanyAsset.status == status_filter)
    if category_filter:
        q = q.filter(CompanyAsset.category_id == category_filter)

    assets = q.order_by(CompanyAsset.asset_tag).all()
    team_view = not user_sees_all_assets(current_user)
    return render_template(
        'company_assets/index.html',
        assets=assets,
        status_filter=status_filter,
        category_filter=category_filter,
        categories=category_choices(cid),
        status_labels=ASSET_STATUS_LABELS,
        team_view=team_view,
        can_manage=user_can_manage_assets(current_user),
    )


@company_assets_bp.route('/create', methods=['GET', 'POST'])
@login_required
@permission_required('manage_assets')
def create():
    cid = require_company_id()
    ensure_default_asset_categories(cid)
    form = CompanyAssetForm()
    _populate_asset_form(form, cid)
    if form.validate_on_submit():
        tag = form.asset_tag.data.strip().upper()
        existing = (
            db.session.query(CompanyAsset.id)
            .filter(CompanyAsset.company_id == cid, CompanyAsset.asset_tag == tag)
            .first()
        )
        if existing:
            flash('An asset with this tag already exists.', 'danger')
            return render_template('company_assets/create.html', form=form)
        asset = CompanyAsset(
            company_id=cid,
            category_id=form.category_id.data,
            asset_tag=tag,
            name=(form.name.data or '').strip() or None,
            brand=(form.brand.data or '').strip() or None,
            model=(form.model.data or '').strip() or None,
            serial_number=(form.serial_number.data or '').strip() or None,
            purchase_date=form.purchase_date.data,
            purchase_value=form.purchase_value.data,
            description=(form.description.data or '').strip() or None,
            notes=(form.notes.data or '').strip() or None,
            status=form.status.data,
        )
        if asset.status not in (ASSET_STATUS_NOT_ASSIGNED, ASSET_STATUS_REPAIR):
            asset.status = ASSET_STATUS_NOT_ASSIGNED
        db.session.add(asset)
        db.session.commit()
        flash('Asset created.', 'success')
        return redirect(url_for('company_assets.view', id=asset.id))
    return render_template('company_assets/create.html', form=form)


@company_assets_bp.route('/<int:id>')
@login_required
@permission_required('view_assets')
def view(id):
    cid = require_company_id()
    asset = get_asset_for_company(id, cid)
    if not asset or not user_can_view_asset(current_user, asset, cid):
        flash('Asset not found.', 'danger')
        return redirect(url_for('company_assets.index'))
    return render_template(
        'company_assets/view.html',
        asset=asset,
        return_form=ReturnAssetForm(),
        status_labels=ASSET_STATUS_LABELS,
        can_manage=user_can_manage_assets(current_user),
    )


@company_assets_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('manage_assets')
def edit(id):
    cid = require_company_id()
    asset = get_asset_for_company(id, cid)
    if not asset:
        flash('Asset not found.', 'danger')
        return redirect(url_for('company_assets.index'))

    form = CompanyAssetForm()
    _populate_asset_form(form, cid, asset=asset)
    if form.validate_on_submit():
        tag = form.asset_tag.data.strip().upper()
        existing = (
            db.session.query(CompanyAsset.id)
            .filter(
                CompanyAsset.company_id == cid,
                CompanyAsset.asset_tag == tag,
                CompanyAsset.id != asset.id,
            )
            .first()
        )
        if existing:
            flash('An asset with this tag already exists.', 'danger')
            return render_template('company_assets/edit.html', form=form, asset=asset)
        try:
            if form.status.data != asset.status:
                set_asset_status(asset, form.status.data)
            asset.category_id = form.category_id.data
            asset.asset_tag = tag
            asset.name = (form.name.data or '').strip() or None
            asset.brand = (form.brand.data or '').strip() or None
            asset.model = (form.model.data or '').strip() or None
            asset.serial_number = (form.serial_number.data or '').strip() or None
            asset.purchase_date = form.purchase_date.data
            asset.purchase_value = form.purchase_value.data
            asset.description = (form.description.data or '').strip() or None
            asset.notes = (form.notes.data or '').strip() or None
            db.session.commit()
            flash('Asset updated.', 'success')
            return redirect(url_for('company_assets.view', id=asset.id))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
    elif request.method == 'GET':
        form.category_id.data = asset.category_id
        form.asset_tag.data = asset.asset_tag
        form.name.data = asset.name
        form.brand.data = asset.brand
        form.model.data = asset.model
        form.serial_number.data = asset.serial_number
        form.purchase_date.data = asset.purchase_date
        form.purchase_value.data = asset.purchase_value
        form.description.data = asset.description
        form.notes.data = asset.notes
        form.status.data = asset.status
    return render_template('company_assets/edit.html', form=form, asset=asset)


@company_assets_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('manage_assets')
def delete(id):
    cid = require_company_id()
    asset = get_asset_for_company(id, cid)
    if not asset:
        flash('Asset not found.', 'danger')
        return redirect(url_for('company_assets.index'))
    if asset.active_assignment:
        flash('Return this asset before deleting it.', 'danger')
        return redirect(url_for('company_assets.view', id=id))
    db.session.delete(asset)
    db.session.commit()
    flash('Asset deleted.', 'success')
    return redirect(url_for('company_assets.index'))


@company_assets_bp.route('/<int:id>/assign', methods=['GET', 'POST'])
@login_required
@permission_required('manage_assets')
def assign(id):
    cid = require_company_id()
    asset = get_asset_for_company(id, cid)
    if not asset:
        flash('Asset not found.', 'danger')
        return redirect(url_for('company_assets.index'))
    if asset.active_assignment:
        flash('This asset is already assigned. Return it first.', 'warning')
        return redirect(url_for('company_assets.view', id=id))

    form = AssignAssetForm()
    form.employee_id.choices = active_employee_choices(cid)
    if not form.employee_id.choices:
        flash('No active employees available to assign.', 'warning')
        return redirect(url_for('company_assets.view', id=id))

    if form.validate_on_submit():
        try:
            assign_asset(
                asset,
                employee_id=form.employee_id.data,
                assigned_by_user_id=current_user.id,
                condition_on_issue=form.condition_on_issue.data,
                notes=form.notes.data,
            )
            db.session.commit()
            flash('Asset assigned.', 'success')
            return redirect(url_for('company_assets.view', id=id))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
    return render_template('company_assets/assign.html', form=form, asset=asset)


@company_assets_bp.route('/<int:id>/return', methods=['POST'])
@login_required
@permission_required('manage_assets')
def return_asset_view(id):
    cid = require_company_id()
    asset = get_asset_for_company(id, cid)
    if not asset:
        flash('Asset not found.', 'danger')
        return redirect(url_for('company_assets.index'))

    form = ReturnAssetForm()
    if form.validate_on_submit():
        try:
            return_asset(
                asset,
                returned_by_user_id=current_user.id,
                condition_on_return=form.condition_on_return.data,
                notes=form.notes.data,
            )
            db.session.commit()
            flash('Asset marked as returned.', 'success')
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
    else:
        flash('Could not return asset. Check the form and try again.', 'danger')
    return redirect(url_for('company_assets.view', id=id))


@company_assets_bp.route('/employee/<int:employee_id>')
@login_required
@permission_required('view_assets')
def employee_assets(employee_id):
    cid = require_company_id()
    employee = db.session.get(Employee, employee_id)
    if not employee or employee.company_id != cid:
        flash('Employee not found.', 'danger')
        return redirect(url_for('company_assets.index'))
    if not user_can_view_employee_assets(current_user, employee, cid):
        abort(403)

    include_history = request.args.get('history', type=int) == 1
    rows = employee_asset_rows(employee_id, include_history=include_history)
    return render_template(
        'company_assets/employee_assets.html',
        employee=employee,
        assignments=rows,
        include_history=include_history,
        status_labels=ASSET_STATUS_LABELS,
        can_manage=user_can_manage_assets(current_user),
    )


@company_assets_bp.route('/categories', methods=['GET', 'POST'])
@login_required
@permission_required('manage_assets')
def categories():
    cid = require_company_id()
    ensure_default_asset_categories(cid)
    form = AssetCategoryForm()
    if form.validate_on_submit():
        code = form.code.data.strip().lower().replace(' ', '_')
        name = form.name.data.strip()
        exists = (
            db.session.query(AssetCategory.id)
            .filter(AssetCategory.company_id == cid, AssetCategory.code == code)
            .first()
        )
        if exists:
            flash('A category with this code already exists.', 'danger')
        else:
            db.session.add(AssetCategory(company_id=cid, code=code, name=name, is_active=True))
            db.session.commit()
            flash('Category added.', 'success')
            return redirect(url_for('company_assets.categories'))
    categories_list = (
        db.session.query(AssetCategory)
        .filter(AssetCategory.company_id == cid)
        .order_by(AssetCategory.name)
        .all()
    )
    return render_template('company_assets/categories.html', form=form, categories=categories_list)
