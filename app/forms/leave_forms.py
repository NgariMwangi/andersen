"""Leave request and approval forms."""
from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateField,
    DecimalField,
    IntegerField,
    RadioField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Optional, ValidationError, NumberRange, Length
from datetime import date as dt_date


def coerce_int_or_none(value):
    """SelectField: empty option -> None for optional handover when no colleagues exist."""
    if value is None or value == '' or value == 'None':
        return None
    return int(value)


class LeaveTypeForm(FlaskForm):
    """Admin: define leave categories (annual, sick, etc.)."""
    code = StringField('Code', validators=[DataRequired()], render_kw={'placeholder': 'e.g. ANNUAL'})
    name = StringField('Name', validators=[DataRequired()])
    days_count_basis = SelectField(
        'Count leave length as',
        choices=[
            ('working', 'Working days (Mon–Fri, excludes weekends)'),
            ('calendar', 'Calendar days (includes weekends — e.g. 90-day maternity)'),
        ],
        validators=[DataRequired()],
    )
    days_per_year = DecimalField('Days per year', places=2, validators=[Optional()])
    accrues_monthly = BooleanField('Accrues monthly', default=False)
    days_per_month = DecimalField('Days accrued per month', places=2, validators=[Optional()])
    requires_approval = BooleanField('Requires approval', default=True)
    requires_document = BooleanField('Requires document upload', default=False)
    is_paid = BooleanField('Paid leave', default=True)
    min_days_request = DecimalField('Minimum days per request', places=2, validators=[Optional(), NumberRange(min=0)])
    max_consecutive_days = IntegerField('Max consecutive days (blank = no limit)', validators=[Optional()])
    carry_forward_max = IntegerField('Max days carry forward to next year', validators=[Optional()])
    is_active = BooleanField('Active', default=True)
    submit = SubmitField('Save')


class LeaveRequestForm(FlaskForm):
    """Employee leave request."""
    leave_type_id = SelectField('Leave Type', coerce=int, validators=[DataRequired()])
    start_date = DateField('Start Date', validators=[DataRequired()])
    end_date = DateField('End Date', validators=[DataRequired()])
    handover_to_id = SelectField(
        'Hand over duties to',
        coerce=coerce_int_or_none,
        validators=[Optional()],
    )
    reason = TextAreaField('Reason', validators=[Optional()])
    day_portion = SelectField(
        'Day length',
        choices=[
            ('1', 'Full day (1)'),
            ('0.5', 'Half day (0.5)'),
            ('0.25', 'Quarter day (0.25)'),
        ],
        default='1',
        validators=[DataRequired()],
    )
    submit = SubmitField('Submit Request')

    def validate_end_date(self, field):
        if self.start_date.data and field.data and field.data < self.start_date.data:
            raise ValidationError('End date must be after start date.')


class AdminLeaveRequestForm(LeaveRequestForm):
    """HR: create a leave request on behalf of an employee."""
    employee_id = SelectField('Employee', coerce=int, validators=[DataRequired()])
    auto_approve = BooleanField('Record as approved immediately', default=True)
    admin_notes = TextAreaField('Internal notes', validators=[Optional()])
    submit = SubmitField('Save leave')


class LeaveApprovalForm(FlaskForm):
    """Manager approval/rejection."""
    action = SelectField('Action', choices=[('approve', 'Approve'), ('reject', 'Reject')], validators=[DataRequired()])
    review_notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Submit')


class LeaveYearRolloverForm(FlaskForm):
    """HR: carry capped balances into the next calendar year."""
    from_year = IntegerField('From year (closing)', validators=[DataRequired(), NumberRange(min=2000, max=2100)])
    to_year = IntegerField('To year (opening)', validators=[DataRequired(), NumberRange(min=2000, max=2100)])
    rollover_submit = SubmitField('Run year rollover')


def _coerce_int_empty(value):
    if value is None or value == '' or value == 'None':
        return None
    return int(value)


_MONTH_CHOICES = [
    ('', '— Month —'),
    (1, 'January'),
    (2, 'February'),
    (3, 'March'),
    (4, 'April'),
    (5, 'May'),
    (6, 'June'),
    (7, 'July'),
    (8, 'August'),
    (9, 'September'),
    (10, 'October'),
    (11, 'November'),
    (12, 'December'),
]


class PublicHolidayForm(FlaskForm):
    """HR: recurring (every year) or one-off public holiday."""
    country_code = StringField(
        'Country (ISO 3166-1 alpha-2)',
        default='KE',
        validators=[DataRequired(), Length(min=2, max=2)],
        render_kw={'placeholder': 'e.g. KE, UG', 'maxlength': 2},
    )
    kind = RadioField(
        'Holiday type',
        choices=[
            ('recurring', 'Fixed every year (same month/day — country holidays)'),
            ('one_off', 'One year only (specific calendar date)'),
        ],
        default='recurring',
        validators=[DataRequired()],
    )
    name = StringField('Name', validators=[DataRequired()], render_kw={'placeholder': 'e.g. Labour Day'})
    recurring_month = SelectField('Month', coerce=_coerce_int_empty, choices=_MONTH_CHOICES, validators=[Optional()])
    recurring_day = IntegerField('Day', validators=[Optional(), NumberRange(min=1, max=31)])
    holiday_date = DateField('Date', validators=[Optional()])
    submit = SubmitField('Save')

    def validate(self, extra_validators=None):
        if not super().validate(extra_validators):
            return False
        k = (self.kind.data or '').strip()
        if k == 'recurring':
            if not self.recurring_month.data or self.recurring_day.data is None:
                self.recurring_month.errors.append('Month and day are required for a fixed annual holiday.')
                return False
            try:
                dt_date(2024, self.recurring_month.data, self.recurring_day.data)
            except ValueError:
                self.recurring_day.errors.append('Invalid day for that month (check Feb / 31-day months).')
                return False
        elif k == 'one_off':
            if not self.holiday_date.data:
                self.holiday_date.errors.append('Date is required for a one-off holiday.')
                return False
        return True
