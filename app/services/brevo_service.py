"""Send transactional email via Brevo (Sendinblue) API."""
import base64
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app

logger = logging.getLogger(__name__)

BREVO_API_URL = 'https://api.brevo.com/v3/smtp/email'
DEFAULT_HR_SENDER_EMAIL = 'hrms@nexusafrica.co.ke'
LEGACY_SENDER_EMAILS = frozenset({
    'info@nexgenfuelworks.com',
    'hr@nexgenfuelworks.com',
    'admin@abzhardware.co.ke',
})


def normalize_hr_sender_email(value: str | None) -> str:
    """Prefer the Andersen HRMS sender; remap known legacy/wrong senders."""
    email = (value or '').strip().lower()
    if not email or email in LEGACY_SENDER_EMAILS:
        return DEFAULT_HR_SENDER_EMAIL
    return email


def _api_key_fingerprint(api_key: str) -> str:
    """Safe identifier for logs (never the full key)."""
    key = (api_key or '').strip()
    if not key:
        return '(missing)'
    if len(key) <= 16:
        return f'{key[:4]}…{key[-2:]} (len={len(key)})'
    return f'{key[:12]}…{key[-6:]} (len={len(key)})'


def brevo_configured() -> bool:
    api_key = (current_app.config.get('BREVO_API_KEY') or '').strip()
    sender = normalize_hr_sender_email(current_app.config.get('BREVO_SENDER_EMAIL'))
    configured = bool(api_key and sender)
    if not configured:
        logger.warning(
            'Brevo not configured: api_key=%s sender=%r',
            _api_key_fingerprint(api_key),
            sender or None,
        )
    else:
        logger.info(
            'Brevo configured: api_key=%s sender=%r sender_name=%r',
            _api_key_fingerprint(api_key),
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
    sender_name: str | None = None,
) -> bool:
    """
    Send one email through Brevo. Returns True on success, False on failure or missing config.
    """
    api_key = (current_app.config.get('BREVO_API_KEY') or '').strip()
    sender_email = normalize_hr_sender_email(current_app.config.get('BREVO_SENDER_EMAIL'))
    sender_name = (sender_name or current_app.config.get('BREVO_SENDER_NAME') or 'Andersen').strip() or 'Andersen'

    if not api_key or not sender_email:
        logger.error(
            'Email not sent to %s — Brevo not configured (api_key=%r sender=%r) subject=%r',
            to_email,
            api_key or '(missing)',
            sender_email or None,
            subject[:80] if subject else '',
        )
        return False

    logger.info(
        'Sending email to %s from %r BREVO_API_KEY=%s subject=%r',
        to_email,
        sender_email,
        api_key,
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
                logger.info(
                    'Email sent successfully to %s (HTTP %s) subject=%r',
                    to_email,
                    resp.status,
                    subject[:80] if subject else '',
                )
                return True
            logger.error(
                'Email not sent to %s — unexpected HTTP status %s subject=%r',
                to_email,
                resp.status,
                subject[:80] if subject else '',
            )
            return False
    except HTTPError as exc:
        body = ''
        try:
            body = exc.read().decode('utf-8', errors='replace')[:500]
        except Exception:
            pass
        logger.error(
            'Email not sent to %s — Brevo HTTP %s: %s',
            to_email,
            exc.code,
            body or exc.reason or str(exc),
        )
        return False
    except URLError as exc:
        logger.error(
            'Email not sent to %s — connection error: %s',
            to_email,
            exc.reason if getattr(exc, 'reason', None) else exc,
        )
        return False
    except Exception as exc:
        logger.exception('Email not sent to %s — unexpected error: %s', to_email, exc)
        return False
