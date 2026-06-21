"""Company asset register: list scope, assign, return."""
from __future__ import annotations

from datetime import date, datetime

from flask_login import UserMixin
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.company_asset import (
    ASSET_STATUS_ASSIGNED,
    ASSET_STATUS_DISPOSED,
    ASSET_STATUS_LOST,
    ASSET_STATUS_NOT_ASSIGNED,
    ASSET_STATUS_REPAIR,
    AssetAssignment,
    AssetCategory,
    CompanyAsset,
)
from app.models.employee import Employee
from app.services.employee_relations_service import subordinate_employee_ids


DEFAULT_ASSET_CATEGORIES = [
    ('laptop', 'Laptop'),
    ('monitor', 'Monitor'),
    ('phone', 'Phone'),
    ('tablet', 'Tablet'),
    ('vehicle', 'Vehicle'),
    ('access_card', 'Access card'),
    ('other', 'Other'),
]


def ensure_default_asset_categories(company_id: int) -> None:
    for code, name in DEFAULT_ASSET_CATEGORIES:
        exists = (
            db.session.query(AssetCategory.id)
            .filter(AssetCategory.company_id == company_id, AssetCategory.code == code)
            .first()
        )
        if not exists:
            db.session.add(AssetCategory(company_id=company_id, code=code, name=name, is_active=True))
    db.session.commit()


def user_can_manage_assets(user: UserMixin) -> bool:
    return bool(getattr(user, 'is_superuser', False) or user.has_permission('manage_assets'))


def user_sees_all_assets(user: UserMixin) -> bool:
    if getattr(user, 'is_superuser', False):
        return True
    if user.has_permission('manage_assets'):
        return True
    if user.has_permission('edit_employees') or user.has_permission('create_employees'):
        return True
    return False


def team_employee_ids_for_user(user: UserMixin, company_id: int) -> set[int]:
    if not getattr(user, 'employee_id', None):
        return set()
    return subordinate_employee_ids(int(user.employee_id), company_id)


def assets_query(company_id: int, user: UserMixin):
    q = (
        db.session.query(CompanyAsset)
        .options(
            joinedload(CompanyAsset.category),
            joinedload(CompanyAsset.assignments).joinedload(AssetAssignment.employee),
        )
        .filter(CompanyAsset.company_id == company_id)
    )
    if user_sees_all_assets(user):
        return q
    team_ids = team_employee_ids_for_user(user, company_id)
    if not team_ids:
        return q.filter(CompanyAsset.id == -1)
    active_asset_ids = [
        row[0]
        for row in (
            db.session.query(AssetAssignment.asset_id)
            .filter(
                AssetAssignment.employee_id.in_(team_ids),
                AssetAssignment.returned_at.is_(None),
            )
            .all()
        )
    ]
    if not active_asset_ids:
        return q.filter(CompanyAsset.id == -1)
    return q.filter(CompanyAsset.id.in_(active_asset_ids))


def get_asset_for_company(asset_id: int, company_id: int) -> CompanyAsset | None:
    return (
        db.session.query(CompanyAsset)
        .options(
            joinedload(CompanyAsset.category),
            joinedload(CompanyAsset.assignments).joinedload(AssetAssignment.employee),
        )
        .filter(CompanyAsset.id == asset_id, CompanyAsset.company_id == company_id)
        .first()
    )


def user_can_view_asset(user: UserMixin, asset: CompanyAsset, company_id: int) -> bool:
    if asset is None or asset.company_id != company_id:
        return False
    if user_sees_all_assets(user):
        return True
    active = asset.active_assignment
    if not active:
        return False
    return int(active.employee_id) in team_employee_ids_for_user(user, company_id)


def user_can_view_employee_assets(user: UserMixin, employee: Employee, company_id: int) -> bool:
    if employee is None or employee.company_id != company_id:
        return False
    if user_sees_all_assets(user):
        return True
    return int(employee.id) in team_employee_ids_for_user(user, company_id)


def employee_asset_rows(employee_id: int, *, include_history: bool = False) -> list[AssetAssignment]:
    q = (
        db.session.query(AssetAssignment)
        .options(joinedload(AssetAssignment.asset).joinedload(CompanyAsset.category))
        .filter(AssetAssignment.employee_id == employee_id)
        .order_by(AssetAssignment.assigned_at.desc())
    )
    if not include_history:
        q = q.filter(AssetAssignment.returned_at.is_(None))
    return q.all()


def assign_asset(
    asset: CompanyAsset,
    *,
    employee_id: int,
    assigned_by_user_id: int | None,
    condition_on_issue: str | None = None,
    notes: str | None = None,
) -> AssetAssignment:
    if asset.status in (ASSET_STATUS_LOST, ASSET_STATUS_DISPOSED):
        raise ValueError('This asset cannot be assigned in its current status.')
    if asset.active_assignment:
        raise ValueError('Return the asset from the current assignee before assigning again.')

    employee = db.session.get(Employee, employee_id)
    if not employee or employee.company_id != asset.company_id:
        raise ValueError('Select a valid employee in your organization.')

    now = datetime.utcnow()
    row = AssetAssignment(
        asset_id=asset.id,
        employee_id=employee_id,
        assigned_at=now,
        condition_on_issue=(condition_on_issue or '').strip() or None,
        notes=(notes or '').strip() or None,
        assigned_by_user_id=assigned_by_user_id,
        created_at=now,
        updated_at=now,
    )
    db.session.add(row)
    asset.status = ASSET_STATUS_ASSIGNED
    asset.updated_at = now
    return row


def return_asset(
    asset: CompanyAsset,
    *,
    returned_by_user_id: int | None,
    condition_on_return: str | None = None,
    notes: str | None = None,
) -> AssetAssignment:
    active = asset.active_assignment
    if not active:
        raise ValueError('This asset is not currently assigned.')

    now = datetime.utcnow()
    active.returned_at = now
    active.condition_on_return = (condition_on_return or '').strip() or None
    if notes:
        existing = (active.notes or '').strip()
        active.notes = (existing + '\n' + notes.strip()).strip() if existing else notes.strip()
    active.returned_by_user_id = returned_by_user_id
    active.updated_at = now
    asset.status = ASSET_STATUS_NOT_ASSIGNED
    asset.updated_at = now
    return active


def set_asset_status(asset: CompanyAsset, status: str) -> None:
    if status == ASSET_STATUS_ASSIGNED and not asset.active_assignment:
        raise ValueError('Assign the asset to an employee first.')
    if status in (ASSET_STATUS_NOT_ASSIGNED, ASSET_STATUS_REPAIR) and asset.active_assignment:
        raise ValueError('Return the asset before changing to this status.')
    if status in (ASSET_STATUS_LOST, ASSET_STATUS_DISPOSED) and asset.active_assignment:
        raise ValueError('Return the asset before marking it lost or disposed.')
    asset.status = status
    asset.updated_at = datetime.utcnow()


def active_employee_choices(company_id: int, exclude_assigned_only: bool = False) -> list[tuple[int, str]]:
    employees = (
        db.session.query(Employee)
        .filter(Employee.company_id == company_id, Employee.status == 'active')
        .order_by(Employee.last_name, Employee.first_name)
        .all()
    )
    return [(e.id, e.full_name) for e in employees]


def category_choices(company_id: int) -> list[tuple[int, str]]:
    rows = (
        db.session.query(AssetCategory)
        .filter(AssetCategory.company_id == company_id, AssetCategory.is_active.is_(True))
        .order_by(AssetCategory.name)
        .all()
    )
    return [(c.id, c.name) for c in rows]
