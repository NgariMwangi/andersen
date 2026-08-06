"""Brevo sender email normalization."""
from app.services.brevo_service import normalize_hr_sender_email


def test_normalize_defaults_to_hrms():
    assert normalize_hr_sender_email(None) == 'hrms@nexusafrica.co.ke'
    assert normalize_hr_sender_email('') == 'hrms@nexusafrica.co.ke'


def test_normalize_replaces_legacy_and_wrong_senders():
    assert normalize_hr_sender_email('info@nexgenfuelworks.com') == 'hrms@nexusafrica.co.ke'
    assert normalize_hr_sender_email('hr@nexgenfuelworks.com') == 'hrms@nexusafrica.co.ke'
    assert normalize_hr_sender_email('admin@abzhardware.co.ke') == 'hrms@nexusafrica.co.ke'


def test_normalize_keeps_configured_hrms_address():
    assert normalize_hr_sender_email('HRMS@nexusafrica.co.ke') == 'hrms@nexusafrica.co.ke'
