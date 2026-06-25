"""
HRMS Kenya - Application Factory.
Monolithic Flask app with blueprints for Kenyan statutory-compliant HR.
"""
import os
import logging
from pathlib import Path

from dotenv import load_dotenv

# Load .env before config import so BREVO_* and DATABASE_URL are available.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / '.env')

from flask import Flask
from flask_wtf.csrf import CSRFError
from sqlalchemy.exc import ProgrammingError

from app.extensions import (
    db,
    migrate,
    login_manager,
    csrf,
    limiter,
    mail,
)
from config import get_config


def _apply_env_config(app: Flask) -> None:
    """Re-apply selected settings from os.environ (after .env load)."""
    for key in (
        'BREVO_API_KEY',
        'BREVO_SENDER_EMAIL',
        'BREVO_SENDER_NAME',
        'APP_BASE_URL',
        'APP_NAME',
        'ENABLE_PAYROLL',
        'ENABLE_ATTENDANCE',
        'ENABLE_OVERTIME',
        'ENABLE_BRANCHES',
        'PASSWORD_RESET_EXPIRY_SECONDS',
    ):
        raw = os.environ.get(key)
        if raw is not None and str(raw).strip():
            if key == 'PASSWORD_RESET_EXPIRY_SECONDS':
                app.config[key] = int(raw)
            elif key == 'ENABLE_PAYROLL':
                app.config[key] = str(raw).strip().lower() in ('1', 'true', 'yes')
            elif key == 'ENABLE_ATTENDANCE':
                app.config[key] = str(raw).strip().lower() in ('1', 'true', 'yes')
            elif key == 'ENABLE_OVERTIME':
                app.config[key] = str(raw).strip().lower() in ('1', 'true', 'yes')
            elif key == 'ENABLE_BRANCHES':
                app.config[key] = str(raw).strip().lower() in ('1', 'true', 'yes')
            else:
                app.config[key] = str(raw).strip()


def _ensure_writable_dir(path_value: str, fallback_name: str) -> tuple[Path, bool]:
    """
    Ensure directory exists and is writable.
    Returns (resolved_path, used_fallback).
    """
    target = Path(path_value)
    try:
        target.mkdir(parents=True, exist_ok=True)
        return target, False
    except PermissionError:
        fallback = Path('/tmp/hrms') / fallback_name
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback, True


def create_app(config_object=None):
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder='templates',
        static_folder='static',
        instance_relative_config=True,
    )

    # Load config
    config = config_object or get_config()
    app.config.from_object(config)
    _apply_env_config(app)

    # Ensure instance and storage dirs exist; fallback to /tmp/hrms/* when container FS is read-only.
    instance_dir, instance_fallback = _ensure_writable_dir(app.instance_path, 'instance')
    if instance_fallback:
        app.instance_path = str(instance_dir)

    upload_dir, upload_fallback = _ensure_writable_dir(app.config['UPLOAD_FOLDER'], 'uploads')
    if upload_fallback:
        app.config['UPLOAD_FOLDER'] = str(upload_dir)

    eu_dir, eu_fallback = _ensure_writable_dir(app.config['EMPLOYEE_UPLOADS_ROOT'], 'employeeuploads')
    if eu_fallback:
        app.config['EMPLOYEE_UPLOADS_ROOT'] = str(eu_dir)

    if not app.config.get('TESTING'):
        log_dir, log_fallback = _ensure_writable_dir(app.config['LOG_DIR'], 'logs')
        if log_fallback:
            app.config['LOG_DIR'] = str(log_dir)

    # Initialize extensions
    _init_extensions(app)
    from app.services.audit_service import register_auto_audit_listeners
    register_auto_audit_listeners()

    # Load all models and create tables *before* blueprints (so metadata has full dependency order).
    with app.app_context():
        from app.models import (  # noqa: F401
            Company,
            Branch,
            User,
            Role,
            Permission,
            UserRole,
            Employee,
            EmployeeAssignmentHistory,
            Department,
            JobTitle,
            StatutoryRateType,
            StatutoryRate,
            PayeBracket,
            NssfTier,
            AuditLog,
            PayrollRun,
            PayrollItem,
            PayrollStatutoryRemittance,
            PayrollRunManualDeduction,
            PayrollRunExclusion,
            EmployeeSalary,
            EmployeeAllowance,
            Allowance,
            Deduction,
            EmployeeDeduction,
            EarningsDeductionType,
            LeaveType,
            LeaveBalance,
            LeaveRequest,
            PublicHoliday,
            OvertimeRequest,
            AttendanceRecord,
            EmployeeDocument,
            DocumentCategory,
            Notification,
            SavedReport,
            Employer,
            EmployeeBenefit,
            EmployeeBenefitPayment,
            CasualWorker,
            CasualPayment,
            MessageThread,
            MessageThreadParticipant,
            Message,
            MessageRecipient,
        )
        from app.models.company_asset import AssetCategory, CompanyAsset, AssetAssignment  # noqa: F401
        from app.models.it_ticket import TicketCategory, Ticket, TicketComment  # noqa: F401
        _create_tables_safe(app)
        _apply_schema_patches(app)
        try:
            from app.services.rbac_bootstrap import ensure_rbac_defaults
            ensure_rbac_defaults()
        except Exception as e:
            app.logger.warning('RBAC bootstrap skipped or partial: %s', e)
        if not app.config.get('LEAVE_ALLOW_CARRY_FORWARD', False):
            try:
                from app.services.company_bootstrap import sync_leave_carry_forward_policy
                n = sync_leave_carry_forward_policy()
                if n:
                    app.logger.info('Leave carry-forward disabled: updated %s leave type(s).', n)
            except Exception as e:
                app.logger.warning('Leave carry-forward policy sync skipped: %s', e)

    # Register blueprints (after tables so route imports don't affect metadata)
    _register_blueprints(app)

    # Register error handlers
    _register_error_handlers(app)

    # Context processors
    _register_context_processors(app)

    _register_request_hooks(app)

    # Configure logging
    _configure_logging(app)

    # Root URL rule
    @app.route('/')
    def index():
        from app.utils.navigation import redirect_to_user_home
        return redirect_to_user_home()

    return app


# Explicit creation order: dependencies first. SQLAlchemy's sorted_tables can be wrong.
_TABLE_ORDER = (
    'permissions', 'roles', 'role_permissions',
    'companies', 'branches',
    'statutory_rate_types',
    'employers',
    'document_categories',
    'departments', 'job_titles',
    'allowances', 'deductions', 'earnings_deduction_types',
    'leave_types', 'public_holidays',
    'statutory_rates', 'paye_brackets', 'nssf_tiers',
    'employees',   # before users (User.employee_id -> employees)
    'users', 'user_roles',
    'employee_assignment_history',
    'audit_logs', 'leave_balances', 'leave_requests', 'employee_salaries', 'employee_allowances',
    'deductions', 'employee_deductions',
    'attendance_records', 'employee_documents', 'employee_benefits', 'employee_benefit_payments', 'casual_workers', 'casual_payments',
    'consultants', 'consultant_compensation',
    'payroll_runs', 'overtime_requests', 'payroll_run_exclusions', 'payroll_run_manual_deductions', 'payroll_items',
    'consultant_payroll_run_exclusions', 'consultant_payroll_items',
    'payroll_statutory_remitances',
    'notifications', 'saved_reports',
    'message_threads', 'message_thread_participants', 'messages', 'message_recipients',
    'asset_categories', 'company_assets', 'asset_assignments',
    'ticket_categories', 'tickets', 'ticket_comments',
)


def _create_tables_safe(app):
    """Create all tables in explicit dependency order. Ignore already exists; retry on dependency missing."""
    meta = db.metadata
    order_index = {name: i for i, name in enumerate(_TABLE_ORDER)}
    # Sort all tables: known names by our order, then any others last
    tables = sorted(
        list(meta.tables.values()),
        key=lambda t: order_index.get(t.name, len(_TABLE_ORDER)),
    )
    for _ in range(20):
        deferred = 0
        for table in tables:
            try:
                table.create(db.engine, checkfirst=True)
            except ProgrammingError as e:
                msg = str(e).lower()
                if "already exists" in msg or "duplicate" in msg:
                    continue
                if "does not exist" in msg or "undefined table" in msg:
                    deferred += 1
                    continue
                raise
        if deferred == 0:
            break
    # Ensure users table exists (often missed due to order/FK); create employees then users if needed
    for name in ('employees', 'users'):
        if name in meta.tables:
            try:
                meta.tables[name].create(db.engine, checkfirst=True)
            except ProgrammingError as e:
                if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                    pass
                else:
                    app.logger.warning("Could not create table %s: %s", name, e)


def _apply_schema_patches(app):
    """Lightweight ALTERs for columns added after initial deploy (PostgreSQL)."""
    if app.config.get('TESTING'):
        return
    from sqlalchemy import text

    patches = (
        "ALTER TABLE employee_documents ADD COLUMN IF NOT EXISTS original_filename VARCHAR(255) NULL",
        """
        UPDATE employee_documents
        SET original_filename = name
        WHERE original_filename IS NULL AND name IS NOT NULL
        """,
    )
    try:
        with db.engine.begin() as conn:
            for stmt in patches:
                conn.execute(text(stmt))
    except Exception as e:
        app.logger.warning('Schema patches skipped or partial: %s', e)


def _init_extensions(app):
    """Initialize Flask extensions with app."""
    db.init_app(app)
    migrate.init_app(app, db, directory=os.path.join(os.path.dirname(app.root_path), 'migrations'))

    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'
    login_manager.session_protection = 'strong'

    csrf.init_app(app)
    limiter.init_app(app)
    mail.init_app(app)

    # User loader for Flask-Login
    from app.models.user import User
    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))


def _register_blueprints(app):
    """Register application blueprints."""
    from app.routes.auth import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.employees import employees_bp
    from app.routes.departments import departments_bp
    from app.routes.branches import branches_bp
    from app.routes.leave import leave_bp
    from app.routes.attendance import attendance_bp
    from app.routes.payroll import payroll_bp
    from app.routes.statutory import statutory_bp
    from app.routes.reports import reports_bp
    from app.routes.settings import settings_bp
    from app.routes.api import api_bp
    from app.routes.overtime import overtime_bp
    from app.routes.casual_workers import casual_workers_bp
    from app.routes.consultants import consultants_bp
    from app.routes.messages import messages_bp
    from app.routes.company_assets import company_assets_bp
    from app.routes.it_tickets import it_tickets_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(dashboard_bp, url_prefix='/dashboard')
    app.register_blueprint(employees_bp, url_prefix='/employees')
    app.register_blueprint(departments_bp, url_prefix='/departments')
    if app.config.get('ENABLE_BRANCHES', False):
        app.register_blueprint(branches_bp, url_prefix='/branches')
    try:
        from app.routes.job_titles import job_titles_bp
        app.register_blueprint(job_titles_bp, url_prefix='/job-titles')
    except Exception as e:
        app.logger.warning('Job titles blueprint not registered: %s', e)
    try:
        from app.routes.allowances import allowances_bp
        if app.config.get('ENABLE_PAYROLL', False):
            app.register_blueprint(allowances_bp, url_prefix='/allowances')
    except Exception as e:
        app.logger.warning('Allowances blueprint not registered: %s', e)
    app.register_blueprint(leave_bp, url_prefix='/leave')
    if app.config.get('ENABLE_OVERTIME', False):
        app.register_blueprint(overtime_bp, url_prefix='/overtime')
    if app.config.get('ENABLE_ATTENDANCE', False):
        app.register_blueprint(attendance_bp, url_prefix='/attendance')
    if app.config.get('ENABLE_PAYROLL', False):
        app.register_blueprint(casual_workers_bp, url_prefix='/casual-workers')
        app.register_blueprint(consultants_bp, url_prefix='/consultants')
        app.register_blueprint(payroll_bp, url_prefix='/payroll')
        app.register_blueprint(statutory_bp, url_prefix='/statutory')
    app.register_blueprint(reports_bp, url_prefix='/reports')
    app.register_blueprint(messages_bp, url_prefix='/messages')
    app.register_blueprint(company_assets_bp, url_prefix='/company-assets')
    app.register_blueprint(it_tickets_bp, url_prefix='/it-tickets')
    app.register_blueprint(settings_bp, url_prefix='/settings')
    app.register_blueprint(api_bp, url_prefix='/api')


def _register_error_handlers(app):
    """Register custom error handlers."""
    from flask import jsonify, render_template, redirect, url_for, request, flash
    from werkzeug.exceptions import RequestEntityTooLarge

    @app.errorhandler(RequestEntityTooLarge)
    def request_entity_too_large(e):
        if request.path.endswith('/documents/upload'):
            max_mb = max(1, int(app.config.get('EMPLOYEE_DOCUMENT_MAX_BYTES', 500 * 1024 * 1024)) // (1024 * 1024))
            return jsonify(status='error', message=f'File is too large. Maximum size is {max_mb} MB.'), 413
        return render_template('errors/500.html'), 413

    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template('errors/500.html'), 500

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        """
        Handle expired/invalid CSRF tokens gracefully.
        Common when a user leaves a form open and session expires.
        """
        if request.path.endswith('/documents/upload') or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(status='error', message='Your session expired. Refresh the page and try again.'), 400
        flash('Your session expired. Please log in again and retry.', 'warning')
        return redirect(url_for('auth.login', next=request.path))


def _register_request_hooks(app):
    """Global request hooks (e.g. forced password change after bulk provisioning)."""
    from flask import redirect, request, session, url_for
    from flask_login import current_user

    @app.before_request
    def refresh_session_lifetime():
        """Keep signed-in users active for PERMANENT_SESSION_LIFETIME (default 2h)."""
        session.permanent = True

    @app.before_request
    def enforce_password_change():
        if not current_user.is_authenticated:
            return None
        if not getattr(current_user, 'must_change_password', False):
            return None
        endpoint = request.endpoint or ''
        if endpoint.startswith('static'):
            return None
        if endpoint in (
            'auth.login',
            'auth.logout',
            'auth.change_password',
            'auth.forgot_password',
            'auth.reset_password',
            'auth.register',
        ):
            return None
        return redirect(url_for('auth.change_password'))


def _register_context_processors(app):
    """Register template context processors."""
    from app.context_processors import (
        inject_config,
        inject_leave_approval_helpers,
        inject_page_nav,
        inject_pending_approvals,
        inject_permissions,
        inject_tenant_nav,
        inject_today,
        inject_unread_messages,
        register_template_filters,
    )
    app.context_processor(inject_permissions)
    app.context_processor(inject_config)
    app.context_processor(inject_tenant_nav)
    app.context_processor(inject_page_nav)
    app.context_processor(inject_today)
    app.context_processor(inject_unread_messages)
    app.context_processor(inject_leave_approval_helpers)
    app.context_processor(inject_pending_approvals)
    register_template_filters(app)


def _configure_logging(app):
    """Configure application logging."""
    if app.config.get('TESTING'):
        app.logger.setLevel(logging.DEBUG)
        return

    log_level = getattr(logging, app.config.get('LOG_LEVEL', 'INFO'))
    app.logger.setLevel(log_level)
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
    stream_formatter = logging.Formatter('[%(asctime)s] %(levelname)s %(name)s: %(message)s')

    if not app.config.get('LOG_TO_STDOUT'):
        log_dir = app.config['LOG_DIR']
        file_handler = logging.FileHandler(
            os.path.join(log_dir, 'hrms.log'),
            encoding='utf-8',
        )
        file_handler.setFormatter(formatter)
        app.logger.addHandler(file_handler)

    # Message / Brevo diagnostics always on the terminal when running python run.py
    console = logging.StreamHandler()
    console.setFormatter(stream_formatter)
    console.setLevel(log_level)
    for logger_name in (
        'app.services.brevo_service',
        'app.services.message_notification_service',
        'app.routes.messages',
    ):
        email_logger = logging.getLogger(logger_name)
        email_logger.setLevel(log_level)
        if not any(isinstance(h, logging.StreamHandler) for h in email_logger.handlers):
            email_logger.addHandler(console)
        email_logger.propagate = True
