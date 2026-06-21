"""Secure file upload handling for employee documents."""
import os
import uuid
from pathlib import Path
from flask import current_app


ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png'}


def allowed_file(filename: str) -> bool:
    """Check extension is allowed."""
    if not filename or '.' not in filename:
        return False
    return filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def secure_filename_employee(employee_id: int, original_filename: str) -> str:
    """Generate unique secure path: employees/{employee_id}/{uuid}.ext."""
    if not allowed_file(original_filename):
        raise ValueError(f'File type not allowed. Allowed: {", ".join(ALLOWED_EXTENSIONS)}')
    ext = original_filename.rsplit('.', 1)[1].lower()
    unique = uuid.uuid4().hex[:12]
    return os.path.join('employees', str(employee_id), f'{unique}.{ext}')


def get_upload_path(relative_path: str) -> str:
    """Full path for a relative path under UPLOAD_FOLDER."""
    root = current_app.config['UPLOAD_FOLDER']
    return os.path.join(root, relative_path)


def ensure_employee_upload_dir(employee_id: int) -> str:
    """Create and return directory for employee documents."""
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'employees', str(employee_id))
    Path(path).mkdir(parents=True, exist_ok=True)
    return path
