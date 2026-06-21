"""WTForms for consultants."""
from flask_wtf import FlaskForm
from wtforms import StringField, DateField, DecimalField, TextAreaField, BooleanField, SelectField
from wtforms.validators import DataRequired, Optional, NumberRange, Length


class ConsultantForm(FlaskForm):
    consultant_number = StringField('Consultant number', validators=[Optional(), Length(max=30)])
    first_name = StringField('First name', validators=[DataRequired(), Length(max=100)])
    last_name = StringField('Last name', validators=[DataRequired(), Length(max=100)])
    middle_name = StringField('Middle name', validators=[Optional(), Length(max=100)])
    email = StringField('Email', validators=[Optional(), Length(max=255)])
    phone = StringField('Phone', validators=[Optional(), Length(max=30)])
    national_id = StringField('National ID', validators=[Optional(), Length(max=30)])
    kra_pin = StringField('KRA PIN', validators=[Optional(), Length(max=20)])
    bank_name = StringField('Bank name', validators=[Optional(), Length(max=100)])
    bank_branch = StringField('Bank branch', validators=[Optional(), Length(max=100)])
    bank_account_number = StringField('Account number', validators=[Optional(), Length(max=50)])
    bank_code = StringField('Bank code', validators=[Optional(), Length(max=20)])
    branch_id = SelectField('Branch', coerce=int, validators=[DataRequired()])
    status = SelectField(
        'Status',
        choices=[('active', 'Active'), ('inactive', 'Inactive'), ('terminated', 'Terminated')],
        validators=[DataRequired()],
    )
    start_date = DateField('Start date', validators=[DataRequired()])
    end_date = DateField('End date', validators=[Optional()])
    withholding_rate = DecimalField(
        'Withholding rate (%)',
        places=3,
        validators=[DataRequired(), NumberRange(min=0, max=100)],
        default=5,
    )
    prorate_payroll = BooleanField('Pro-rate for partial months', default=True)
    notes = TextAreaField('Notes', validators=[Optional()])


class ConsultantCompensationForm(FlaskForm):
    effective_from = DateField('Effective from', validators=[DataRequired()])
    effective_to = DateField('Effective to', validators=[Optional()])
    monthly_fee = DecimalField('Monthly fee', places=2, validators=[DataRequired(), NumberRange(min=0)])
    other_allowances = DecimalField('Other allowances', places=2, validators=[Optional(), NumberRange(min=0)], default=0)
    notes = TextAreaField('Notes', validators=[Optional()])
