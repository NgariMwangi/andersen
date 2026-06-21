"""Forms for company branches (sites / jurisdictions)."""
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length, Optional, Regexp


class BranchForm(FlaskForm):
    name = StringField('Branch name', validators=[DataRequired(), Length(min=1, max=200)])
    country_code = StringField(
        'Country (ISO 3166-1 alpha-2)',
        default='KE',
        validators=[DataRequired(), Length(min=2, max=2)],
    )
    currency_code = StringField(
        'Currency (ISO 4217, optional)',
        validators=[
            Optional(),
            Length(min=3, max=3),
            Regexp(r'^[A-Za-z]{3}$', message='Use a 3-letter code such as KES or UGX.'),
        ],
        description='Leave blank to use the default for this country (e.g. KE → KES).',
    )
    timezone = StringField(
        'Timezone (optional)',
        validators=[Optional(), Length(max=64)],
        description='e.g. Africa/Nairobi',
    )
    submit = SubmitField('Save')
