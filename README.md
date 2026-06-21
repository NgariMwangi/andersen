# HRMS Kenya

Production-ready monolithic Human Resource Management System for Kenyan markets, built with Flask. Compliant with Kenyan statutory requirements (PAYE, NSSF, SHIF, Housing Levy) as of 2026.

## Features

- **Statutory compliance**: Dynamic rate configuration for PAYE, NSSF (Tier I/II), SHIF (2.75%), Housing Levy (1.5%). Rates stored in DB with effective dates—no code change when legislation changes.
- **Immutable audit trail**: All sensitive changes (payroll, employee, statutory) logged with user, timestamp, and before/after values. Audit logs cannot be modified or deleted.
- **Role-based access**: ADMIN, HR_MANAGER, HR_STAFF, MANAGER, EMPLOYEE with granular permissions.
- **Employee lifecycle**: Full employee master data, Kenyan identifiers (KRA PIN, NSSF, NHIF/SHIF), documents, salary, bank details.
- **Payroll**: Run payroll by month, auto-calculate statutory deductions, pro-rata for mid-month join/exit, approval workflow, payslips.
- **Leave**: Leave types (annual, sick, maternity, paternity, etc.), balances, request/approval workflow.
- **Reports**: Employee list, payroll summary, statutory reports (P9, NSSF, SHIF, PAYE returns).

## Tech Stack

- **Backend**: Flask 2.3+, Python 3.11+
- **Database**: PostgreSQL 15+, SQLAlchemy 2.0+, Alembic (Flask-Migrate)
- **Auth**: Flask-Login, session-based, optional Redis
- **Forms**: Flask-WTF, CSRF protection
- **Frontend**: Jinja2, Bootstrap 5, HTMX-ready
- **Tasks**: Celery + Redis (optional)
- **API**: Flask-RESTful for internal/mobile

## Quick Start

### 1. Environment

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
cp .env.example .env
# Edit .env: set SECRET_KEY, DATABASE_URL (e.g. postgresql://user:pass@localhost:5432/hrms_kenya)
```

### 2. Database

Create PostgreSQL database, then:

```bash
set FLASK_APP=run.py
flask db init
flask db migrate -m "Initial schema"
flask db upgrade
```

### 3. Seed data (roles, permissions, statutory rates, leave types)

```bash
flask shell
>>> from scripts.seed_data import run
>>> run()
>>> exit()
```

Create first admin user (in flask shell):

```python
from app.extensions import db
from app.models.user import User, UserRole
from app.models.employee import Employee

# Create a minimal employee for the admin user (optional)
emp = Employee(employee_number='EMP-2026-0001', first_name='Admin', last_name='User', hire_date=date(2026, 1, 1))
db.session.add(emp)
db.session.flush()

admin = User(email='admin@example.com', is_active=True, is_superuser=True)
admin.set_password('ChangeMe123!')
db.session.add(admin)
admin.employee_id = emp.id  # optional
db.session.commit()

# Assign role (optional if is_superuser)
role_admin = db.session.query(Role).filter_by(code='ADMIN').first()
db.session.add(UserRole(user_id=admin.id, role_id=role_admin.id))
db.session.commit()
```

### 4. Run

```bash
python run.py
# Open http://localhost:5000 → redirect to login
```

## Project Structure

```
hrms-kenya/
├── app/
│   ├── __init__.py          # App factory
│   ├── extensions.py        # db, login_manager, csrf, limiter, mail
│   ├── models/              # SQLAlchemy models (user, employee, statutory, audit, payroll, leave, ...)
│   ├── routes/              # Blueprints (auth, dashboard, employees, payroll, leave, statutory, reports, api)
│   ├── services/            # Business logic (payroll_engine, statutory_service, audit_service)
│   ├── forms/               # WTForms (auth, employee, leave, payroll, settings)
│   ├── decorators/          # @permission_required, audit
│   ├── utils/               # Kenyan validators (KRA PIN, ID, phone), formatters, file_handlers
│   ├── templates/           # Jinja2 layouts, auth, dashboard, employees, payroll, leave, reports, errors
│   └── context_processors.py
├── migrations/              # Alembic
├── scripts/
│   └── seed_data.py         # Roles, permissions, statutory rates, leave types
├── config.py                # Development / Testing / Production
├── run.py                   # Dev server
├── wsgi.py                  # Production
└── requirements.txt
```

## Statutory Configuration (Kenya 2026)

- **PAYE**: Tax brackets (0–30k @ 10%, 30k–50k @ 25%, etc.) and personal relief stored in DB. Edit via **Settings → Statutory** (or `/statutory`).
- **NSSF**: Tier I (first 9,000 @ 6%+6%), Tier II (9,001–108,000). Seeded in `scripts/seed_data.py`.
- **SHIF**: 2.75% of gross (rate code `SHIF_PERCENT`).
- **Housing Levy**: 1.5% of gross, employee only (`HOUSING_LEVY_PERCENT`).

## Security

- CSRF on all forms
- Session: HTTPOnly, Secure (production), 30-min timeout
- Account lockout after 5 failed attempts (15 min)
- Passwords hashed with Werkzeug
- Audit log for logins and data changes

## Testing

```bash
pip install pytest pytest-cov pytest-flask
set FLASK_ENV=testing
pytest tests/ -v --cov=app
```

## Deployment

- **WSGI**: Gunicorn (`gunicorn -w 4 -b 0.0.0.0:5000 wsgi:application`)
- **Reverse proxy**: Nginx — see `deploy/nginx/hrms.conf.example`
- **Process**: systemd or Supervisor
- Set `FLASK_ENV=production`, `SECRET_KEY`, `DATABASE_URL`, and other env vars from `.env.example`.

**Large leave attachments (100 MB):** Nginx defaults to 1 MB. Set `client_max_body_size 105M;` in the `server` block (or `http` block in `/etc/nginx/nginx.conf`), then `sudo nginx -t && sudo systemctl reload nginx`. A `413 Request Entity Too Large` from nginx means this limit was not raised on the server.

## License

Proprietary. All rights reserved.
