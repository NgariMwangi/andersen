"""Send the employee 'Leave request received' email to a test inbox."""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from html import escape

from app import create_app
from app.extensions import db
from app.models.leave import LeaveRequest
from app.services.leave_approval_service import LEAVE_STATUS_PENDING
from app.services.leave_notification_service import (
    _app_name,
    _dates_phrase,
    _email_button,
    _highlight_box,
    _leave_index_url,
    _leave_summary_html,
    _load_leave_request,
    _wrap_email,
)
from app.services.brevo_service import brevo_configured, send_transactional_email


def main() -> int:
    to_email = (sys.argv[1] if len(sys.argv) > 1 else 'mwangingari2@gmail.com').strip()
    leave_request_id = int(sys.argv[2]) if len(sys.argv) > 2 else None

    app = create_app()
    with app.app_context(), app.test_request_context():
        if leave_request_id:
            lr = _load_leave_request(leave_request_id)
        else:
            latest = db.session.query(LeaveRequest).order_by(LeaveRequest.id.desc()).first()
            lr = _load_leave_request(latest.id) if latest else None
        if not lr or not lr.employee:
            print('FAIL: leave request not found or employee missing')
            return 1

        emp = lr.employee
        app_name = _app_name()
        dates = _dates_phrase(lr)
        if lr.status == LEAVE_STATUS_PENDING:
            wait_msg = (
                'Please wait for your <strong>supervisor</strong> and <strong>HR</strong> '
                'to review and confirm your leave.'
            )
            wait_text = 'Please wait for your supervisor and HR to review and confirm your leave.'
        else:
            wait_msg = 'Please wait for <strong>HR</strong> to review and confirm your leave.'
            wait_text = 'Please wait for HR to review and confirm your leave.'

        subject = f'{app_name} — Leave request received'
        body = (
            f'<p style="margin:0 0 16px;font-size:17px;color:#243444;">'
            f'Hello <strong>{escape(emp.first_name or emp.full_name)}</strong>,</p>'
            f'{_highlight_box(f"Your leave request has been received for <strong>{escape(dates)}</strong>.", tone="info")}'
            f'<p style="margin:0 0 16px;">{wait_msg}</p>'
            f'{_leave_summary_html(lr, include_employee=False)}'
            f'<p style="margin:16px 0 0;color:#64748b;font-size:13px;text-align:center;">'
            f'You will receive another email when your supervisor or HR responds.</p>'
            f'{_email_button("View my leave requests", _leave_index_url())}'
        )
        text = (
            f'Hello {emp.first_name or emp.full_name},\n\n'
            f'Your leave request has been received.\n'
            f'You requested leave on {dates}.\n\n'
            f'{wait_text}\n\n'
            f'View leave: {_leave_index_url()}\n'
        )
        if not brevo_configured():
            print('FAIL: Brevo not configured')
            return 1
        ok = send_transactional_email(
            to_email,
            subject,
            _wrap_email(
                title='Leave request received',
                subtitle='We received your request',
                body_html=body,
                preheader=f'Leave requested for {dates}',
                employee=emp,
            ),
            text_content=text,
        )
        if ok:
            print(f'OK: sent leave request received test to {to_email}')
            print(f'    leave_request_id={lr.id} sample_employee={emp.full_name}')
            return 0
        print(f'FAIL: Brevo did not accept send to {to_email}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
