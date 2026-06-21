"""Employee create/edit forms with Kenyan validators."""
from flask_wtf import FlaskForm
from wtforms import (
    StringField, DateField, SelectField, SelectMultipleField, TextAreaField, SubmitField,
    FloatField, IntegerField, BooleanField,
)
from wtforms.validators import DataRequired, Optional, Email, ValidationError, Length
from datetime import date


def _coerce_optional_int(value):
    """Coerce for optional SelectField: '' -> None, else int(value)."""
    if value is None or value == '':
        return None
    return int(value)


def _validate_optional_identifier(form, field, *, field_name: str, max_length: int):
    if field.data:
        from app.utils.validators import validate_optional_identifier
        ok, msg = validate_optional_identifier(
            field.data, field_name=field_name, max_length=max_length
        )
        if not ok:
            raise ValidationError(msg)


def _validate_national_id(form, field):
    _validate_optional_identifier(form, field, field_name='National ID', max_length=30)


def _validate_kra_pin(form, field):
    _validate_optional_identifier(form, field, field_name='Tax PIN', max_length=20)


def _validate_nssf(form, field):
    _validate_optional_identifier(form, field, field_name='NSSF number', max_length=30)


def _validate_nhif(form, field):
    _validate_optional_identifier(form, field, field_name='NHIF/SHIF number', max_length=30)


def _validate_phone(form, field):
    if field.data:
        from app.utils.validators import validate_phone
        country = None
        branch_id_field = getattr(form, 'branch_id', None)
        if branch_id_field and branch_id_field.data:
            try:
                from app.extensions import db
                from app.models.company import Branch
                branch = db.session.get(Branch, int(branch_id_field.data))
                if branch:
                    country = branch.country_code
            except (ValueError, TypeError):
                pass
        ok, msg = validate_phone(field.data, country)
        if not ok:
            raise ValidationError(msg)


class EmployeeForm(FlaskForm):
    """Create/Edit employee."""
    employee_number = StringField('Employee Number', validators=[Optional()])
    first_name = StringField('First Name', validators=[DataRequired()])
    last_name = StringField('Last Name', validators=[DataRequired()])
    middle_name = StringField('Middle Name', validators=[Optional()])
    date_of_birth = DateField('Date of Birth', validators=[Optional()])
    gender = SelectField('Gender', choices=[('', '--'), ('Male', 'Male'), ('Female', 'Female'), ('Other', 'Other')], validators=[Optional()])
    marital_status = SelectField('Marital Status', choices=[
        ('', '--'), ('Single', 'Single'), ('Married', 'Married'), ('Divorced', 'Divorced'), ('Widowed', 'Widowed')
    ], validators=[Optional()])
    nationality = StringField('Nationality', validators=[Optional()])
    national_id = StringField('National ID', validators=[Optional(), Length(max=30), _validate_national_id])
    passport_number = StringField('Passport Number', validators=[Optional(), Length(max=50)])
    kra_pin = StringField('KRA PIN', validators=[Optional(), Length(max=20), _validate_kra_pin])
    nssf_number = StringField('NSSF Number', validators=[Optional(), Length(max=30), _validate_nssf])
    nhif_number = StringField('NHIF/SHIF Number', validators=[Optional(), Length(max=30), _validate_nhif])
    email = StringField('Email', validators=[Optional(), Email()])
    secondary_email = StringField('Secondary Email', validators=[Optional(), Email()])
    phone = StringField('Phone', validators=[Optional(), _validate_phone])
    secondary_phone = StringField('Secondary Phone', validators=[Optional(), _validate_phone])
    address = TextAreaField('Address', validators=[Optional()])
    postal_address = StringField('Postal Address', validators=[Optional()])
    emergency_contact_name = StringField('Emergency Contact Name', validators=[Optional()])
    emergency_contact_phone = StringField('Emergency Contact Phone', validators=[Optional(), _validate_phone])
    branch_id = SelectField('Work site (branch)', coerce=int, validators=[DataRequired()])
    department_id = SelectField('Department', coerce=_coerce_optional_int, validators=[Optional()])
    job_title_id = SelectField('Job Title', coerce=_coerce_optional_int, validators=[Optional()])
    manager_id = SelectField('Manager', coerce=_coerce_optional_int, validators=[Optional()])
    supervisor_ids = SelectMultipleField('Supervisors', coerce=int, validators=[Optional()])
    status = SelectField('Status', choices=[
        ('active', 'Active'), ('terminated', 'Terminated'), ('resigned', 'Resigned'),
        ('retired', 'Retired'), ('on_leave', 'On Leave'), ('suspended', 'Suspended'),
    ], default='active')
    employment_type = SelectField('Employment Type', choices=[
        ('', '--'), ('permanent', 'Permanent'), ('contract', 'Contract'),
        ('probation', 'Probation'), ('intern', 'Intern'), ('casual', 'Casual'),
    ], validators=[Optional()])
    hire_date = DateField('Hire Date', validators=[DataRequired()])
    probation_start_date = DateField('Probation Start Date', validators=[Optional()])
    probation_end_date = DateField('Probation End Date', validators=[Optional()])
    confirmation_date = DateField('Confirmation Date', validators=[Optional()])
    contract_start_date = DateField('Contract Start Date', validators=[Optional()])
    contract_end_date = DateField('Contract End Date', validators=[Optional()])
    prorate_payroll = BooleanField('Prorate payroll for partial months', default=True)
    bank_name = StringField('Bank Name', validators=[Optional()])
    bank_branch = StringField('Bank branch', validators=[Optional()])
    bank_account_number = StringField('Account Number', validators=[Optional()])
    bank_code = StringField('Bank Code', validators=[Optional()])
    swift_code = StringField('SWIFT Code', validators=[Optional()])
    submit = SubmitField('Save')

    def __init__(self, *args, employee_id=None, **kwargs):
        self._employee_id = employee_id
        super().__init__(*args, **kwargs)

    def validate_supervisor_ids(self, field):
        if self._employee_id and field.data and int(self._employee_id) in field.data:
            raise ValidationError('An employee cannot be their own supervisor.')

    def validate_hire_date(self, field):
        if field.data and field.data > date.today():
            raise ValidationError('Hire date cannot be in the future.')

    def validate_date_of_birth(self, field):
        if field.data:
            from datetime import timedelta
            if field.data > date.today() - timedelta(days=365 * 18):
                raise ValidationError('Employee must be at least 18 years old.')

    def validate_probation_end_date(self, field):
        if self.employment_type.data == 'probation':
            if not self.probation_start_date.data:
                raise ValidationError('Probation start date is required for probation employment type.')
            if not field.data:
                raise ValidationError('Probation end date is required for probation employment type.')
            if field.data < self.probation_start_date.data:
                raise ValidationError('Probation end date cannot be before probation start date.')

    def validate_contract_start_date(self, field):
        if self.employment_type.data == 'contract' and not field.data:
            raise ValidationError('Contract start date is required for contract employment type.')

    def validate_contract_end_date(self, field):
        if (
            self.employment_type.data == 'contract'
            and field.data
            and self.contract_start_date.data
            and field.data < self.contract_start_date.data
        ):
            raise ValidationError('Contract end date cannot be before contract start date.')


class EmployeeSelfContactForm(FlaskForm):
    """Contact fields employees may update on their own profile."""
    login_email = StringField('Sign-in email', validators=[DataRequired(), Email()])
    email = StringField('Work email', validators=[Optional(), Email()])
    secondary_email = StringField('Secondary email', validators=[Optional(), Email()])
    phone = StringField('Phone', validators=[Optional(), _validate_phone])
    secondary_phone = StringField('Secondary phone', validators=[Optional(), _validate_phone])
    address = TextAreaField('Physical address', validators=[Optional()])
    postal_address = StringField('Postal address', validators=[Optional()])
    emergency_contact_name = StringField('Emergency contact name', validators=[Optional()])
    emergency_contact_phone = StringField('Emergency contact phone', validators=[Optional(), _validate_phone])
    submit = SubmitField('Save contact details')

    def __init__(self, *args, user_id=None, **kwargs):
        self._user_id = user_id
        super().__init__(*args, **kwargs)

    def validate_login_email(self, field):
        from app.extensions import db
        from app.models.user import User

        email = (field.data or '').strip().lower()
        if not email:
            raise ValidationError('Sign-in email is required.')
        field.data = email
        q = db.session.query(User).filter(User.email == email)
        if self._user_id:
            q = q.filter(User.id != self._user_id)
        if q.first():
            raise ValidationError('Another account already uses this email.')


class EmployeeSalaryForm(FlaskForm):
    """Employee basic salary record. Allowances are added separately via Allowance table."""
    basic_salary = FloatField('Basic Salary', validators=[DataRequired()])
    pension_employee_percent = FloatField('Pension Employee %', default=0, validators=[Optional()])
    pension_employee_fixed_amount = FloatField('Employee Pension Fixed Amount', default=0, validators=[Optional()])
    pension_employer_percent = FloatField('Pension Employer %', default=0, validators=[Optional()])
    effective_from = DateField('Effective From', validators=[DataRequired()])
    notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Save')
