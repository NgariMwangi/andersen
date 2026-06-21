"""Allowance create/edit forms."""
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Optional, Length


class AllowanceForm(FlaskForm):
    """Create or edit allowance type."""
    code = StringField('Code', validators=[Optional(), Length(max=50)])
    name = StringField('Name', validators=[DataRequired(), Length(max=200)])
    description = TextAreaField('Description', validators=[Optional(), Length(max=500)])
    is_taxable = BooleanField('Taxable', default=True)
    is_pensionable = BooleanField('Pensionable (for NSSF base)', default=False)
    submit = SubmitField('Save')
