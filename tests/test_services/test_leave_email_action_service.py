"""Signed supervisor leave email action tokens."""
from app.services.leave_email_action_service import (
    generate_leave_email_action_token,
    verify_leave_email_action_token,
)


def test_leave_email_action_token_roundtrip(app_context):
    token = generate_leave_email_action_token(
        leave_request_id=42,
        action='approve',
        supervisor_employee_id=7,
    )
    payload = verify_leave_email_action_token(token)
    assert payload == {
        'leave_request_id': 42,
        'action': 'approve',
        'supervisor_employee_id': 7,
    }


def test_leave_email_action_token_rejects_bad_action(app_context):
    try:
        generate_leave_email_action_token(
            leave_request_id=1,
            action='noop',
            supervisor_employee_id=1,
        )
        assert False, 'expected ValueError'
    except ValueError:
        pass


def test_leave_email_action_token_rejects_tampered(app_context):
    token = generate_leave_email_action_token(
        leave_request_id=1,
        action='reject',
        supervisor_employee_id=2,
    )
    assert verify_leave_email_action_token(token + 'x') is None
