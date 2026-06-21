"""
Validators for employee identifiers and contact details.
Kenya-specific formats are not enforced — IDs may be alphanumeric (e.g. Uganda NIN).
"""
import re

# Letters, digits, and common separators used on national/statutory IDs
IDENTIFIER_PATTERN = re.compile(r'^[\w\s\-/.]+$', re.UNICODE)


def validate_optional_identifier(
    value: str,
    *,
    field_name: str = 'Value',
    max_length: int = 50,
) -> tuple[bool, str]:
    """
    Optional ID / reference number: allow mixed letters and digits.
    Returns (is_valid, error_message).
    """
    if not value or not value.strip():
        return True, ''
    value = value.strip()
    if len(value) > max_length:
        return False, f'{field_name} must be at most {max_length} characters.'
    if not IDENTIFIER_PATTERN.match(value):
        return False, (
            f'{field_name} may only contain letters, numbers, spaces, and - / . _'
        )
    return True, ''


def validate_kra_pin(value: str) -> tuple[bool, str]:
    """Tax ID / PIN (Kenya KRA or equivalent) — alphanumeric, not digits-only."""
    return validate_optional_identifier(value, field_name='Tax PIN', max_length=20)


def validate_national_id(value: str) -> tuple[bool, str]:
    """National ID / NIN — alphanumeric (e.g. Uganda, Kenya, other countries)."""
    return validate_optional_identifier(value, field_name='National ID', max_length=30)


def validate_nssf_number(value: str) -> tuple[bool, str]:
    """Social security / pension reference number."""
    return validate_optional_identifier(value, field_name='NSSF number', max_length=30)


def validate_nhif_shif_number(value: str) -> tuple[bool, str]:
    """Health insurance / SHIF reference number."""
    return validate_optional_identifier(value, field_name='NHIF/SHIF number', max_length=30)


COUNTRY_PHONE_CONFIG: dict[str, dict] = {
    'KE': {'code': '254', 'local_len': 9, 'label': 'Kenyan'},
    'UG': {'code': '256', 'local_len': 9, 'label': 'Ugandan'},
    'TZ': {'code': '255', 'local_len': 9, 'label': 'Tanzanian'},
}


def normalize_phone(value: str, country_code: str | None = None) -> str:
    """Normalize a phone number to +{dialing_code}{local} based on country."""
    if not value or not value.strip():
        return ''
    value = re.sub(r'[\s\-]+', '', value.strip())
    if value.startswith('+') and len(value) >= 10:
        return value
    cc = (country_code or 'KE').upper()[:2]
    cfg = COUNTRY_PHONE_CONFIG.get(cc, COUNTRY_PHONE_CONFIG['KE'])
    dial = cfg['code']
    if value.startswith(dial):
        return '+' + value
    if value.startswith('0'):
        return '+' + dial + value[1:]
    if len(value) == cfg['local_len'] and value[0].isdigit():
        return '+' + dial + value
    return value


def normalize_phone_ke(value: str) -> str:
    """Normalize Kenyan phone to +254XXXXXXXXX (legacy wrapper)."""
    return normalize_phone(value, 'KE')


def validate_phone(value: str, country_code: str | None = None) -> tuple[bool, str]:
    """Validate phone number for the given country."""
    if not value or not value.strip():
        return True, ''
    cleaned = re.sub(r'[\s\-]+', '', value.strip())
    if cleaned.startswith('+') and len(cleaned) >= 10:
        return True, ''
    normalized = normalize_phone(value, country_code)
    cc = (country_code or 'KE').upper()[:2]
    cfg = COUNTRY_PHONE_CONFIG.get(cc)
    if cfg:
        expected_len = len(cfg['code']) + cfg['local_len'] + 1
        if len(normalized) < expected_len:
            return False, f'Invalid {cfg["label"]} phone number.'
    else:
        if len(normalized) < 10:
            return False, 'Phone number too short.'
    return True, ''


def validate_phone_ke(value: str) -> tuple[bool, str]:
    """Validate Kenyan phone (legacy wrapper)."""
    return validate_phone(value, 'KE')
