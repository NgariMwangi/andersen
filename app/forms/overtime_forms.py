"""Overtime compensation request forms."""
from datetime import date

from flask_wtf import FlaskForm
from wtforms import IntegerField, SelectField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, NumberRange, Optional, ValidationError


class OvertimeRequestForm(FlaskForm):
    """Overtime request by explicit worked dates."""

    worked_dates = TextAreaField(
        'Worked overtime dates',
        validators=[DataRequired()],
        render_kw={'placeholder': 'One date per line (YYYY-MM-DD)'},
    )
    for_pay_month = IntegerField('Payroll month', validators=[DataRequired(), NumberRange(min=1, max=12)])
    for_pay_year = IntegerField('Payroll year', validators=[DataRequired(), NumberRange(min=2000, max=2100)])
    reason = TextAreaField('Reason', validators=[Optional()])
    submit = SubmitField('Submit request')

    def parsed_worked_dates(self) -> list[date]:
        raw = self.worked_dates.data or ''
        lines = [x.strip() for x in raw.replace(',', '\n').splitlines() if x.strip()]
        parsed = []
        for token in lines:
            try:
                parsed.append(date.fromisoformat(token))
            except ValueError as exc:
                raise ValidationError(f'Invalid date format: {token}. Use YYYY-MM-DD.') from exc
        unique = sorted(set(parsed))
        if not unique:
            raise ValidationError('Provide at least one overtime date.')
        return unique

    def validate_worked_dates(self, field):
        dates = self.parsed_worked_dates()
        latest = max(dates)
        month = self.for_pay_month.data
        year = self.for_pay_year.data
        if month and year and (month != latest.month or year != latest.year):
            raise ValidationError(
                f'Payroll period must match latest overtime date ({latest.isoformat()}).'
            )


class OvertimeForEmployeeForm(OvertimeRequestForm):
    """Manager/HR: overtime on behalf of an employee."""

    employee_id = SelectField('Employee', coerce=int, validators=[DataRequired()])
    submit = SubmitField('Submit request')


class OvertimeReviewForm(FlaskForm):
    """Approve or reject."""

    action = SelectField(
        'Action',
        choices=[('approve', 'Approve'), ('reject', 'Reject')],
        validators=[DataRequired()],
    )
    review_notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Submit')

    def validate_review_notes(self, field):
        if (self.action.data or '') == 'reject' and not (field.data or '').strip():
            raise ValidationError('Add a short note when rejecting.')
