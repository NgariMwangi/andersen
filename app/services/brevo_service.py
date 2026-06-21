"""Send transactional email via Brevo (Sendinblue) API."""
import base64
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app

logger = logging.getLogger(__name__)

BREVO_API_URL = 'https://api.brevo.com/v3/smtp/email'
DEFAULT_HR_SENDER_EMAIL = 'hr@nexgenfuelworks.com'
LEGACY_SENDER_EMAIL = 'info@nexgenfuelworks.com'


def normalize_hr_sender_email(value: str | None) -> str:
    """Use hr@ for all outbound mail; migrate away from legacy info@."""
    email = (value or '').strip().lower()
    if not email or email == LEGACY_SENDER_EMAIL:
        return DEFAULT_HR_SENDER_EMAIL
    return email


def brevo_configured() -> bool:
    api_key = (current_app.config.get('BREVO_API_KEY') or '').strip()
    sender = normalize_hr_sender_email(current_app.config.get('BREVO_SENDER_EMAIL'))
    configured = bool(api_key and sender)
    if not configured:
        logger.warning(
            'Brevo not configured: api_key_set=%s sender=%r',
            bool(api_key),
            sender or None,
        )
    else:
        logger.info(
            'Brevo configured: api_key_len=%s sender=%r sender_name=%r',
            len(api_key),
            sender,
            (current_app.config.get('BREVO_SENDER_NAME') or '').strip() or None,
        )
    return configured


def send_transactional_email(
    to_email: str,
    subject: str,
    html_content: str,
    *,
    text_content: str | None = None,
    attachments: list[tuple[str, bytes]] | None = None,
) -> bool:
    """
    Send one email through Brevo. Returns True on success, False on failure or missing config.
    """
    api_key = (current_app.config.get('BREVO_API_KEY') or '').strip()
    sender_email = normalize_hr_sender_email(current_app.config.get('BREVO_SENDER_EMAIL'))
    sender_name = (current_app.config.get('BREVO_SENDER_NAME') or 'HR NexGen Fuelworks').strip() or 'HR NexGen Fuelworks'

    if not api_key or not sender_email:
        logger.warning(
            'Brevo send skipped — missing config (api_key_set=%s sender=%r) to=%s subject=%r',
            bool(api_key),
            sender_email or None,
            to_email,
            subject[:80] if subject else '',
        )
        return False

    logger.info(
        'Brevo sending email to=%s from=%r subject=%r',
        to_email,
        sender_email,
        subject[:80] if subject else '',
    )

    payload = {
        'sender': {'name': sender_name, 'email': sender_email},
        'to': [{'email': to_email}],
        'subject': subject,
        'htmlContent': html_content,
    }
    if text_content:
        payload['textContent'] = text_content
    if attachments:
        payload['attachment'] = [
            {
                'name': name,
                'content': base64.b64encode(content).decode('ascii'),
            }
            for name, content in attachments
            if name and content
        ]

    req = Request(
        BREVO_API_URL,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'accept': 'application/json',
            'api-key': api_key,
            'content-type': 'application/json',
        },
        method='POST',
    )
    try:
        with urlopen(req, timeout=30) as resp:
            if 200 <= resp.status < 300:
                logger.info('Brevo email sent OK to=%s status=%s', to_email, resp.status)
                return True
            logger.error('Brevo API unexpected status %s for %s', resp.status, to_email)
            return False
    except HTTPError as exc:
        body = ''
        try:
            body = exc.read().decode('utf-8', errors='replace')[:500]
        except Exception:
            pass
        logger.error('Brevo API HTTP error %s for %s: %s', exc.code, to_email, body)
        return False
    except URLError as exc:
        logger.error('Brevo API connection error for %s: %s', to_email, exc)
        return False
