"""Sync and query employee next-of-kin and supervisor assignments."""
from __future__ import annotations

from flask import Request

from app.extensions import db
from app.models.employee import Employee
from app.models.employee_relations import EmployeeNextOfKin, EmployeeSupervisor
from app.utils.validators import normalize_phone


def employee_supervisor_ids(employee: Employee | None) -> list[int]:
    """Supervisor employee IDs from junction table, with manager_id fallback."""
    if not employee:
        return []
    ids = [link.supervisor_id for link in (employee.supervisor_links or [])]
    if ids:
        return ids
    if employee.manager_id:
        return [employee.manager_id]
    return []


def employee_supervisors(employee: Employee | None) -> list[Employee]:
    """Supervisor Employee records in assignment order."""
    if not employee:
        return []
    if employee.supervisor_links:
        return [link.supervisor for link in employee.supervisor_links if link.supervisor]
    if employee.manager:
        return [employee.manager]
    return []


def employee_supervisor_names(employee: Employee | None) -> str:
    names = [s.full_name for s in employee_supervisors(employee)]
    return ', '.join(names) if names else ''


def employee_has_any_supervisor(employee: Employee | None) -> bool:
    return bool(employee_supervisor_ids(employee))


def employee_has_supervisor(employee: Employee | None, supervisor_employee_id: int | None) -> bool:
    if not employee or not supervisor_employee_id:
        return False
    return int(supervisor_employee_id) in employee_supervisor_ids(employee)


def subordinate_employee_ids(supervisor_employee_id: int, company_id: int) -> set[int]:
    """Active employees who report to this supervisor (links + legacy manager_id)."""
    ids = {
        row[0]
        for row in db.session.query(EmployeeSupervisor.employee_id)
        .join(Employee, EmployeeSupervisor.employee_id == Employee.id)
        .filter(
            Employee.company_id == company_id,
            EmployeeSupervisor.supervisor_id == supervisor_employee_id,
            Employee.status == 'active',
        )
        .all()
    }
    ids.update(
        row[0]
        for row in db.session.query(Employee.id)
        .filter(
            Employee.company_id == company_id,
            Employee.manager_id == supervisor_employee_id,
            Employee.status == 'active',
        )
        .all()
    )
    return ids


def sync_employee_supervisors(
    employee: Employee,
    supervisor_ids: list[int] | None,
    company_id: int,
) -> None:
    """Replace supervisor links; keep manager_id in sync with the first supervisor."""
    raw = supervisor_ids or []
    cleaned: list[int] = []
    seen: set[int] = set()
    for sid in raw:
        if sid is None:
            continue
        sid = int(sid)
        if sid == employee.id or sid in seen:
            continue
        sup = db.session.get(Employee, sid)
        if not sup or sup.company_id != company_id or sup.status != 'active':
            continue
        seen.add(sid)
        cleaned.append(sid)

    existing = {link.supervisor_id: link for link in list(employee.supervisor_links or [])}
    for sid, link in list(existing.items()):
        if sid not in cleaned:
            db.session.delete(link)

    for sid in cleaned:
        if sid not in existing:
            db.session.add(EmployeeSupervisor(employee_id=employee.id, supervisor_id=sid))

    employee.manager_id = cleaned[0] if cleaned else None


def _nok_rows_from_request(request: Request) -> list[dict]:
    ids = request.form.getlist('nok_id')
    names = request.form.getlist('nok_name')
    relationships = request.form.getlist('nok_relationship')
    phones = request.form.getlist('nok_phone')
    emails = request.form.getlist('nok_email')
    addresses = request.form.getlist('nok_address')
    row_count = max(len(names), len(relationships), len(phones), len(emails), len(addresses), len(ids))
    rows: list[dict] = []
    for i in range(row_count):
        name = (names[i] if i < len(names) else '').strip()
        relationship = (relationships[i] if i < len(relationships) else '').strip()
        phone = (phones[i] if i < len(phones) else '').strip()
        email = (emails[i] if i < len(emails) else '').strip()
        address = (addresses[i] if i < len(addresses) else '').strip()
        raw_id = (ids[i] if i < len(ids) else '').strip()
        if not name and not relationship and not phone and not email and not address:
            continue
        if not name:
            raise ValueError('Each next of kin row must include a name.')
        nok_id = int(raw_id) if raw_id.isdigit() else None
        rows.append({
            'id': nok_id,
            'full_name': name,
            'relationship': relationship or None,
            'phone': phone or None,
            'email': email or None,
            'address': address or None,
        })
    return rows


def sync_employee_next_of_kin(
    employee: Employee,
    request: Request,
    country_code: str | None = None,
) -> None:
    """Replace next-of-kin rows from repeated form fields."""
    rows = _nok_rows_from_request(request)
    existing = {nok.id: nok for nok in list(employee.next_of_kin or [])}
    keep_ids: set[int] = set()

    for row in rows:
        phone = normalize_phone(row['phone'], country_code) if row['phone'] else None
        if row['id'] and row['id'] in existing:
            nok = existing[row['id']]
            nok.full_name = row['full_name']
            nok.relationship = row['relationship']
            nok.phone = phone
            nok.email = row['email']
            nok.address = row['address']
            keep_ids.add(nok.id)
        else:
            db.session.add(EmployeeNextOfKin(
                employee_id=employee.id,
                full_name=row['full_name'],
                relationship=row['relationship'],
                phone=phone,
                email=row['email'],
                address=row['address'],
            ))

    for nok_id, nok in existing.items():
        if nok_id not in keep_ids:
            db.session.delete(nok)
