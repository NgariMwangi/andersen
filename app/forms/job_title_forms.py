"""Job title create/edit forms."""
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Optional, Length


class JobTitleForm(FlaskForm):
    """Create or edit job title."""
    code = StringField('Code', validators=[Optional(), Length(max=50)])
    name = StringField('Name', validators=[DataRequired(), Length(max=200)])
    description = TextAreaField('Description', validators=[Optional(), Length(max=2000)])
    grade = StringField('Grade', validators=[Optional(), Length(max=50)], description='e.g. G5, G6')
    submit = SubmitField('Save')
