"""Send the urgent leave document re-upload email to a test inbox."""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from html import escape

from app import create_app
from app.extensions import db
from app.models.leave import LeaveRequest
from app.services.brevo_service import brevo_configured, send_transactional_email
from app.services.leave_notification_service import (
    BRAND_PRIMARY,
    BRAND_SLATE,
    _app_name,
    _dates_phrase,
    _email_button,
    _highlight_box,
    _leave_summary_html,
    _load_leave_request,
    _portal_base,
    _wrap_email,
)
from flask import url_for


def main() -> int:
    to_email = (sys.argv[1] if len(sys.argv) > 1 else 'mwangingari2@gmail.com').strip()
    leave_request_id = int(sys.argv[2]) if len(sys.argv) > 2 else None

    app = create_app()
    with app.app_context(), app.test_request_context():
        if leave_request_id:
            lr = _load_leave_request(leave_request_id)
        else:
            latest = (
                db.session.query(LeaveRequest)
                .filter(LeaveRequest.document_path.isnot(None))
                .order_by(LeaveRequest.id.desc())
                .first()
            )
            if not latest:
                latest = db.session.query(LeaveRequest).order_by(LeaveRequest.id.desc()).first()
            lr = _load_leave_request(latest.id) if latest else None
        if not lr or not lr.employee:
            print('FAIL: leave request not found or employee missing')
            return 1

        emp = lr.employee
        app_name = _app_name()
        dates = _dates_phrase(lr)
        reupload_url = _portal_base() + url_for('leave.reupload_document', id=lr.id)
        lt_name = lr.leave_type.name if lr.leave_type else 'leave'
        first = escape(emp.first_name or emp.full_name)

        subject = f'{app_name} — Urgent: re-upload leave supporting document'
        detail_html = (
            f'There was a storage issue with the supporting document you uploaded for your '
            f'<strong>{escape(lt_name)}</strong> request ({escape(dates)}). '
            f'The file is no longer available and <strong>must be re-uploaded urgently</strong>.'
        )
        body = (
            f'<p style="margin:0 0 16px;font-size:17px;color:{BRAND_SLATE};">'
            f'Hello <strong>{first}</strong>,</p>'
            f'{_highlight_box(detail_html, tone="danger")}'
            f'<p style="margin:0 0 16px;">Please open the portal and upload the document again as soon as possible '
            f'so HR can complete review of your leave request.</p>'
            f'{_leave_summary_html(lr, include_employee=False)}'
            f'{_email_button("Re-upload document now", reupload_url)}'
            f'<p style="margin:16px 0 0;font-size:13px;color:#64748b;text-align:center;">'
            f'Or open: <a href="{escape(reupload_url)}" style="color:{BRAND_PRIMARY};">{escape(reupload_url)}</a></p>'
        )
        text = (
            f'Hello {emp.first_name or emp.full_name},\n\n'
            f'There was a storage issue with the supporting document you uploaded for your '
            f'{lt_name} request ({dates}). The file is no longer available and must be '
            f're-uploaded urgently.\n\n'
            f'Re-upload here: {reupload_url}\n'
        )

        if not brevo_configured():
            print('FAIL: Brevo not configured')
            return 1

        ok = send_transactional_email(
            to_email,
            subject,
            _wrap_email(
                title='Re-upload required',
                subtitle='Urgent — supporting document missing',
                body_html=body,
                preheader=f'Urgent: re-upload document for {lt_name} leave',
                employee=emp,
            ),
            text_content=text,
        )
        if ok:
            print(f'OK: sent re-upload email to {to_email}')
            print(f'    leave_request_id={lr.id} sample_employee={emp.full_name}')
            print(f'    reupload_url={reupload_url}')
            return 0
        print(f'FAIL: Brevo did not accept send to {to_email}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
