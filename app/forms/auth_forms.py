"""Auth forms: login, register, password reset."""
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email, Length, Optional, ValidationError, EqualTo


class LoginForm(FlaskForm):
    """Login form."""
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember_me = BooleanField('Remember Me', default=False)
    submit = SubmitField('Sign In')


class RegisterForm(FlaskForm):
    """First-time setup: create the initial admin account."""
    organization_name = StringField(
        'Organization name',
        validators=[DataRequired(), Length(min=1, max=200)],
    )
    country_code = StringField(
        'Primary country (ISO2)',
        default='KE',
        validators=[Optional(), Length(min=2, max=2)],
    )
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[
        DataRequired(),
        Length(min=8, message='Password must be at least 8 characters'),
    ])
    confirm = PasswordField('Confirm Password', validators=[
        DataRequired(),
        EqualTo('password', message='Passwords must match'),
    ])
    submit = SubmitField('Create Account')


class ForgotPasswordForm(FlaskForm):
    """Request password reset."""
    email = StringField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Send Reset Link')


class ResetPasswordForm(FlaskForm):
    """Set new password (from reset link)."""
    password = PasswordField('New Password', validators=[DataRequired()])
    confirm = PasswordField('Confirm Password', validators=[
        DataRequired(),
        EqualTo('password', message='Passwords must match'),
    ])
    submit = SubmitField('Reset Password')

    def validate_password(self, field):
        from flask import current_app
        min_len = current_app.config.get('PASSWORD_MIN_LENGTH', 8)
        if len(field.data or '') < min_len:
            raise ValidationError(f'Password must be at least {min_len} characters')


class ChangePasswordForm(FlaskForm):
    """Signed-in user changes password (current password optional when force_change in route)."""
    current_password = PasswordField('Current password', validators=[Optional()])
    new_password = PasswordField('New password', validators=[DataRequired()])
    confirm_password = PasswordField(
        'Confirm new password',
        validators=[
            DataRequired(),
            EqualTo('new_password', message='Passwords must match'),
        ],
    )
    submit = SubmitField('Change password')

    def validate_new_password(self, field):
        from flask import current_app
        min_len = current_app.config.get('PASSWORD_MIN_LENGTH', 8)
        if len(field.data or '') < min_len:
            raise ValidationError(f'Password must be at least {min_len} characters')
        if self.current_password.data and field.data == self.current_password.data:
            raise ValidationError('New password must be different from your current password')
