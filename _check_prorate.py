import psycopg2

conn = psycopg2.connect(
    host='37.60.242.201',
    port=5432,
    user='postgres',
    password='deno0707',
    dbname='hrms_kenya1',
)
cur = conn.cursor()
cur.execute("""
    SELECT e.id, e.first_name, e.middle_name, e.last_name,
           e.hire_date, e.termination_date, e.prorate_payroll, e.status,
           s.effective_from AS salary_from, s.effective_to AS salary_to, s.basic_salary
    FROM employees e
    LEFT JOIN employee_salaries s ON s.employee_id = e.id
    WHERE e.first_name ILIKE '%Boniface%'
      AND (e.last_name ILIKE '%Macharia%' OR e.middle_name ILIKE '%Nduati%')
    ORDER BY s.effective_from DESC
    LIMIT 5;
""")
rows = cur.fetchall()
cols = [d[0] for d in cur.description]
print(' | '.join(cols))
print('-' * 140)
for r in rows:
    print(' | '.join(str(v) for v in r))

# Also check payroll items for this employee
if rows:
    emp_id = rows[0][0]
    print(f"\n--- Payroll items for employee_id={emp_id} ---")
    cur.execute("""
        SELECT pr.pay_month, pr.pay_year, pi.gross_pay, pi.net_pay, pi.is_pro_rata,
               pi.earnings_breakdown
        FROM payroll_items pi
        JOIN payroll_runs pr ON pr.id = pi.payroll_run_id
        WHERE pi.employee_id = %s
        ORDER BY pr.pay_year DESC, pr.pay_month DESC
        LIMIT 5;
    """, (emp_id,))
    pi_rows = cur.fetchall()
    pi_cols = [d[0] for d in cur.description]
    print(' | '.join(pi_cols))
    for r in pi_rows:
        print(' | '.join(str(v) for v in r))

conn.close()
