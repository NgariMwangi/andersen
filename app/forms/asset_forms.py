"""Forms for company assets."""
from flask_wtf import FlaskForm
from wtforms import DateField, DecimalField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class CompanyAssetForm(FlaskForm):
    category_id = SelectField('Category', coerce=int, validators=[DataRequired()])
    asset_tag = StringField('Asset tag', validators=[DataRequired(), Length(max=50)])
    name = StringField('Name / label', validators=[Optional(), Length(max=200)])
    brand = StringField('Brand', validators=[Optional(), Length(max=100)])
    model = StringField('Model', validators=[Optional(), Length(max=100)])
    serial_number = StringField('Serial number', validators=[Optional(), Length(max=100)])
    purchase_date = DateField('Purchase date', validators=[Optional()], format='%Y-%m-%d')
    purchase_value = DecimalField(
        'Purchase value',
        places=2,
        validators=[Optional(), NumberRange(min=0)],
    )
    description = TextAreaField('Description', validators=[Optional(), Length(max=2000)])
    notes = TextAreaField('Notes', validators=[Optional(), Length(max=2000)])
    status = SelectField('Status', validators=[DataRequired()])
    submit = SubmitField('Save asset')


class AssignAssetForm(FlaskForm):
    employee_id = SelectField('Employee', coerce=int, validators=[DataRequired()])
    condition_on_issue = StringField('Condition on issue', validators=[Optional(), Length(max=200)])
    notes = TextAreaField('Notes', validators=[Optional(), Length(max=2000)])
    submit = SubmitField('Assign asset')


class ReturnAssetForm(FlaskForm):
    condition_on_return = StringField('Condition on return', validators=[Optional(), Length(max=200)])
    notes = TextAreaField('Return notes', validators=[Optional(), Length(max=2000)])
    submit = SubmitField('Mark returned')


class AssetCategoryForm(FlaskForm):
    code = StringField('Code', validators=[DataRequired(), Length(max=50)])
    name = StringField('Name', validators=[DataRequired(), Length(max=100)])
    submit = SubmitField('Save category')
