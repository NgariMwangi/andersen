"""System and statutory settings forms."""
from flask_wtf import FlaskForm
from wtforms import StringField, FloatField, DateField, SubmitField, SelectField, IntegerField, TextAreaField, PasswordField
from wtforms.validators import DataRequired, InputRequired, Optional, NumberRange, Email, Length, EqualTo


class StatutoryRateForm(FlaskForm):
    """Add/edit statutory rate (e.g. SHIF %, Housing Levy %)."""
    country_code = StringField('Country (ISO2)', default='KE', validators=[DataRequired(), Length(min=2, max=2)])
    code = StringField('Code', validators=[DataRequired()])
    effective_from = DateField('Effective From', validators=[DataRequired()])
    effective_to = DateField('Effective To', validators=[Optional()])
    value = FloatField('Value (%) or Amount', validators=[InputRequired()])
    description = StringField('Description', validators=[Optional()])
    submit = SubmitField('Save')


class PayeBracketForm(FlaskForm):
    """PAYE tax bracket."""
    country_code = StringField('Country (ISO2)', default='KE', validators=[DataRequired(), Length(min=2, max=2)])
    effective_from = DateField('Effective From', validators=[DataRequired()])
    effective_to = DateField('Effective To', validators=[Optional()])
    bracket_order = IntegerField('Order', validators=[InputRequired(), NumberRange(min=1, max=50)])
    min_amount = FloatField('Min taxable income', validators=[InputRequired()])
    max_amount = FloatField('Max taxable income', validators=[Optional()])
    rate_percent = FloatField('Rate (%)', validators=[InputRequired()])
    submit = SubmitField('Save')


class NssfTierForm(FlaskForm):
    """NSSF tier configuration."""
    country_code = StringField('Country (ISO2)', default='KE', validators=[DataRequired(), Length(min=2, max=2)])
    effective_from = DateField('Effective From', validators=[DataRequired()])
    effective_to = DateField('Effective To', validators=[Optional()])
    tier_number = IntegerField('Tier number', validators=[InputRequired(), NumberRange(min=1, max=20)])
    pensionable_min = FloatField('Pensionable min', validators=[InputRequired(), NumberRange(min=0)])
    pensionable_max = FloatField('Pensionable max', validators=[Optional(), NumberRange(min=0)])
    employee_percent = FloatField('Employee %', validators=[InputRequired(), NumberRange(min=0)])
    employer_percent = FloatField('Employer %', validators=[InputRequired(), NumberRange(min=0)])
    employee_max_amount = FloatField('Employee max amount', validators=[Optional(), NumberRange(min=0)])
    employer_max_amount = FloatField('Employer max amount', validators=[Optional(), NumberRange(min=0)])
    submit = SubmitField('Save')


class CreateOrganizationForm(FlaskForm):
    """Superuser-only: add another tenant (company) and its first admin user."""

    company_name = StringField('Company name', validators=[DataRequired(), Length(min=1, max=200)])
    branch_name = StringField(
        'First branch name',
        validators=[Optional(), Length(max=200)],
        default='Head Office',
    )
    country_code = StringField(
        'Primary country (ISO2)',
        default='KE',
        validators=[DataRequired(), Length(min=2, max=2)],
    )
    admin_email = StringField('Administrator email', validators=[DataRequired(), Email()])
    admin_password = PasswordField(
        'Administrator password',
        validators=[
            DataRequired(),
            Length(min=8, message='Password must be at least 8 characters'),
        ],
    )
    admin_password_confirm = PasswordField(
        'Confirm password',
        validators=[DataRequired(), EqualTo('admin_password', message='Passwords must match')],
    )
    submit = SubmitField('Create company')


class EmployerForm(FlaskForm):
    """Company/employer details shown on reports and exported documents."""
    name = StringField('Employer name', validators=[DataRequired()])
    kra_pin = StringField('Employer KRA PIN', validators=[Optional()])

    email = StringField('Employer email', validators=[Optional(), Email()])
    phone = StringField('Employer phone', validators=[Optional()])

    physical_address = TextAreaField('Physical address', validators=[Optional()])
    postal_address = StringField('Postal address', validators=[Optional()])

    registration_number = StringField('Registration number', validators=[Optional()])
    welfare_kit_deduction = FloatField(
        'Welfare kit deduction (per employee per month)',
        validators=[Optional(), NumberRange(min=0)],
        default=0,
    )

    submit = SubmitField('Save')
