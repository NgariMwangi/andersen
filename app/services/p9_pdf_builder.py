"""
Generate KRA P9A (Tax Deduction Card) as a native PDF matching the official form layout.
Data is placed in table cells so amounts align without overlaying a flat template.
"""
from __future__ import annotations

from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.employee import Employee

PAGE_SIZE = landscape(letter)
MARGIN = 10

# 16 columns: MONTH + A..O (column E is one merged pension column)
COL_WIDTHS = [
    52,   # MONTH
    33,   # A Basic
    32,   # B Benefits
    32,   # C Quarters
    36,   # D Gross
    88,   # E Pension (NSSF)
    36,   # F AHL
    37,   # G SHIF
    42,   # H PRMF
    31,   # I Owner interest
    50,   # J Total deductions
    38,   # K Chargeable
    34,   # L Tax
    33,   # M Relief
    35,   # N Insurance relief
    30,   # O PAYE
]

_MONTH_LABELS = (
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December', 'TOTAL',
)

_DATA_KEYS = (
    'a_basic', 'b_benefits', 'c_quarters', 'd_gross', 'e_pension', 'f_ahl', 'g_shif',
    'h_prmf', 'i_owner_interest', 'j_other', 'k_chargeable', 'l_tax_charged',
    'm_personal_relief', 'n_insurance_relief', 'o_paye',
)


def _fmt_amount(value) -> str:
    if value is None:
        return ''
    d = Decimal(str(value)).quantize(Decimal('0.01'))
    if d == 0:
        return ''
    if d == d.to_integral():
        return f'{int(d):,}'
    return f'{float(d):,.2f}'


def _split_employee_names(emp: Employee) -> tuple[str, str]:
    main = (emp.last_name or '').strip()
    parts = [emp.first_name]
    if emp.middle_name:
        parts.append(emp.middle_name)
    other = ' '.join(p for p in parts if p).strip()
    if not main and other:
        bits = other.split()
        main = bits[-1] if bits else ''
        other = ' '.join(bits[:-1]) if len(bits) > 1 else ''
    return main, other


def build_p9a_context(
    *,
    calendar_year: int,
    employer_name: str,
    employer_pin: str,
    employee: Employee,
    p9a_rows: list,
    p9a_totals: dict,
) -> dict:
    main_name, other_names = _split_employee_names(employee)
    return {
        'year': str(calendar_year),
        'employer_name': employer_name or '',
        'employer_pin': employer_pin or '',
        'employee_main_name': main_name,
        'employee_other_names': other_names,
        'employee_pin': (employee.kra_pin or '').strip(),
        'p9a_rows': p9a_rows,
        'p9a_totals': p9a_totals,
    }


def _styles():
    base = getSampleStyleSheet()
    return {
        'title': ParagraphStyle(
            'p9title',
            parent=base['Normal'],
            fontName='Helvetica-Bold',
            fontSize=9,
            leading=10,
            alignment=TA_CENTER,
        ),
        'small': ParagraphStyle(
            'p9small',
            parent=base['Normal'],
            fontName='Helvetica',
            fontSize=5.5,
            leading=6,
            alignment=TA_CENTER,
        ),
        'small_left': ParagraphStyle(
            'p9smalll',
            parent=base['Normal'],
            fontName='Helvetica',
            fontSize=6,
            leading=7,
            alignment=TA_LEFT,
        ),
        'label': ParagraphStyle(
            'p9label',
            parent=base['Normal'],
            fontName='Helvetica-Bold',
            fontSize=6,
            leading=7,
            alignment=TA_LEFT,
        ),
        'value': ParagraphStyle(
            'p9value',
            parent=base['Normal'],
            fontName='Helvetica',
            fontSize=7,
            leading=8,
            alignment=TA_LEFT,
        ),
        'month': ParagraphStyle(
            'p9month',
            parent=base['Normal'],
            fontName='Helvetica',
            fontSize=6,
            leading=7,
            alignment=TA_LEFT,
        ),
        'amount': ParagraphStyle(
            'p9amt',
            parent=base['Normal'],
            fontName='Helvetica',
            fontSize=5.5,
            leading=6,
            alignment=TA_RIGHT,
        ),
        'footer': ParagraphStyle(
            'p9foot',
            parent=base['Normal'],
            fontName='Helvetica',
            fontSize=6,
            leading=7,
            alignment=TA_LEFT,
        ),
        'note': ParagraphStyle(
            'p9note',
            parent=base['Normal'],
            fontName='Helvetica',
            fontSize=4.5,
            leading=5,
            alignment=TA_LEFT,
        ),
    }


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph((text or '').replace('&', '&amp;'), style)


def _header_block(ctx: dict, st: dict) -> list:
    year = str(ctx.get('year', ''))
    yy = year[2:4] if len(year) >= 4 else year
    title = _p(
        'KENYA REVENUE AUTHORITY DOMESTIC TAXES DEPARTMENT<br/>'
        f'TAX DEDUCTION CARD YEAR 20 <b>{yy}</b>',
        st['title'],
    )
    cert = _p('ISO 9001:2015 CERTIFIED &nbsp;&nbsp; APPENDIX 2A', st['small'])

    info = Table(
        [
            [
                _p("Employer's PIN", st['label']),
                _p(ctx.get('employer_pin', ''), st['value']),
                _p("Employers Name", st['label']),
                _p(ctx.get('employer_name', ''), st['value']),
            ],
            [
                _p("Employee's Main Name", st['label']),
                _p(ctx.get('employee_main_name', ''), st['value']),
                _p("Employee's PIN", st['label']),
                _p(ctx.get('employee_pin', ''), st['value']),
            ],
            [
                _p("Employee's Other Names", st['label']),
                _p(ctx.get('employee_other_names', ''), st['value']),
                _p('', st['value']),
                _p('', st['value']),
            ],
        ],
        colWidths=[95, 175, 95, 175],
    )
    info.setStyle(
        TableStyle(
            [
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 6),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 3),
                ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
                ('SPAN', (1, 2), (3, 2)),
            ]
        )
    )
    return [cert, Spacer(1, 2), title, Spacer(1, 4), info, Spacer(1, 6)]


def _grid_table(ctx: dict, st: dict) -> Table:
    hdr1 = [
        _p('MONTH', st['small']),
        _p('Basic<br/>Salary', st['small']),
        _p('Benefits-<br/>NonCash', st['small']),
        _p('Value of<br/>Quarters', st['small']),
        _p('Total Gross<br/>Pay', st['small']),
        _p('Defined Contribution<br/>Retirement Scheme', st['small']),
        _p('Affordable<br/>Housing Levy<br/>(AHL)', st['small']),
        _p('Social Health<br/>Insurance<br/>Fund (SHIF)', st['small']),
        _p('Post<br/>Retirement<br/>Medical Fund<br/>(PRMF)', st['small']),
        _p('Owner-<br/>Occupied<br/>Interest', st['small']),
        _p('Total<br/>Deductions<br/>(Lower of E<br/>+F+G+H+I)', st['small']),
        _p('Chargeable<br/>Pay (D-J)', st['small']),
        _p('Tax<br/>Charged', st['small']),
        _p('Personal<br/>Relief', st['small']),
        _p('Insurance<br/>Relief', st['small']),
        _p('PAYE Tax<br/>(L-M-N)', st['small']),
    ]
    hdr2 = [''] + [_p('Kshs.', st['small']) for _ in range(15)]
    hdr3 = [''] + [_p(x, st['small']) for x in 'ABCDEFGHIJKLMNO']

    rows = [hdr1, hdr2, hdr3]
    rows_by_month = {int(r['month']): r for r in ctx.get('p9a_rows', [])}
    totals = ctx.get('p9a_totals') or {}

    for idx, month_name in enumerate(_MONTH_LABELS):
        if month_name == 'TOTAL':
            src = totals
        else:
            src = rows_by_month.get(idx + 1)
        row_cells = [_p(month_name, st['month'])]
        if src:
            for key in _DATA_KEYS:
                row_cells.append(_p(_fmt_amount(src.get(key)), st['amount']))
        else:
            row_cells.extend([''] * 15)
        rows.append(row_cells)

    tbl = Table(rows, colWidths=COL_WIDTHS, repeatRows=3)
    style_cmds = [
        ('GRID', (0, 0), (-1, -1), 0.4, colors.black),
        ('BACKGROUND', (0, 0), (-1, 2), colors.HexColor('#e8e8e8')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING', (0, 0), (0, -1), 3),
        ('RIGHTPADDING', (1, 0), (-1, -1), 2),
        ('FONTNAME', (0, 3), (0, -1), 'Helvetica'),
        ('FONTSIZE', (0, 3), (-1, -1), 5.5),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
    ]
    # TOTAL row emphasis
    style_cmds.append(('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f0f0f0')))
    tbl.setStyle(TableStyle(style_cmds))
    return tbl


def _footer_block(ctx: dict, st: dict) -> list:
    totals = ctx.get('p9a_totals') or {}
    k_amt = _fmt_amount(totals.get('k_chargeable'))
    o_amt = _fmt_amount(totals.get('o_paye'))
    foot = Table(
        [
            [
                _p('To be completed by Employer at end of year', st['footer']),
                '',
            ],
            [
                _p(f'TOTAL CHARGEABLE PAY (COL. K) Kshs. <b>{k_amt}</b>', st['footer']),
                _p(f'TOTAL TAX (COL. O) Kshs. <b>{o_amt}</b>', st['footer']),
            ],
        ],
        colWidths=[380, 360],
    )
    foot.setStyle(
        TableStyle(
            [
                ('SPAN', (0, 0), (1, 0)),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
            ]
        )
    )
    notes = _p(
        '<b>IMPORTANT</b> Use P9A for all liable employees. '
        'Personal Relief is Kshs. 2,400 per month or 28,800 per year. '
        'SHIF and Affordable Housing Levy (AHL) deductions apply from December 2024.',
        st['note'],
    )
    return [Spacer(1, 4), foot, Spacer(1, 4), notes]


def build_p9a_pdf(ctx: dict) -> bytes:
    """Build complete P9A PDF bytes from context dict (see build_p9a_context)."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=PAGE_SIZE,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
    )
    st = _styles()
    story = []
    story.extend(_header_block(ctx, st))
    story.append(_grid_table(ctx, st))
    story.extend(_footer_block(ctx, st))
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()
