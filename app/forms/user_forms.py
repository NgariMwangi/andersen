"""User management forms."""
from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    PasswordField,
    BooleanField,
    SelectField,
    SelectMultipleField,
    SubmitField,
)
from wtforms.validators import DataRequired, Email, Length, Optional


class UserForm(FlaskForm):
    """Create or edit user account."""

    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField(
        "Password (leave blank to keep current)",
        validators=[Optional(), Length(min=8)],
    )
    is_active = BooleanField("Active", default=True)
    is_superuser = BooleanField("Superuser (all permissions)", default=False)
    employee_id = SelectField("Linked Employee", coerce=int, validators=[Optional()])
    role_ids = SelectMultipleField("Roles", coerce=int, validators=[Optional()])
    submit = SubmitField("Save")

