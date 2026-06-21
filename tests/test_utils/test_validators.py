"""Tests for identifier and phone validators."""
from app.utils.validators import (
    validate_kra_pin,
    validate_national_id,
    validate_nhif_shif_number,
    validate_phone_ke,
    normalize_phone_ke,
)


def test_validate_kra_pin_alphanumeric():
    ok, msg = validate_kra_pin('A001234567P')
    assert ok is True
    assert msg == ''


def test_validate_kra_pin_rejects_too_long():
    ok, msg = validate_kra_pin('A' * 25)
    assert ok is False


def test_validate_national_id_digits_ok():
    ok, msg = validate_national_id('12345678')
    assert ok is True


def test_validate_national_id_mixed_characters_ok():
    ok, msg = validate_national_id('CM920941026QEK')
    assert ok is True


def test_validate_national_id_rejects_invalid_chars():
    ok, msg = validate_national_id('ID#123')
    assert ok is False


def test_validate_nhif_mixed_ok():
    ok, msg = validate_nhif_shif_number('SHIF-UG-12345')
    assert ok is True


def test_normalize_phone_ke():
    assert normalize_phone_ke('0712345678') == '+254712345678'
    assert normalize_phone_ke('254712345678') == '+254712345678'
