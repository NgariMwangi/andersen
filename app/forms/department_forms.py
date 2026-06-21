"""Department create/edit forms."""
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, SubmitField
from wtforms.validators import DataRequired, Optional, Length

from app.forms.employee_forms import _coerce_optional_int


class DepartmentForm(FlaskForm):
    """Create or edit department."""
    code = StringField('Code', validators=[Optional(), Length(max=50)])
    name = StringField('Name', validators=[DataRequired(), Length(max=200)])
    description = TextAreaField('Description', validators=[Optional(), Length(max=2000)])
    parent_id = SelectField('Parent Department', coerce=_coerce_optional_int, validators=[Optional()])
    submit = SubmitField('Save')
