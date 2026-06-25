"""
Configuration classes for HRMS Kenya.
Environment-based: development, testing, production.
"""
import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / '.env')

# Repo root (andersen_hrms/). Employee documents live in a sibling folder, not inside the repo.
_PROJECT_ROOT = Path(__file__).resolve().parent
_DEFAULT_EMPLOYEE_UPLOADS = _PROJECT_ROOT.parent / 'employeeuploads'


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in ('1', 'true', 'yes')


def _session_cookie_secure_default() -> bool:
    """
    Secure cookies require HTTPS. When APP_BASE_URL is http:// (or unset),
  browsers ignore the session cookie and login appears to do nothing.
    """
    explicit = os.environ.get('SESSION_COOKIE_SECURE')
    if explicit is not None and str(explicit).strip():
        return _env_bool('SESSION_COOKIE_SECURE')
    base = (os.environ.get('APP_BASE_URL') or '').strip().lower()
    if base.startswith('https://'):
        return True
    if base.startswith('http://'):
        return False
    return False


class Config:
    """Base configuration."""
    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-change-in-production'
    DEBUG = False
    TESTING = False

    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'postgresql://postgres:deno0707@37.60.242.201:5432/hrms_kenya'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }

    # Session (default 2 hours; override with SESSION_LIFETIME_HOURS)
    SESSION_LIFETIME_HOURS = float(os.environ.get('SESSION_LIFETIME_HOURS', '2'))
    SESSION_TYPE = 'redis' if os.environ.get('REDIS_URL') else 'filesystem'
    PERMANENT_SESSION_LIFETIME = timedelta(hours=SESSION_LIFETIME_HOURS)
    REMEMBER_COOKIE_DURATION = timedelta(hours=SESSION_LIFETIME_HOURS)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = _session_cookie_secure_default()
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_NAME = 'hrms_session'

    # Redis (optional)
    REDIS_URL = os.environ.get('REDIS_URL') or 'redis://localhost:6379/0'
    CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL') or REDIS_URL
    CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND') or REDIS_URL

    # Security
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = int(float(os.environ.get('SESSION_LIFETIME_HOURS', '2')) * 3600)
    PASSWORD_MIN_LENGTH = 8
    PASSWORD_HISTORY_COUNT = 3
    PASSWORD_EXPIRY_DAYS = 90
    ACCOUNT_LOCKOUT_ATTEMPTS = 10
    ACCOUNT_LOCKOUT_DURATION_MINUTES = 15
    RATELIMIT_ENABLED = _env_bool('RATELIMIT_ENABLED', False)
    RATE_LIMIT_AUTH = '50 per minute'
    PASSWORD_RESET_EXPIRY_SECONDS = int(os.environ.get('PASSWORD_RESET_EXPIRY_SECONDS', '3600'))

    # Brevo transactional email (password reset, leave notifications)
    BREVO_API_KEY = os.environ.get('BREVO_API_KEY') or ''
    BREVO_SENDER_EMAIL = os.environ.get('BREVO_SENDER_EMAIL') or 'hr@nexgenfuelworks.com'
    BREVO_SENDER_NAME = os.environ.get('BREVO_SENDER_NAME') or 'HR NexGen Fuelworks'
    LEAVE_HR_NOTIFY_EMAIL = os.environ.get('LEAVE_HR_NOTIFY_EMAIL') or 'hr@nexgenfuelworks.com'
    APP_BASE_URL = os.environ.get('APP_BASE_URL') or ''  # e.g. https://hrms.example.com
    APP_NAME = os.environ.get('APP_NAME') or 'Andersen'
    ENABLE_PAYROLL = os.environ.get('ENABLE_PAYROLL', 'false').lower() in ('1', 'true', 'yes')
    ENABLE_ATTENDANCE = os.environ.get('ENABLE_ATTENDANCE', 'false').lower() in ('1', 'true', 'yes')
    ENABLE_OVERTIME = os.environ.get('ENABLE_OVERTIME', 'false').lower() in ('1', 'true', 'yes')
    ENABLE_BRANCHES = os.environ.get('ENABLE_BRANCHES', 'false').lower() in ('1', 'true', 'yes')
    # When false (default), leave days do not carry from one calendar year to the next.
    LEAVE_ALLOW_CARRY_FORWARD = _env_bool('LEAVE_ALLOW_CARRY_FORWARD', False)
    # annual = basic_salary stored as per-year figure (default); monthly = per-month (payroll-native).
    SALARY_BASIS = os.environ.get('SALARY_BASIS', 'annual').strip().lower()

    # File uploads (default 500 MB per request; override with UPLOAD_MAX_BYTES)
    _UPLOAD_MAX_BYTES = int(os.environ.get('UPLOAD_MAX_BYTES', str(500 * 1024 * 1024)))
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER') or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'uploads'
    )
    MAX_CONTENT_LENGTH = _UPLOAD_MAX_BYTES
    LEAVE_MAX_ATTACHMENT_BYTES = int(os.environ.get('LEAVE_MAX_ATTACHMENT_BYTES', str(_UPLOAD_MAX_BYTES)))
    ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png'}
    # Cloudinary (optional) for employee document storage
    CLOUDINARY_CLOUD_NAME = os.environ.get('CLOUDINARY_CLOUD_NAME') or ''
    CLOUDINARY_API_KEY = os.environ.get('CLOUDINARY_API_KEY') or ''
    CLOUDINARY_API_SECRET = os.environ.get('CLOUDINARY_API_SECRET') or ''
    CLOUDINARY_DOCS_FOLDER = os.environ.get('CLOUDINARY_DOCS_FOLDER') or 'hrms/employee_docs'
    # Local employee documents — sibling of repo (e.g. Andersen/employeeuploads next to Andersen/andersen_hrms)
    EMPLOYEE_UPLOADS_ROOT = os.environ.get('EMPLOYEE_UPLOADS_ROOT') or str(_DEFAULT_EMPLOYEE_UPLOADS)
    EMPLOYEE_DOCUMENT_MAX_BYTES = int(os.environ.get('EMPLOYEE_DOCUMENT_MAX_BYTES', str(_UPLOAD_MAX_BYTES)))

    # Mail
    MAIL_SERVER = os.environ.get('MAIL_SERVER') or 'localhost'
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 587)
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER') or 'noreply@hrms.local'

    # App
    EMPLOYEE_NUMBER_PREFIX = 'EMP'
    EMPLOYEE_NUMBER_YEAR_PREFIX = True
    DEFAULT_CURRENCY = 'KES'
    TIMEZONE = 'Africa/Nairobi'
    # P9 / statutory reporting (optional; set via env)
    EMPLOYER_NAME = os.environ.get('EMPLOYER_NAME') or ''
    EMPLOYER_KRA_PIN = os.environ.get('EMPLOYER_KRA_PIN') or ''
    P9_TEMPLATE_PATH = os.environ.get('P9_TEMPLATE_PATH') or ''

    # Logging
    LOG_TO_STDOUT = os.environ.get('LOG_TO_STDOUT', 'false').lower() == 'true'
    LOG_LEVEL = os.environ.get('LOG_LEVEL') or 'INFO'
    LOG_DIR = os.environ.get('LOG_DIR') or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'logs'
    )


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    SQLALCHEMY_ECHO = False
    SESSION_COOKIE_SECURE = False
    EXPLAIN_TEMPLATE_LOADING = False


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get('TEST_DATABASE_URL') or \
        'postgresql://localhost/hrms_kenya_test'
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'test-secret'
    SERVER_NAME = 'localhost:5000'
    RATE_LIMIT_AUTH = '100 per minute'  # Relax for tests
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_uploads')


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    # Inherits SESSION_COOKIE_SECURE from env / APP_BASE_URL (see helper above).


config_by_name = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}


def get_config():
    """Return config class from FLASK_ENV."""
    return config_by_name.get(
        os.environ.get('FLASK_ENV', 'development'),
        DevelopmentConfig
    )
