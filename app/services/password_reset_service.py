"""Password reset tokens and Brevo reset emails."""
from datetime import datetime, timedelta

from flask import current_app, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.extensions import db
from app.models.user import User
from app.services.brevo_service import brevo_configured, send_transactional_email


def _serializer():
    return URLSafeTimedSerializer(
        current_app.config['SECRET_KEY'],
        salt='password-reset-v1',
    )


def generate_reset_token(user_id: int) -> str:
    return _serializer().dumps({'uid': user_id})


def verify_reset_token(token: str) -> int | None:
    """Return user id if token is valid and not expired."""
    max_age = int(current_app.config.get('PASSWORD_RESET_EXPIRY_SECONDS', 3600))
    try:
        data = _serializer().loads(token, max_age=max_age)
        uid = data.get('uid')
        return int(uid) if uid is not None else None
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return None


def external_base_url() -> str:
    """Public base URL for links in emails (set APP_BASE_URL in production)."""
    from flask import request

    configured = (current_app.config.get('APP_BASE_URL') or '').strip().rstrip('/')
    if configured:
        return configured
    return request.url_root.rstrip('/')


def build_reset_url(token: str) -> str:
    return external_base_url() + url_for('auth.reset_password', token=token)


def send_password_reset_email(user: User) -> bool:
    token = generate_reset_token(user.id)
    reset_url = build_reset_url(token)
    app_name = current_app.config.get('APP_NAME', 'Andersen')
    expiry_hours = max(1, int(current_app.config.get('PASSWORD_RESET_EXPIRY_SECONDS', 3600)) // 3600)

    html = f"""
    <p>Hello,</p>
    <p>You requested a password reset for your <strong>{app_name}</strong> account ({user.email}).</p>
    <p><a href="{reset_url}" style="display:inline-block;padding:10px 18px;background:#ab0e1e;color:#fff;text-decoration:none;border-radius:6px;">Reset your password</a></p>
    <p>Or copy this link into your browser:<br><a href="{reset_url}">{reset_url}</a></p>
    <p>This link expires in about {expiry_hours} hour(s). If you did not request this, you can ignore this email.</p>
    <p style="color:#64748b;font-size:12px;">{app_name}</p>
    """
    text = (
        f'Password reset for {app_name}\n\n'
        f'Open this link to set a new password (expires in about {expiry_hours} hour(s)):\n'
        f'{reset_url}\n\n'
        'If you did not request this, ignore this email.'
    )

    sent = send_transactional_email(
        user.email,
        f'{app_name} — Reset your password',
        html,
        text_content=text,
    )
    if not sent and current_app.debug:
        current_app.logger.info('Password reset link (dev, email not sent): %s', reset_url)
    return sent


def initiate_password_reset(email: str) -> None:
    """
    Look up user by email and send reset link if active.
    Always succeeds from caller's perspective (no email enumeration).
    """
    user = (
        db.session.query(User)
        .filter(db.func.lower(User.email) == email.strip().lower())
        .first()
    )
    if not user or not user.is_active:
        return
    if not brevo_configured() and not current_app.debug:
        current_app.logger.warning('Password reset requested but Brevo is not configured')
        return
    send_password_reset_email(user)


def apply_password_reset(user: User, new_password: str) -> None:
    user.set_password(new_password)
    user.must_change_password = False
    user.failed_login_count = 0
    user.locked_until = None
    user.updated_at = datetime.utcnow()
