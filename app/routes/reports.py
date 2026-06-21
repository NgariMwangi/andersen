"""Report generation."""
import csv
from datetime import date, datetime
from io import BytesIO, StringIO
from decimal import Decimal
from xml.sax.saxutils import escape as _xml_escape

from flask import Blueprint, abort, current_app, render_template, request, send_file
from flask_login import login_required, current_user
from app.decorators.permissions import permission_required
from app.decorators.features import require_payroll
from app.extensions import db
from app.utils.tenant import require_company_id
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.models.payroll import PayrollRun, PayrollItem, PayrollStatutoryRemittance
from app.models.employee import Employee
from app.models.department import Department
from app.models.employer import Employer
from app.models.leave import LeaveRequest
from app.models.overtime import OvertimeRequest
from app.services.p9_service import MONTH_NAMES, row_for_employee, rows_for_csv
from app.services.p9_template_service import build_p9a_overlay_context, fill_p9a_template_pdf
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

reports_bp = Blueprint('reports', __name__)
PDF_MARGIN = 12


@reports_bp.route('/')
@login_required
@permission_required('view_reports')
def index():
    return render_template('reports/index.html')


def _employee_list_query():
    """Build filtered Employee query with department/job_title/branch loaded."""
    cid = require_company_id()
    q = (
        db.session.query(Employee)
        .filter(Employee.company_id == cid)
        .options(
            joinedload(Employee.department),
            joinedload(Employee.job_title),
            joinedload(Employee.branch),
        )
    )
    status = request.args.get('status', '').strip()
    department_id = request.args.get('department_id', type=int)
    branch_id = request.args.get('branch_id', type=int)
    search = request.args.get('q', '').strip()
    if status:
        q = q.filter(Employee.status == status)
    if department_id:
        q = q.filter(Employee.department_id == department_id)
    if branch_id:
        q = q.filter(Employee.branch_id == branch_id)
    if search:
        like = f'%{search}%'
        q = q.filter(
            db.or_(
                Employee.first_name.ilike(like),
                Employee.last_name.ilike(like),
                Employee.employee_number.ilike(like),
                Employee.email.ilike(like),
            )
        )
    return q.order_by(Employee.employee_number)


def _get_employer_name_pin(company_id: int, default_name='Employer', default_pin='—'):
    """Employer identifiers used in documents; falls back to config for backward compatibility."""
    emp = db.session.query(Employer).filter(Employer.company_id == company_id).first()
    config_name = current_app.config.get('EMPLOYER_NAME') or ''
    config_pin = current_app.config.get('EMPLOYER_KRA_PIN') or ''

    name = (emp.name if emp and emp.name else '') or config_name or default_name
    pin = (emp.kra_pin if emp and emp.kra_pin else '') or config_pin or default_pin
    return name, pin


def _p9_access_own_only() -> bool:
    """True when user may only view their own P9 (not full reports permission)."""
    return bool(current_user.is_authenticated and not current_user.has_permission('view_reports'))


def _p9_require_employee_access(employee_id: int) -> None:
    """403 unless same-tenant HR reports access or viewing own employee record."""
    emp = db.session.get(Employee, employee_id)
    if not emp:
        abort(404)
    cid = getattr(current_user, 'company_id', None)
    if cid is not None and emp.company_id != cid:
        abort(403)
    if current_user.has_permission('view_reports'):
        return
    if not current_user.employee_id or int(current_user.employee_id) != int(employee_id):
        abort(403)


@reports_bp.route('/employee-list')
@login_required
@permission_required('view_reports')
def employee_list():
    employees = _employee_list_query().all()
    cid = require_company_id()
    departments = (
        db.session.query(Department)
        .filter(Department.company_id == cid)
        .order_by(Department.name)
        .all()
    )
    from app.models.company import Branch

    branches = (
        db.session.query(Branch)
        .filter(Branch.company_id == cid)
        .order_by(Branch.name)
        .all()
    )
    return render_template(
        'reports/employee_list.html',
        employees=employees,
        departments=departments,
        branches=branches,
    )


@reports_bp.route('/employee-list/csv')
@login_required
@permission_required('view_reports')
def employee_list_csv():
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment

    employees = _employee_list_query().all()
    wb = Workbook()
    ws = wb.active
    ws.title = 'Employee List'

    headers = [
        'Employee No.', 'Full Name', 'Email', 'Phone', 'Branch',
        'Department', 'Job Title', 'Status', 'Hire Date',
        'KRA/TIN', 'NSSF', 'SHIF/NHIF',
        'Bank Name', 'Bank Branch', 'Account Number', 'Bank Code', 'SWIFT Code',
    ]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal='center')

    for e in employees:
        ws.append([
            e.employee_number or '',
            e.full_name,
            (e.email or '').strip(),
            (e.phone or '').strip(),
            e.branch.name if e.branch else '',
            e.department.name if e.department else '',
            e.job_title.name if e.job_title else '',
            e.status or '',
            e.hire_date.isoformat() if e.hire_date else '',
            (e.kra_pin or '').strip(),
            (e.nssf_number or '').strip(),
            (e.nhif_number or '').strip(),
            (e.bank_name or '').strip(),
            (e.bank_branch or '').strip(),
            (e.bank_account_number or '').strip(),
            (e.bank_code or '').strip(),
            (e.swift_code or '').strip(),
        ])

    ws.freeze_panes = 'C2'

    for col in ws.columns:
        max_len = 0
        col_letter = col[0].column_letter
        for cell in col:
            if cell.value:
                max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[col_letter].width = min(max_len + 2, 30)

    out = BytesIO()
    wb.save(out)
    out.seek(0)
    return send_file(
        out,
        as_attachment=True,
        download_name='employee-list.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


@reports_bp.route('/payroll-summary')
@login_required
@permission_required('view_reports')
@require_payroll
def payroll_summary():
    return render_template('reports/payroll_summary.html')


def _executive_summary_payload(company_id: int):
    """Aggregate executive metrics for exportable summary documents."""
    from app.models.company import Branch
    from app.models.consultant import Consultant, ConsultantPayrollItem
    from app.services.leave_approval_service import count_all_open_leave_approvals
    from app.utils.currency import currency_for_country

    today = date.today()
    month_start = date(today.year, today.month, 1)

    active_employees = (
        db.session.query(func.count(Employee.id))
        .filter(Employee.company_id == company_id, Employee.status == 'active')
        .scalar() or 0
    )
    total_employees = (
        db.session.query(func.count(Employee.id))
        .filter(Employee.company_id == company_id)
        .scalar() or 0
    )
    pending_leave = count_all_open_leave_approvals(company_id)
    pending_overtime = (
        db.session.query(func.count(OvertimeRequest.id))
        .filter(OvertimeRequest.company_id == company_id, OvertimeRequest.status == 'pending')
        .scalar() or 0
    )
    new_hires = (
        db.session.query(func.count(Employee.id))
        .filter(Employee.company_id == company_id, Employee.hire_date >= month_start)
        .scalar() or 0
    )
    exits = (
        db.session.query(func.count(Employee.id))
        .filter(
            Employee.company_id == company_id,
            Employee.termination_date.isnot(None),
            Employee.termination_date >= month_start,
        )
        .scalar() or 0
    )

    # Headcount by status
    status_counts = (
        db.session.query(Employee.status, func.count(Employee.id))
        .filter(Employee.company_id == company_id)
        .group_by(Employee.status)
        .all()
    )

    # Headcount by branch
    branch_counts = (
        db.session.query(Branch.name, Branch.country_code, func.count(Employee.id))
        .join(Employee, Employee.branch_id == Branch.id)
        .filter(Employee.company_id == company_id, Employee.status == 'active')
        .group_by(Branch.name, Branch.country_code)
        .order_by(func.count(Employee.id).desc())
        .all()
    )

    # Headcount by department
    dept_counts = (
        db.session.query(Department.name, func.count(Employee.id))
        .join(Employee, Employee.department_id == Department.id)
        .filter(Employee.company_id == company_id, Employee.status == 'active')
        .group_by(Department.name)
        .order_by(func.count(Employee.id).desc())
        .all()
    )

    # Headcount by employment type
    type_counts = (
        db.session.query(Employee.employment_type, func.count(Employee.id))
        .filter(Employee.company_id == company_id, Employee.status == 'active')
        .group_by(Employee.employment_type)
        .all()
    )

    # Active consultants
    active_consultants = (
        db.session.query(func.count(Consultant.id))
        .filter(Consultant.company_id == company_id, Consultant.status == 'active')
        .scalar() or 0
    )

    # Latest payroll (include drafts)
    latest_run = (
        db.session.query(PayrollRun)
        .filter(PayrollRun.company_id == company_id)
        .order_by(PayrollRun.pay_year.desc(), PayrollRun.pay_month.desc(), PayrollRun.id.desc())
        .first()
    )
    payroll_by_branch = []
    payroll_period = None
    if latest_run:
        payroll_period = f'{latest_run.pay_month}/{latest_run.pay_year}'
        runs_for_period = (
            db.session.query(PayrollRun)
            .filter(
                PayrollRun.company_id == company_id,
                PayrollRun.pay_year == latest_run.pay_year,
                PayrollRun.pay_month == latest_run.pay_month,
            )
            .all()
        )
        for run in runs_for_period:
            staff_gross, staff_net, staff_count = (
                db.session.query(
                    func.coalesce(func.sum(PayrollItem.gross_pay), 0),
                    func.coalesce(func.sum(PayrollItem.net_pay), 0),
                    func.count(PayrollItem.id),
                )
                .filter(PayrollItem.payroll_run_id == run.id)
                .one()
            )
            con_gross, con_net, con_count = (
                db.session.query(
                    func.coalesce(func.sum(ConsultantPayrollItem.gross_pay), 0),
                    func.coalesce(func.sum(ConsultantPayrollItem.net_pay), 0),
                    func.count(ConsultantPayrollItem.id),
                )
                .filter(ConsultantPayrollItem.payroll_run_id == run.id)
                .one()
            )
            payroll_by_branch.append({
                'country_code': run.country_code or 'KE',
                'currency': currency_for_country(run.country_code),
                'status': run.status,
                'staff_count': int(staff_count or 0),
                'staff_gross': Decimal(str(staff_gross or 0)),
                'staff_net': Decimal(str(staff_net or 0)),
                'consultant_count': int(con_count or 0),
                'consultant_gross': Decimal(str(con_gross or 0)),
                'consultant_net': Decimal(str(con_net or 0)),
                'total_net': Decimal(str(staff_net or 0)) + Decimal(str(con_net or 0)),
            })

    # Legacy single-run payroll for CSV/PDF backward compatibility
    latest_payroll = {
        'period': payroll_period or 'N/A',
        'employees_paid': sum(b['staff_count'] for b in payroll_by_branch),
        'gross_paid': sum((b['staff_gross'] for b in payroll_by_branch), Decimal('0')),
        'net_paid': sum((b['staff_net'] for b in payroll_by_branch), Decimal('0')),
    }

    return {
        'generated_at': datetime.now(),
        'active_employees': active_employees,
        'total_employees': total_employees,
        'active_consultants': active_consultants,
        'pending_leave': pending_leave,
        'pending_overtime': pending_overtime,
        'new_hires_this_month': new_hires,
        'exits_this_month': exits,
        'status_counts': status_counts,
        'branch_counts': branch_counts,
        'dept_counts': dept_counts,
        'type_counts': type_counts,
        'payroll_period': payroll_period,
        'payroll_by_branch': payroll_by_branch,
        'latest_payroll': latest_payroll,
    }


@reports_bp.route('/executive-summary')
@login_required
@permission_required('view_reports')
@require_payroll
def executive_summary():
    cid = require_company_id()
    employer_name, employer_pin = _get_employer_name_pin(cid, default_name='Company', default_pin='—')
    summary = _executive_summary_payload(cid)
    import json as _json
    from app.utils.currency import currency_for_country
    from app.models.consultant import ConsultantPayrollItem
    from collections import OrderedDict

    trend_runs = (
        db.session.query(
            PayrollRun.pay_year,
            PayrollRun.pay_month,
            PayrollRun.country_code,
            func.coalesce(func.sum(PayrollItem.net_pay), 0).label('staff_net'),
        )
        .outerjoin(PayrollItem, PayrollItem.payroll_run_id == PayrollRun.id)
        .filter(PayrollRun.company_id == cid)
        .group_by(PayrollRun.pay_year, PayrollRun.pay_month, PayrollRun.country_code)
        .order_by(PayrollRun.pay_year, PayrollRun.pay_month)
        .all()
    )
    trend_consultant = (
        db.session.query(
            PayrollRun.pay_year,
            PayrollRun.pay_month,
            PayrollRun.country_code,
            func.coalesce(func.sum(ConsultantPayrollItem.net_pay), 0).label('con_net'),
        )
        .outerjoin(ConsultantPayrollItem, ConsultantPayrollItem.payroll_run_id == PayrollRun.id)
        .filter(PayrollRun.company_id == cid)
        .group_by(PayrollRun.pay_year, PayrollRun.pay_month, PayrollRun.country_code)
        .order_by(PayrollRun.pay_year, PayrollRun.pay_month)
        .all()
    )
    con_lookup = {}
    for r in trend_consultant:
        con_lookup[(r.pay_year, r.pay_month, r.country_code)] = float(r.con_net or 0)

    all_countries = sorted({r.country_code or 'KE' for r in trend_runs})
    colors = ['#0d6efd', '#198754', '#dc3545', '#ffc107', '#6f42c1', '#20c997']
    payroll_charts = []

    for i, cc in enumerate(all_countries):
        months_data = OrderedDict()
        for r in trend_runs:
            if (r.country_code or 'KE') != cc:
                continue
            label = f"{r.pay_month:02d}/{r.pay_year}"
            con_net = con_lookup.get((r.pay_year, r.pay_month, r.country_code), 0)
            months_data[label] = float(r.staff_net or 0) + con_net

        chart_labels = list(months_data.keys())[-12:]
        chart_data = [months_data.get(lbl, 0) for lbl in chart_labels]
        currency = currency_for_country(cc)
        payroll_charts.append({
            'id': f'payrollChart_{cc}',
            'title': f'{cc} — {currency}',
            'data_json': _json.dumps({
                'labels': chart_labels,
                'datasets': [{
                    'label': f'Net Pay ({currency})',
                    'data': chart_data,
                    'borderColor': colors[i % len(colors)],
                    'backgroundColor': colors[i % len(colors)] + '33',
                    'tension': 0.3,
                    'fill': True,
                }]
            }),
        })

    return render_template(
        'reports/executive_summary.html',
        summary=summary,
        employer_name=employer_name,
        employer_pin=employer_pin,
        payroll_charts=payroll_charts,
    )


@reports_bp.route('/executive-summary/csv')
@login_required
@permission_required('view_reports')
@require_payroll
def executive_summary_csv():
    cid = require_company_id()
    employer_name, employer_pin = _get_employer_name_pin(cid, default_name='Company', default_pin='—')
    s = _executive_summary_payload(cid)
    si = StringIO()
    w = csv.writer(si)
    w.writerow(['metric', 'value'])
    w.writerow(['generated_at', s['generated_at'].isoformat(timespec='seconds')])
    w.writerow(['company_name', employer_name])
    w.writerow(['company_kra_pin', employer_pin])
    w.writerow(['active_employees', s['active_employees']])
    w.writerow(['pending_leave_approvals', s['pending_leave']])
    w.writerow(['pending_overtime_approvals', s['pending_overtime']])
    w.writerow(['new_hires_this_month', s['new_hires_this_month']])
    w.writerow(['exits_this_month', s['exits_this_month']])
    w.writerow(['latest_payroll_period', s['latest_payroll']['period']])
    w.writerow(['latest_payroll_employees_paid', s['latest_payroll']['employees_paid']])
    w.writerow(['latest_payroll_gross_paid', str(s['latest_payroll']['gross_paid'])])
    w.writerow(['latest_payroll_net_paid', str(s['latest_payroll']['net_paid'])])
    out = BytesIO()
    out.write(si.getvalue().encode('utf-8-sig'))
    out.seek(0)
    return send_file(
        out,
        as_attachment=True,
        download_name='executive-summary.csv',
        mimetype='text/csv; charset=utf-8',
    )


@reports_bp.route('/executive-summary/pdf')
@login_required
@permission_required('view_reports')
@require_payroll
def executive_summary_pdf():
    cid = require_company_id()
    employer_name, employer_pin = _get_employer_name_pin(cid, default_name='Company', default_pin='—')
    s = _executive_summary_payload(cid)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=PDF_MARGIN,
        rightMargin=PDF_MARGIN,
        topMargin=18,
        bottomMargin=18,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph('Executive Summary Report', styles['Title']),
        Paragraph(f'Company: {_xml_escape(employer_name)}', styles['Normal']),
        Paragraph(f'KRA PIN: {_xml_escape(employer_pin)}', styles['Normal']),
        Paragraph(f'Generated: {_xml_escape(s["generated_at"].strftime("%d/%m/%Y %H:%M"))}', styles['Normal']),
        Spacer(1, 12),
    ]
    table_data = [
        ['Metric', 'Value'],
        ['Active employees', str(s['active_employees'])],
        ['Pending leave approvals', str(s['pending_leave'])],
        ['Pending overtime approvals', str(s['pending_overtime'])],
        ['New hires this month', str(s['new_hires_this_month'])],
        ['Exits this month', str(s['exits_this_month'])],
        ['Latest payroll period', s['latest_payroll']['period']],
        ['Employees paid (latest payroll)', str(s['latest_payroll']['employees_paid'])],
        ['Gross paid (latest payroll)', f"{s['latest_payroll']['gross_paid']:,.2f}"],
        ['Net paid (latest payroll)', f"{s['latest_payroll']['net_paid']:,.2f}"],
    ]
    t = Table(table_data, repeatRows=1, colWidths=[doc.width * 0.65, doc.width * 0.35], hAlign='LEFT')
    t.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e9ecef')),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f8f9fa')),
            ]
        )
    )
    story.append(t)
    doc.build(story)
    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name='executive-summary.pdf',
        mimetype='application/pdf',
    )


def _build_nssf_rows(run_id: int):
    """Return NSSF per-employee rows and totals for one approved run."""
    rows = (
        db.session.query(PayrollStatutoryRemittance)
        .filter(
            PayrollStatutoryRemittance.payroll_run_id == run_id,
            PayrollStatutoryRemittance.statutory_code.in_(['NSSF_EMPLOYEE', 'NSSF_EMPLOYER']),
        )
        .order_by(PayrollStatutoryRemittance.employee_id, PayrollStatutoryRemittance.statutory_code)
        .all()
    )
    by_employee = {}
    for r in rows:
        key = r.employee_id
        if key not in by_employee:
            by_employee[key] = {
                'employee': r.employee,
                'nssf_number': (r.employee.nssf_number if r.employee else None) or '-',
                'employee_cont': Decimal('0.00'),
                'employer_cont': Decimal('0.00'),
            }
        if r.statutory_code == 'NSSF_EMPLOYEE':
            by_employee[key]['employee_cont'] += Decimal(str(r.amount or 0))
        elif r.statutory_code == 'NSSF_EMPLOYER':
            by_employee[key]['employer_cont'] += Decimal(str(r.amount or 0))

    out = []
    total_employee = Decimal('0.00')
    total_employer = Decimal('0.00')
    for emp_id, entry in by_employee.items():
        employee_name = entry['employee'].full_name if entry['employee'] else f'Employee #{emp_id}'
        total = (entry['employee_cont'] + entry['employer_cont']).quantize(Decimal('0.01'))
        total_employee += entry['employee_cont']
        total_employer += entry['employer_cont']
        out.append(
            {
                'employee_id': emp_id,
                'nssf_number': entry['nssf_number'],
                'employee_name': employee_name,
                'employee_cont': entry['employee_cont'].quantize(Decimal('0.01')),
                'employer_cont': entry['employer_cont'].quantize(Decimal('0.01')),
                'total': total,
            }
        )
    out.sort(key=lambda x: x['employee_name'])
    grand_total = (total_employee + total_employer).quantize(Decimal('0.01'))
    return out, total_employee.quantize(Decimal('0.01')), total_employer.quantize(Decimal('0.01')), grand_total


@reports_bp.route('/nssf')
@login_required
@permission_required('view_reports')
@require_payroll
def nssf_report():
    cid = require_company_id()
    runs = (
        db.session.query(PayrollRun)
        .filter(PayrollRun.status == 'approved', PayrollRun.company_id == cid)
        .order_by(PayrollRun.pay_year.desc(), PayrollRun.pay_month.desc())
        .all()
    )
    selected_run_id = request.args.get('run_id', type=int)
    selected_run = None
    rows = []
    total_employee = Decimal('0.00')
    total_employer = Decimal('0.00')
    grand_total = Decimal('0.00')
    if selected_run_id:
        selected_run = db.session.get(PayrollRun, selected_run_id)
        if selected_run and selected_run.status == 'approved' and selected_run.company_id == cid:
            rows, total_employee, total_employer, grand_total = _build_nssf_rows(selected_run_id)
        else:
            selected_run = None
    return render_template(
        'reports/nssf_report.html',
        runs=runs,
        selected_run=selected_run,
        rows=rows,
        total_employee=total_employee,
        total_employer=total_employer,
        grand_total=grand_total,
    )


@reports_bp.route('/nssf/pdf')
@login_required
@permission_required('view_reports')
@require_payroll
def nssf_report_pdf():
    run_id = request.args.get('run_id', type=int)
    run_obj = db.session.get(PayrollRun, run_id) if run_id else None
    cid = require_company_id()
    if not run_obj or run_obj.status != 'approved' or run_obj.company_id != cid:
        from flask import abort
        abort(400)

    rows, total_employee, total_employer, grand_total = _build_nssf_rows(run_obj.id)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=PDF_MARGIN,
        rightMargin=PDF_MARGIN,
        topMargin=18,
        bottomMargin=18,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("NSSF Payments Report", styles['Title']),
        Paragraph(f"Payroll Period: {run_obj.pay_month}/{run_obj.pay_year}", styles['Normal']),
        Spacer(1, 12),
    ]
    table_data = [['NSSF No', 'Employee Name', 'Employee Cont', 'Employer Cont', 'Total']]
    for r in rows:
        table_data.append(
            [
                r['nssf_number'],
                r['employee_name'],
                f"{r['employee_cont']:,.2f}",
                f"{r['employer_cont']:,.2f}",
                f"{r['total']:,.2f}",
            ]
        )
    table_data.append(['', 'TOTAL', f"{total_employee:,.2f}", f"{total_employer:,.2f}", f"{grand_total:,.2f}"])
    table = Table(
        table_data,
        repeatRows=1,
        colWidths=[doc.width * 0.16, doc.width * 0.34, doc.width * 0.17, doc.width * 0.17, doc.width * 0.16],
        hAlign='LEFT',
    )
    table.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e9ecef')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f8f9fa')),
            ]
        )
    )
    story.append(table)
    doc.build(story)
    buffer.seek(0)
    filename = f"nssf-payments-{run_obj.pay_year}-{run_obj.pay_month:02d}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')


def _build_paye_rows(run_id: int):
    """Return PAYE rows per employee and total for one approved run."""
    rows = (
        db.session.query(PayrollStatutoryRemittance)
        .filter(
            PayrollStatutoryRemittance.payroll_run_id == run_id,
            PayrollStatutoryRemittance.statutory_code == 'PAYE',
        )
        .order_by(PayrollStatutoryRemittance.employee_id)
        .all()
    )
    out = []
    total = Decimal('0.00')
    for r in rows:
        amount = Decimal(str(r.amount or 0)).quantize(Decimal('0.01'))
        emp_name = r.employee.full_name if r.employee else f'Employee #{r.employee_id}'
        pin = (r.employee.kra_pin if r.employee else None) or '-'
        out.append(
            {
                'employee_id': r.employee_id,
                'pin': pin,
                'employee_name': emp_name,
                'paye_amount': amount,
            }
        )
        total += amount
    out.sort(key=lambda x: x['employee_name'])
    return out, total.quantize(Decimal('0.01'))


@reports_bp.route('/paye')
@login_required
@permission_required('view_reports')
@require_payroll
def paye_report():
    cid = require_company_id()
    runs = (
        db.session.query(PayrollRun)
        .filter(PayrollRun.status == 'approved', PayrollRun.company_id == cid)
        .order_by(PayrollRun.pay_year.desc(), PayrollRun.pay_month.desc())
        .all()
    )
    selected_run_id = request.args.get('run_id', type=int)
    selected_run = None
    rows = []
    total = Decimal('0.00')
    if selected_run_id:
        selected_run = db.session.get(PayrollRun, selected_run_id)
        if selected_run and selected_run.status == 'approved' and selected_run.company_id == cid:
            rows, total = _build_paye_rows(selected_run_id)
        else:
            selected_run = None
    return render_template(
        'reports/paye_report.html',
        runs=runs,
        selected_run=selected_run,
        rows=rows,
        total=total,
    )


@reports_bp.route('/paye/pdf')
@login_required
@permission_required('view_reports')
@require_payroll
def paye_report_pdf():
    run_id = request.args.get('run_id', type=int)
    run_obj = db.session.get(PayrollRun, run_id) if run_id else None
    cid = require_company_id()
    if not run_obj or run_obj.status != 'approved' or run_obj.company_id != cid:
        from flask import abort
        abort(400)

    rows, total = _build_paye_rows(run_obj.id)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=PDF_MARGIN,
        rightMargin=PDF_MARGIN,
        topMargin=18,
        bottomMargin=18,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("PAYE Report", styles['Title']),
        Paragraph(f"Payroll Period: {run_obj.pay_month}/{run_obj.pay_year}", styles['Normal']),
        Spacer(1, 12),
    ]
    table_data = [['PIN', 'Employee Name', 'PAYE Amount']]
    for r in rows:
        table_data.append([r['pin'], r['employee_name'], f"{r['paye_amount']:,.2f}"])
    table_data.append(['', 'TOTAL', f"{total:,.2f}"])
    table = Table(
        table_data,
        repeatRows=1,
        colWidths=[doc.width * 0.28, doc.width * 0.47, doc.width * 0.25],
        hAlign='LEFT',
    )
    table.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e9ecef')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('ALIGN', (2, 1), (2, -1), 'RIGHT'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f8f9fa')),
            ]
        )
    )
    story.append(table)
    doc.build(story)
    buffer.seek(0)
    filename = f"paye-report-{run_obj.pay_year}-{run_obj.pay_month:02d}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')


def _build_sha_rows(run_id: int):
    """Return SHA (SHIF) rows per employee and total for one approved run."""
    rows = (
        db.session.query(PayrollStatutoryRemittance)
        .filter(
            PayrollStatutoryRemittance.payroll_run_id == run_id,
            PayrollStatutoryRemittance.statutory_code == 'SHIF',
        )
        .order_by(PayrollStatutoryRemittance.employee_id)
        .all()
    )
    out = []
    total = Decimal('0.00')
    for r in rows:
        amount = Decimal(str(r.amount or 0)).quantize(Decimal('0.01'))
        emp_name = r.employee.full_name if r.employee else f'Employee #{r.employee_id}'
        sha_no = (r.employee.nhif_number if r.employee else None) or '-'
        out.append(
            {
                'employee_id': r.employee_id,
                'sha_no': sha_no,
                'employee_name': emp_name,
                'sha_amount': amount,
            }
        )
        total += amount
    out.sort(key=lambda x: x['employee_name'])
    return out, total.quantize(Decimal('0.01'))


@reports_bp.route('/sha')
@login_required
@permission_required('view_reports')
@require_payroll
def sha_report():
    cid = require_company_id()
    runs = (
        db.session.query(PayrollRun)
        .filter(PayrollRun.status == 'approved', PayrollRun.company_id == cid)
        .order_by(PayrollRun.pay_year.desc(), PayrollRun.pay_month.desc())
        .all()
    )
    selected_run_id = request.args.get('run_id', type=int)
    selected_run = None
    rows = []
    total = Decimal('0.00')
    if selected_run_id:
        selected_run = db.session.get(PayrollRun, selected_run_id)
        if selected_run and selected_run.status == 'approved' and selected_run.company_id == cid:
            rows, total = _build_sha_rows(selected_run_id)
        else:
            selected_run = None
    return render_template(
        'reports/sha_report.html',
        runs=runs,
        selected_run=selected_run,
        rows=rows,
        total=total,
    )


@reports_bp.route('/sha/pdf')
@login_required
@permission_required('view_reports')
@require_payroll
def sha_report_pdf():
    run_id = request.args.get('run_id', type=int)
    run_obj = db.session.get(PayrollRun, run_id) if run_id else None
    cid = require_company_id()
    if not run_obj or run_obj.status != 'approved' or run_obj.company_id != cid:
        from flask import abort
        abort(400)

    rows, total = _build_sha_rows(run_obj.id)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=PDF_MARGIN,
        rightMargin=PDF_MARGIN,
        topMargin=18,
        bottomMargin=18,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("SHA (SHIF) Report", styles['Title']),
        Paragraph(f"Payroll Period: {run_obj.pay_month}/{run_obj.pay_year}", styles['Normal']),
        Spacer(1, 12),
    ]
    table_data = [['SHA No', 'Employee Name', 'SHA Amount']]
    for r in rows:
        table_data.append([r['sha_no'], r['employee_name'], f"{r['sha_amount']:,.2f}"])
    table_data.append(['', 'TOTAL', f"{total:,.2f}"])
    table = Table(
        table_data,
        repeatRows=1,
        colWidths=[doc.width * 0.28, doc.width * 0.47, doc.width * 0.25],
        hAlign='LEFT',
    )
    table.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e9ecef')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('ALIGN', (2, 1), (2, -1), 'RIGHT'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f8f9fa')),
            ]
        )
    )
    story.append(table)
    doc.build(story)
    buffer.seek(0)
    filename = f"sha-report-{run_obj.pay_year}-{run_obj.pay_month:02d}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')


def _build_housing_levy_rows(run_id: int):
    """
    Return Housing Levy rows per employee and totals for one approved run.
    Employee contribution comes from statutory snapshots (HOUSING_LEVY).
    Employer contribution is mirrored 1:1 for reporting purposes.
    """
    rows = (
        db.session.query(PayrollStatutoryRemittance)
        .filter(
            PayrollStatutoryRemittance.payroll_run_id == run_id,
            PayrollStatutoryRemittance.statutory_code == 'HOUSING_LEVY',
        )
        .order_by(PayrollStatutoryRemittance.employee_id)
        .all()
    )
    out = []
    total_employee = Decimal('0.00')
    total_employer = Decimal('0.00')
    for r in rows:
        employee_cont = Decimal(str(r.amount or 0)).quantize(Decimal('0.01'))
        employer_cont = employee_cont
        emp_name = r.employee.full_name if r.employee else f'Employee #{r.employee_id}'
        pin = (r.employee.kra_pin if r.employee else None) or '-'
        total = (employee_cont + employer_cont).quantize(Decimal('0.01'))
        out.append(
            {
                'employee_id': r.employee_id,
                'pin': pin,
                'employee_name': emp_name,
                'employee_cont': employee_cont,
                'employer_cont': employer_cont,
                'total': total,
            }
        )
        total_employee += employee_cont
        total_employer += employer_cont
    out.sort(key=lambda x: x['employee_name'])
    grand_total = (total_employee + total_employer).quantize(Decimal('0.01'))
    return (
        out,
        total_employee.quantize(Decimal('0.01')),
        total_employer.quantize(Decimal('0.01')),
        grand_total,
    )


@reports_bp.route('/housing-levy')
@login_required
@permission_required('view_reports')
@require_payroll
def housing_levy_report():
    cid = require_company_id()
    runs = (
        db.session.query(PayrollRun)
        .filter(PayrollRun.status == 'approved', PayrollRun.company_id == cid)
        .order_by(PayrollRun.pay_year.desc(), PayrollRun.pay_month.desc())
        .all()
    )
    selected_run_id = request.args.get('run_id', type=int)
    selected_run = None
    rows = []
    total_employee = Decimal('0.00')
    total_employer = Decimal('0.00')
    grand_total = Decimal('0.00')
    if selected_run_id:
        selected_run = db.session.get(PayrollRun, selected_run_id)
        if selected_run and selected_run.status == 'approved' and selected_run.company_id == cid:
            rows, total_employee, total_employer, grand_total = _build_housing_levy_rows(selected_run_id)
        else:
            selected_run = None
    return render_template(
        'reports/housing_levy_report.html',
        runs=runs,
        selected_run=selected_run,
        rows=rows,
        total_employee=total_employee,
        total_employer=total_employer,
        grand_total=grand_total,
    )


@reports_bp.route('/housing-levy/pdf')
@login_required
@permission_required('view_reports')
@require_payroll
def housing_levy_report_pdf():
    run_id = request.args.get('run_id', type=int)
    run_obj = db.session.get(PayrollRun, run_id) if run_id else None
    cid = require_company_id()
    if not run_obj or run_obj.status != 'approved' or run_obj.company_id != cid:
        from flask import abort
        abort(400)

    rows, total_employee, total_employer, grand_total = _build_housing_levy_rows(run_obj.id)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=PDF_MARGIN,
        rightMargin=PDF_MARGIN,
        topMargin=18,
        bottomMargin=18,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Housing Levy Report", styles['Title']),
        Paragraph(f"Payroll Period: {run_obj.pay_month}/{run_obj.pay_year}", styles['Normal']),
        Spacer(1, 12),
    ]
    table_data = [['PIN', 'Employee Name', 'Employee Cont', 'Employer Cont', 'Total']]
    for r in rows:
        table_data.append(
            [
                r['pin'],
                r['employee_name'],
                f"{r['employee_cont']:,.2f}",
                f"{r['employer_cont']:,.2f}",
                f"{r['total']:,.2f}",
            ]
        )
    table_data.append(['', 'TOTAL', f"{total_employee:,.2f}", f"{total_employer:,.2f}", f"{grand_total:,.2f}"])
    table = Table(
        table_data,
        repeatRows=1,
        colWidths=[doc.width * 0.16, doc.width * 0.34, doc.width * 0.17, doc.width * 0.17, doc.width * 0.16],
        hAlign='LEFT',
    )
    table.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e9ecef')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f8f9fa')),
            ]
        )
    )
    story.append(table)
    doc.build(story)
    buffer.seek(0)
    filename = f"housing-levy-report-{run_obj.pay_year}-{run_obj.pay_month:02d}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')


@reports_bp.route('/p9')
@login_required
@require_payroll
def p9_report():
    """P9-style annual PAYE (calendar year) from approved payroll runs."""
    cid = require_company_id()
    can_view_all = current_user.has_permission('view_reports')
    if _p9_access_own_only() and not current_user.employee_id:
        abort(403)
    year_list = [
        r[0]
        for r in db.session.query(PayrollRun.pay_year)
        .filter(PayrollRun.status == 'approved', PayrollRun.company_id == cid)
        .distinct()
        .order_by(PayrollRun.pay_year.desc())
        .all()
    ]
    if not year_list:
        year_list = [date.today().year]
    if can_view_all:
        employees = (
            db.session.query(Employee)
            .filter(Employee.status == 'active', Employee.company_id == cid)
            .order_by(Employee.first_name, Employee.last_name)
            .all()
        )
    else:
        own = db.session.get(Employee, current_user.employee_id)
        employees = [own] if own and own.company_id == cid else []
    selected_year = request.args.get('year', type=int)
    selected_employee_id = request.args.get('employee_id', type=int)
    if not can_view_all:
        selected_employee_id = current_user.employee_id
    preview = None
    if selected_year and selected_employee_id:
        preview = row_for_employee(selected_year, selected_employee_id, cid)
    employer = db.session.query(Employer).filter(Employer.company_id == cid).first()
    employer_display_name, employer_display_pin = _get_employer_name_pin(
        cid,
        default_name='—',
        default_pin='—',
    )
    return render_template(
        'reports/p9_report.html',
        year_list=year_list,
        employees=employees,
        selected_year=selected_year,
        selected_employee_id=selected_employee_id,
        preview=preview,
        month_names=MONTH_NAMES,
        employer=employer,
        employer_display_name=employer_display_name,
        employer_display_pin=employer_display_pin,
        can_view_all_p9=can_view_all,
    )


@reports_bp.route('/p9/pdf')
@login_required
@require_payroll
def p9_pdf():
    """Download KRA P9A tax deduction card PDF filled from approved payroll."""
    year = request.args.get('year', type=int)
    employee_id = request.args.get('employee_id', type=int)
    if not year or not employee_id:
        abort(400)
    _p9_require_employee_access(employee_id)
    cid = require_company_id()
    data = row_for_employee(year, employee_id, cid)
    if not data:
        abort(404)
    emp = data['employee']
    employer_name, employer_pin = _get_employer_name_pin(cid, default_name='Employer', default_pin='—')
    ctx = build_p9a_overlay_context(
        calendar_year=year,
        employer_name=employer_name,
        employer_pin=employer_pin,
        employee=emp,
        p9a_rows=data.get('p9a_rows') or [],
        p9a_totals=data.get('p9a_totals') or {},
    )
    pdf_bytes = fill_p9a_template_pdf(ctx)
    buffer = BytesIO(pdf_bytes)
    buffer.seek(0)
    safe_name = (emp.last_name or 'employee').replace(' ', '-')
    filename = f"P9A-{year}-{safe_name}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')


@reports_bp.route('/p9/csv')
@login_required
@require_payroll
def p9_csv():
    """iTax-oriented CSV: one row per employee, monthly PAYE + yearly P9 totals."""
    year = request.args.get('year', type=int)
    employee_id = request.args.get('employee_id', type=int)
    if not year:
        abort(400)
    cid = require_company_id()
    if _p9_access_own_only():
        if not current_user.employee_id:
            abort(403)
        employee_id = current_user.employee_id
    rows = rows_for_csv(year, cid)
    if employee_id:
        _p9_require_employee_access(employee_id)
        rows = [r for r in rows if r['employee_id'] == employee_id]
    employer_name, employer_pin = _get_employer_name_pin(cid, default_name='', default_pin='')
    si = StringIO()
    w = csv.writer(si)
    header = [
        'employer_kra_pin',
        'employer_name',
        'employee_number',
        'employee_kra_pin',
        'employee_name',
        'gross_pay_yearly',
        'benefits_other_cash_yearly',
        'chargeable_income_paye_basis_yearly',
        'tax_before_personal_relief_yearly',
        'personal_relief_applied_yearly',
        'paye_deducted_yearly',
        'nssf_employee_yearly',
        'nssf_employer_yearly',
        'shif_yearly',
        'housing_levy_employee_yearly',
    ] + [f'paye_{m:02d}_{MONTH_NAMES[m - 1].lower()}' for m in range(1, 13)]
    w.writerow(header)
    for r in rows:
        w.writerow(
            [
                employer_pin,
                employer_name,
                r['employee_number'],
                r['pin'],
                r['name'],
                str(r['gross_pay_yearly']),
                str(r['benefits_yearly']),
                str(r['chargeable_income_yearly']),
                str(r['tax_before_relief_yearly']),
                str(r['personal_relief_yearly']),
                str(r['total_paye']),
                str(r['nssf_employee_yearly']),
                str(r['nssf_employer_yearly']),
                str(r['shif_yearly']),
                str(r['housing_levy_yearly']),
            ]
            + [str(r[f'm{m}']) for m in range(1, 13)]
        )
    out = BytesIO()
    out.write(si.getvalue().encode('utf-8-sig'))
    out.seek(0)
    suffix = f'-emp-{employee_id}' if employee_id else '-all'
    filename = f"p9-itax-{year}{suffix}.csv"
    return send_file(
        out,
        as_attachment=True,
        download_name=filename,
        mimetype='text/csv; charset=utf-8',
    )
