"""Forms for IT helpdesk tickets."""
from flask_wtf import FlaskForm
from wtforms import SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional


class TicketForm(FlaskForm):
    category_id = SelectField('Category', coerce=int, validators=[DataRequired()])
    subject = StringField('Subject', validators=[DataRequired(), Length(max=300)])
    description = TextAreaField('Description', validators=[DataRequired(), Length(max=5000)])
    priority = SelectField('Priority', validators=[DataRequired()])
    related_asset_id = SelectField('Related asset', coerce=int, validators=[Optional()])
    submit = SubmitField('Submit ticket')


class AssignTicketForm(FlaskForm):
    assigned_to_user_id = SelectField('Assign to', coerce=int, validators=[DataRequired()])
    submit = SubmitField('Assign')


class TicketStatusForm(FlaskForm):
    status = SelectField('Status', validators=[DataRequired()])
    submit = SubmitField('Update status')


class TicketCommentForm(FlaskForm):
    body = TextAreaField('Comment', validators=[DataRequired(), Length(max=5000)])
    submit = SubmitField('Add comment')


class TicketCategoryForm(FlaskForm):
    code = StringField('Code', validators=[DataRequired(), Length(max=50)])
    name = StringField('Name', validators=[DataRequired(), Length(max=100)])
    submit = SubmitField('Save category')
