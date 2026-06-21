"""Compose and reply forms for internal messages."""
from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    TextAreaField,
    SelectField,
    SelectMultipleField,
    BooleanField,
    SubmitField,
    HiddenField,
)
from wtforms.validators import DataRequired, Optional, Length, ValidationError


class ComposeMessageForm(FlaskForm):
    recipient_type = SelectField(
        'Send to',
        choices=[
            ('individual', 'One person'),
            ('group', 'Selected people'),
            ('organization', 'Whole organization'),
        ],
        validators=[DataRequired()],
        default='individual',
    )
    recipient_ids = SelectMultipleField('Recipients', coerce=int, validators=[Optional()])
    subject = StringField('Subject', validators=[DataRequired(), Length(max=300)])
    body = TextAreaField('Message', validators=[DataRequired(), Length(min=1, max=20000)])
    send_email = BooleanField('Also send email notification', default=False)
    submit = SubmitField('Send message')

    def __init__(self, *args, can_broadcast=False, **kwargs):
        self.can_broadcast = can_broadcast
        super().__init__(*args, **kwargs)
        if not can_broadcast:
            self.recipient_type.choices = [
                ('individual', 'One person'),
                ('group', 'Selected people'),
            ]

    def validate_recipient_type(self, field):
        if field.data == 'organization' and not self.can_broadcast:
            raise ValidationError('You do not have permission to message the whole organization.')

    def validate_recipient_ids(self, field):
        rtype = (self.recipient_type.data or '').strip()
        if rtype == 'organization':
            return
        ids = field.data or []
        if rtype == 'individual' and len(ids) != 1:
            raise ValidationError('Select exactly one recipient.')
        if rtype == 'group' and len(ids) < 1:
            raise ValidationError('Select at least one recipient.')


class ReplyMessageForm(FlaskForm):
    reply_to_message_id = HiddenField('Reply to', validators=[Optional()])
    body = TextAreaField('Reply', validators=[DataRequired(), Length(min=1, max=20000)])
    send_email = BooleanField('Also send email notification', default=False)
    submit = SubmitField('Send reply')
