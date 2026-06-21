"""Payroll run and configuration forms."""
from datetime import date

from flask_wtf import FlaskForm
from wtforms import SelectField, SubmitField, TextAreaField, StringField
from wtforms.validators import DataRequired, Optional, Length


def _pay_year_choices() -> list[tuple[int, str]]:
    """Current year first, then up to five prior years."""
    current = date.today().year
    return [(y, str(y)) for y in range(current, current - 6, -1)]


class PayrollRunForm(FlaskForm):
    """Create new payroll run."""
    pay_month = SelectField('Month', coerce=int, choices=[
        (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'),
        (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'),
        (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December'),
    ], validators=[DataRequired()])
    pay_year = SelectField('Year', coerce=int, validators=[DataRequired()])
    country_code = StringField('Country (ISO2)', validators=[DataRequired(), Length(min=2, max=2)], default='KE')
    notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Create Payroll Run')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pay_year.choices = _pay_year_choices()
        if self.pay_year.data is None:
            self.pay_year.data = date.today().year


class PayrollApproveForm(FlaskForm):
    """Approve payroll run."""
    notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Approve Payroll')
