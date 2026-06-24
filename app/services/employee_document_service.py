"""Employee document storage under EMPLOYEE_UPLOADS_ROOT (sibling of repo)."""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models.document import DocumentCategory, EmployeeDocument
from app.models.employee import Employee

# Fixed categories — folder names on disk match display names.
STANDARD_DOCUMENT_CATEGORIES: tuple[tuple[str, str, bool], ...] = (
    ('PERSONAL', 'Personal Documents', True),
    ('WORK', 'Work Related Documents', True),
    ('EDUCATION', 'Education Documents', False),
    ('OTHER', 'Others', False),
)

STANDARD_CATEGORY_CODES = {code for code, _name, _track in STANDARD_DOCUMENT_CATEGORIES}


def allowed_document_filename(filename: str) -> bool:
    if not filename or '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in current_app.config.get('ALLOWED_EXTENSIONS', {'pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png'})


def _sanitize_folder_segment(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', '', name or '')
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return (cleaned[:120] if cleaned else 'Employee')


def employee_folder_name(employee: Employee) -> str:
    """Disk folder: {id}_{Full Name} under employeeuploads/."""
    return f'{employee.id}_{_sanitize_folder_segment(employee.full_name)}'


def category_folder_name(category: DocumentCategory) -> str:
    return _sanitize_folder_segment(category.name)


def employee_uploads_root() -> Path:
    return Path(current_app.config['EMPLOYEE_UPLOADS_ROOT'])


def ensure_employee_uploads_root() -> Path:
    root = employee_uploads_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def ensure_standard_document_categories(company_id: int) -> list[DocumentCategory]:
    """Ensure the four standard categories exist; return them in display order."""
    existing = {
        row.code: row
        for row in db.session.query(DocumentCategory)
        .filter(DocumentCategory.company_id == company_id)
        .all()
    }
    for code, name, track_expiry in STANDARD_DOCUMENT_CATEGORIES:
        if code not in existing:
            row = DocumentCategory(
                company_id=company_id,
                code=code,
                name=name,
                track_expiry=track_expiry,
            )
            db.session.add(row)
            existing[code] = row
    db.session.commit()
    return [
        existing[code]
        for code, _name, _track in STANDARD_DOCUMENT_CATEGORIES
    ]


def get_category_by_code(company_id: int, category_code: str) -> DocumentCategory | None:
    code = (category_code or '').strip().upper()
    if code not in STANDARD_CATEGORY_CODES:
        return None
    ensure_standard_document_categories(company_id)
    return (
        db.session.query(DocumentCategory)
        .filter(DocumentCategory.company_id == company_id, DocumentCategory.code == code)
        .first()
    )


def ensure_employee_category_dir(employee: Employee, category: DocumentCategory) -> Path:
    ensure_employee_uploads_root()
    path = employee_uploads_root() / employee_folder_name(employee) / category_folder_name(category)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except PermissionError as e:
        root = employee_uploads_root()
        raise PermissionError(
            f'Cannot create folder under {root}. '
            f'On the server run: sudo chown -R 1000:1000 {root}'
        ) from e
    except OSError as e:
        raise OSError(f'Cannot create document folder: {path}') from e
    return path


def original_upload_basename(filename: str | None) -> str:
    """Client-side filename (basename only), preserving spaces and casing."""
    if not filename:
        return 'Document'
    base = filename.replace('\\', '/').rsplit('/', 1)[-1].strip()
    return base or 'Document'


def document_download_filename(doc: EmployeeDocument) -> str:
    return doc.display_filename


def _unique_disk_filename(original_filename: str) -> str:
    safe = secure_filename(original_filename) or 'document'
    base, ext = os.path.splitext(safe)
    if not ext:
        ext = '.bin'
    token = uuid.uuid4().hex[:10]
    return f'{base}_{token}{ext}'


def save_employee_document(
    employee: Employee,
    category: DocumentCategory,
    file_storage: FileStorage,
    *,
    name: str | None = None,
    notes: str | None = None,
) -> EmployeeDocument:
    if not file_storage or not file_storage.filename:
        raise ValueError('No file selected.')
    if not allowed_document_filename(file_storage.filename):
        allowed = ', '.join(sorted(current_app.config.get('ALLOWED_EXTENSIONS', [])))
        raise ValueError(f'File type not allowed. Use: {allowed}.')

    max_bytes = int(current_app.config.get('EMPLOYEE_DOCUMENT_MAX_BYTES', 25 * 1024 * 1024))
    file_storage.stream.seek(0, os.SEEK_END)
    size_bytes = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size_bytes > max_bytes:
        mb = max(1, max_bytes // (1024 * 1024))
        raise ValueError(f'File is too large. Maximum size is {mb} MB.')

    upload_dir = ensure_employee_category_dir(employee, category)
    disk_name = _unique_disk_filename(file_storage.filename)
    full_path = upload_dir / disk_name
    file_storage.save(str(full_path))
    size_bytes = full_path.stat().st_size

    original_filename = original_upload_basename(file_storage.filename)[:255]
    display_name = (name or '').strip() or original_filename
    display_name = display_name[:255]

    rel_path = f'{employee_folder_name(employee)}/{category_folder_name(category)}/{disk_name}'

    doc = EmployeeDocument(
        employee_id=employee.id,
        category_id=category.id,
        name=display_name,
        original_filename=original_filename,
        file_path=rel_path.replace('\\', '/'),
        file_size=size_bytes,
        notes=(notes or '').strip() or None,
    )
    db.session.add(doc)
    db.session.commit()
    return doc


def resolve_document_full_path(doc: EmployeeDocument) -> str | None:
    """Local filesystem path for a document, or None if cloud/URL/missing."""
    rel_path = (doc.file_path or '').replace('\\', '/').lstrip('/').strip()
    if not rel_path or rel_path.startswith('cld::') or rel_path.startswith(('http://', 'https://')):
        return None

    eu_root = employee_uploads_root().resolve()
    candidate = (eu_root / rel_path).resolve()
    if str(candidate).startswith(str(eu_root) + os.sep) and candidate.is_file():
        return str(candidate)

    upload_root = Path(current_app.config['UPLOAD_FOLDER']).resolve()
    legacy = (upload_root / rel_path).resolve()
    if str(legacy).startswith(str(upload_root) + os.sep) and legacy.is_file():
        return str(legacy)
    return None


def delete_employee_document(doc: EmployeeDocument) -> None:
    full_path = resolve_document_full_path(doc)
    if full_path and os.path.isfile(full_path):
        try:
            os.remove(full_path)
        except OSError:
            current_app.logger.warning('Could not delete file %s', full_path)
    db.session.delete(doc)
    db.session.commit()


def documents_grouped_by_category(
    employee_id: int,
    categories: list[DocumentCategory],
) -> dict[int, list[EmployeeDocument]]:
    docs = (
        db.session.query(EmployeeDocument)
        .filter(EmployeeDocument.employee_id == employee_id)
        .order_by(EmployeeDocument.created_at.desc())
        .all()
    )
    by_id = {c.id: c for c in categories}
    grouped: dict[int, list[EmployeeDocument]] = {c.id: [] for c in categories}
    other_id = next((c.id for c in categories if c.code == 'OTHER'), None)
    for doc in docs:
        if doc.category_id and doc.category_id in grouped:
            grouped[doc.category_id].append(doc)
        elif other_id is not None:
            grouped[other_id].append(doc)
    return grouped
