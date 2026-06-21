"""Brevo sender email normalization."""
from app.services.brevo_service import normalize_hr_sender_email


def test_normalize_defaults_to_hr():
    assert normalize_hr_sender_email(None) == 'hr@nexgenfuelworks.com'
    assert normalize_hr_sender_email('') == 'hr@nexgenfuelworks.com'


def test_normalize_replaces_legacy_info():
    assert normalize_hr_sender_email('info@nexgenfuelworks.com') == 'hr@nexgenfuelworks.com'


def test_normalize_keeps_other_addresses():
    assert normalize_hr_sender_email('HR@nexgenfuelworks.com') == 'hr@nexgenfuelworks.com'
