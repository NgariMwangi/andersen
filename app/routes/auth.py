"""Authentication: login, logout, password reset."""
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, current_app
from flask_login import login_user, logout_user, current_user, login_required
from app.extensions import db, limiter
from app.models.user import User, Role, UserRole
from app.models.company import Company, Branch
from app.models.employer import Employer
from app.forms.auth_forms import (
    LoginForm,
    RegisterForm,
    ForgotPasswordForm,
    ResetPasswordForm,
    ChangePasswordForm,
)
from app.services.audit_service import log_login, log_audit
from app.services.company_bootstrap import bootstrap_company_defaults
from app.services.password_reset_service import (
    apply_password_reset,
    initiate_password_reset,
    verify_reset_token,
)
from app.utils.navigation import redirect_to_user_home, user_home_endpoint

auth_bp = Blueprint('auth', __name__)


def _safe_next_url(next_url: str | None) -> str | None:
    """Avoid redirect loops to login/register and off-site URLs."""
    if not next_url:
        return None
    path = next_url.split('?', 1)[0]
    if not path.startswith('/') or path.startswith('//'):
        return None
    if path.startswith('/auth/'):
        return None
    return next_url


def _flash_form_errors(form, *, prefix: str = 'Please fix the errors below.') -> None:
    if not form.errors:
        return
    parts = [prefix]
    for field, errors in form.errors.items():
        label = getattr(form, field, None)
        name = getattr(label, 'label', None)
        field_name = name.text if name else field.replace('_', ' ').title()
        for err in errors:
            parts.append(f'{field_name}: {err}')
    flash(' '.join(parts), 'danger')


def _auth_rate_limit():
    from flask import current_app
    return current_app.config.get('RATE_LIMIT_AUTH', '50 per minute')


def _allow_registration():
    """Registration is only allowed when no users exist (first-time setup)."""
    return db.session.query(User).count() == 0


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit(_auth_rate_limit)
def login():
    if current_user.is_authenticated:
        return redirect_to_user_home()
    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.query(User).filter_by(email=form.email.data.strip().lower()).first()
        if user is None:
            log_audit('LOGIN_FAILED', record_type='User', record_id=None,
                      new_values={'email': form.email.data}, description='Login failed - user not found')
            flash('Invalid email or password.', 'danger')
            return render_template('auth/login.html', form=form)
        if user.is_locked:
            flash('Account temporarily locked. Try again later.', 'warning')
            return render_template('auth/login.html', form=form)
        if not user.check_password(form.password.data):
            user.failed_login_count = (user.failed_login_count or 0) + 1
            from flask import current_app
            if user.failed_login_count >= current_app.config.get('ACCOUNT_LOCKOUT_ATTEMPTS', 5):
                user.locked_until = datetime.utcnow() + timedelta(
                    minutes=current_app.config.get('ACCOUNT_LOCKOUT_DURATION_MINUTES', 15))
            db.session.commit()
            log_audit('LOGIN_FAILED', record_type='User', record_id=user.id,
                      new_values={'email': form.email.data}, user_id=user.id, description='Login failed - wrong password')
            flash('Invalid email or password.', 'danger')
            return render_template('auth/login.html', form=form)
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = datetime.utcnow()
        db.session.commit()
        login_user(user, remember=form.remember_me.data)
        log_login(user.id, success=True)
        if user.must_change_password:
            flash('Please set a new password before continuing.', 'warning')
            return redirect(url_for('auth.change_password'))
        flash('Welcome back.', 'success')
        next_url = _safe_next_url(request.args.get('next')) or url_for(user_home_endpoint())
        return redirect(next_url)
    if request.method == 'POST':
        _flash_form_errors(form, prefix='Could not sign in.')
    return render_template('auth/login.html', form=form, allow_register=_allow_registration())


@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit(_auth_rate_limit)
def register():
    """First-time setup: create the initial admin account. Disabled once any user exists."""
    if current_user.is_authenticated:
        return redirect_to_user_home()
    if not _allow_registration():
        flash('Registration is disabled. Contact an administrator for an account.', 'info')
        return redirect(url_for('auth.login'))
    form = RegisterForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if db.session.query(User).filter_by(email=email).first():
            flash('An account with that email already exists.', 'danger')
            return render_template('auth/register.html', form=form)
        try:
            org_name = (form.organization_name.data or '').strip()
            cc_raw = (form.country_code.data or 'KE').strip().upper()
            cc = cc_raw[:2] if len(cc_raw) >= 2 else 'KE'
            company = Company(name=org_name or 'Organization', is_active=True)
            db.session.add(company)
            db.session.flush()
            db.session.add(
                Branch(company_id=company.id, name='Head Office', country_code=cc),
            )
            db.session.add(Employer(company_id=company.id, name=org_name or 'Organization'))
            user = User(
                email=email,
                company_id=company.id,
                is_superuser=True,
                is_active=True,
            )
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.flush()
            admin_role = db.session.query(Role).filter_by(code='ADMIN').first()
            if admin_role:
                db.session.add(UserRole(user_id=user.id, role_id=admin_role.id))
            db.session.commit()
            bootstrap_company_defaults(company.id, cc)
            flash('Account created. You can now sign in.', 'success')
            return redirect(url_for('auth.login'))
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception('Registration failed')
            flash(f'Could not create account: {exc}', 'danger')
            return render_template('auth/register.html', form=form)
    if request.method == 'POST':
        _flash_form_errors(form, prefix='Could not create account.')
    return render_template('auth/register.html', form=form)


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
@limiter.limit(_auth_rate_limit)
def change_password():
    user = db.session.get(User, current_user.id)
    if not user:
        abort(404)
    force_change = bool(user.must_change_password)
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not force_change:
            if not user.check_password(form.current_password.data):
                flash('Current password is incorrect.', 'danger')
                return _change_password_template(form, force_change=force_change)
        user.set_password(form.new_password.data)
        user.must_change_password = False
        db.session.commit()
        log_audit(
            'UPDATE',
            record_type='User',
            record_id=user.id,
            user_id=user.id,
            description='User changed own password',
        )
        flash('Your password has been updated.', 'success')
        return redirect_to_user_home()
    return _change_password_template(form, force_change=force_change)


def _change_password_template(form, *, force_change: bool = False):
    return render_template(
        'auth/change_password.html',
        form=form,
        password_min_length=current_app.config.get('PASSWORD_MIN_LENGTH', 8),
        force_change=force_change,
    )


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit(_auth_rate_limit)
def forgot_password():
    if current_user.is_authenticated:
        return redirect_to_user_home()
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        initiate_password_reset(form.email.data.strip().lower())
        flash(
            'If an account exists for that email, we sent a password reset link. '
            'Check your inbox (and spam folder).',
            'info',
        )
        return redirect(url_for('auth.login'))
    return render_template('auth/forgot_password.html', form=form)


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
@limiter.limit(_auth_rate_limit)
def reset_password(token):
    if current_user.is_authenticated:
        logout_user()
    user_id = verify_reset_token(token)
    if not user_id:
        flash('This reset link is invalid or has expired. Request a new one from the login page.', 'warning')
        return redirect(url_for('auth.forgot_password'))
    user = db.session.get(User, user_id)
    if not user or not user.is_active:
        flash('This reset link is invalid or has expired. Request a new one from the login page.', 'warning')
        return redirect(url_for('auth.forgot_password'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        apply_password_reset(user, form.password.data)
        db.session.commit()
        log_audit(
            'UPDATE',
            record_type='User',
            record_id=user.id,
            user_id=user.id,
            description='Password reset via email link',
        )
        flash('Your password has been updated. You can sign in now.', 'success')
        return redirect(url_for('auth.login'))
    return render_template(
        'auth/reset_password.html',
        form=form,
        token=token,
        password_min_length=current_app.config.get('PASSWORD_MIN_LENGTH', 8),
    )
